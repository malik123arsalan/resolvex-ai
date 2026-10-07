import random
import asyncio
import os
from dotenv import load_dotenv
from supabase import create_client
from agents.state import IncidentState

# Load secrets (Supabase URL and key) from the .env file
load_dotenv()

# Create one Supabase client that this file uses to talk to the database
supabase_url = os.getenv("SUPABASE_URL")
supabase_key = os.getenv("SUPABASE_KEY")
supabase = create_client(supabase_url, supabase_key)


# ---------------------------------------------------------------
# Incident generators
# Each function simulates one type of problem. In a real system,
# this data would come from a monitoring tool like Prometheus.
# ---------------------------------------------------------------
def generate_response_time_incident():
    # Pick a slow response time between 1000ms and 4000ms
    value = random.randint(1000, 4000)
    # Higher response time means higher severity
    severity = "high" if value >= 3000 else "medium" if value >= 2000 else "low"
    return {
        "problem_type": "high_response_time",
        "problem_detail": f"Response time spiked to {value}ms",
        "severity": severity
    }


def generate_cpu_incident():
     # Simulate CPU usage in the danger zone (85% to 99%)
    value = random.randint(85, 99)
    severity = "high" if value >= 95 else "medium" if value >= 90 else "low"
    return {
        "problem_type": "high_cpu_usage",
        "problem_detail": f"CPU usage spiked to {value}%",
        "severity": severity
    }


def generate_memory_incident():
    # Simulate high memory usage (85% to 98%)
    value = random.randint(85, 98)
    severity = "high" if value >= 95 else "medium" if value >= 90 else "low"
    return {
        "problem_type": "memory_leak",
        "problem_detail": f"Memory usage climbed to {value}% and rising",
        "severity": severity
    }


def generate_disk_incident():
    # For disk, LOWER free space is worse, so the comparison is reversed
    free_gb = random.randint(1, 5)
    severity = "high" if free_gb <= 2 else "medium"
    return {
        "problem_type": "disk_space_low",
        "problem_detail": f"Disk usage critical, only {free_gb}GB free",
        "severity": severity
    }


def generate_db_incident():
    # Simulate failed database connections (5 to 20 failures)
    failed = random.randint(5, 20)
    severity = "high" if failed >= 15 else "medium" if failed >= 10 else "low"
    return {
        "problem_type": "database_connection_failure",
        "problem_detail": f"Database connection pool exhausted, {failed} failed connections",
        "severity": severity
    }


# List of all generator functions (stored without brackets, so they are not called yet).
# To support a new incident type, write a new function and add it here.
INCIDENT_GENERATORS = [
    generate_response_time_incident,
    generate_cpu_incident,
    generate_memory_incident,
    generate_disk_incident,
    generate_db_incident,
]


def generate_incident():
    # Randomly choose one generator and run it to get a new incident
    generator = random.choice(INCIDENT_GENERATORS)
    return generator()


# ---------------------------------------------------------------
# LangGraph node
# This is the first step of the graph. It receives the shared state
# and returns only the fields it wants to update.
# ---------------------------------------------------------------
def monitoring_node(state: IncidentState) -> dict:
    # Create a new incident and give it a random ID
    incident = generate_incident()
    incident_id = random.randint(10000, 99999)

# Save the incident in the database.
# The thread_id links this row to the graph run, so the dashboard
# can resume the correct paused run when a human approves or rejects.
    try:
        supabase.table("incident_log").insert({
            "id": incident_id,
            "problem_type": incident["problem_type"],
            "problem_detail": incident["problem_detail"],
            "severity": incident["severity"],
            "thread_id": state.get("thread_id")   
        }).execute()
    except Exception as e:
        # If saving fails, we only print the error and let the graph continue
        print(f"ERROR logging incident: {e}")

# Update the shared state so the next agent (Detective) can start.
# Status "detected" marks the beginning of the incident lifecycle.
    return {
        "id": incident_id,
        "problem_type": incident["problem_type"],
        "problem_detail": incident["problem_detail"],
        "severity": incident["severity"],
        "status": "detected"
    }