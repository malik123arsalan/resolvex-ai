import random
import asyncio
import os
from dotenv import load_dotenv
from supabase import create_client

load_dotenv()

supabase_url = os.getenv("SUPABASE_URL")
supabase_key = os.getenv("SUPABASE_KEY")
supabase = create_client(supabase_url, supabase_key)


def generate_normal_response_time():
    return random.randint(100, 999)

def generate_anomaly_response_time():
    return random.randint(1000, 4000)

def generate_response_time():
    # 90% chance normal, 10% chance anomaly (like real life)
    if random.random() < 0.9:
        return generate_normal_response_time()
    else:
        return generate_anomaly_response_time()

THRESHOLD = 1000

def check_for_anomaly(response_time):
    if response_time >= THRESHOLD:
        return True
    else:
        return False


async def start_monitoring():
    while True:
        current_response_time = generate_response_time()
        is_anomaly = check_for_anomaly(current_response_time)

        if is_anomaly:
            print(f"ALERT: Anomaly detected! Response time: {current_response_time}ms")

            supabase.table("incident_log").insert({
                "id": random.randint(10000, 99999),
                "problem_type": "high_response_time",
                "problem_detail": f"Response time spiked to {current_response_time}ms",
                "severity": "high"
            }).execute()

            print("Incident automatically logged in database!")
        else:
            print(f"Normal. Response time: {current_response_time}ms")

        await asyncio.sleep(3)
