import random
import asyncio
import os
from typing import TypedDict
from dotenv import load_dotenv
from supabase import create_client
from langgraph.graph import StateGraph, START, END

load_dotenv()

supabase_url = os.getenv("SUPABASE_URL")
supabase_key = os.getenv("SUPABASE_KEY")
supabase = create_client(supabase_url, supabase_key)


# ── Incident generator functions (unchanged from agents/monitoring_agent.py) ──

def generate_response_time_incident():
    value = random.randint(1000, 4000)
    severity = "high" if value >= 3000 else "medium" if value >= 2000 else "low"
    return {
        "problem_type": "high_response_time",
        "problem_detail": f"Response time spiked to {value}ms",
        "severity": severity
    }


def generate_cpu_incident():
    value = random.randint(85, 99)
    severity = "high" if value >= 95 else "medium" if value >= 90 else "low"
    return {
        "problem_type": "high_cpu_usage",
        "problem_detail": f"CPU usage spiked to {value}%",
        "severity": severity
    }


def generate_memory_incident():
    value = random.randint(85, 98)
    severity = "high" if value >= 95 else "medium" if value >= 90 else "low"
    return {
        "problem_type": "memory_leak",
        "problem_detail": f"Memory usage climbed to {value}% and rising",
        "severity": severity
    }


def generate_disk_incident():
    free_gb = random.randint(1, 5)
    severity = "high" if free_gb <= 2 else "medium"
    return {
        "problem_type": "disk_space_low",
        "problem_detail": f"Disk usage critical, only {free_gb}GB free",
        "severity": severity
    }


def generate_db_incident():
    failed = random.randint(5, 20)
    severity = "high" if failed >= 15 else "medium" if failed >= 10 else "low"
    return {
        "problem_type": "database_connection_failure",
        "problem_detail": f"Database connection pool exhausted, {failed} failed connections",
        "severity": severity
    }


INCIDENT_GENERATORS = [
    generate_response_time_incident,
    generate_cpu_incident,
    generate_memory_incident,
    generate_disk_incident,
    generate_db_incident,
]


def generate_incident():
    generator = random.choice(INCIDENT_GENERATORS)
    return generator()


# ── LangGraph State definition ──

class IncidentState(TypedDict):
    id: int
    problem_type: str
    problem_detail: str
    severity: str
    status: str


# ── LangGraph Node: wraps the monitoring logic ──

def monitoring_node(state: IncidentState) -> dict:
    incident = generate_incident()
    incident_id = random.randint(10000, 99999)

    print(f"ALERT: {incident['problem_type']} detected! Severity: {incident['severity']}")

    try:
        supabase.table("incident_log").insert({
            "id": incident_id,
            "problem_type": incident["problem_type"],
            "problem_detail": incident["problem_detail"],
            "severity": incident["severity"]
        }).execute()
        print("Incident logged in database!")
    except Exception as e:
        print(f"ERROR logging incident: {e}")

    return {
        "id": incident_id,
        "problem_type": incident["problem_type"],
        "problem_detail": incident["problem_detail"],
        "severity": incident["severity"],
        "status": "detected"
    }


# ── Build the graph (currently just one node, for testing) ──

graph_builder = StateGraph(IncidentState)
graph_builder.add_node("monitoring", monitoring_node)
graph_builder.add_edge(START, "monitoring")
graph_builder.add_edge("monitoring", END)
graph = graph_builder.compile()


# ── Outer trigger loop: decides WHEN to start a new graph run ──

async def start_monitoring_loop():
    while True:
        is_anomaly = random.random() < 0.3

        if is_anomaly:
            result = graph.invoke({})
            print("Graph run finished. Final state:", result)
        else:
            print("Normal. No anomaly detected.")

        await asyncio.sleep(5)


# ── Entry point to actually run this test file ──

if __name__ == "__main__":
    asyncio.run(start_monitoring_loop())