import os
import asyncio
from dotenv import load_dotenv
from supabase import create_client
from pydantic import BaseModel
from typing import Literal
import json
from groq import Groq

load_dotenv()

supabase_url = os.getenv("SUPABASE_URL")
supabase_key = os.getenv("SUPABASE_KEY")
supabase = create_client(supabase_url, supabase_key)


groq_client = Groq(api_key=os.getenv("GROQ_API_KEY"))

class FixPlan(BaseModel):
    fix_description: str
    risk_level: Literal["low", "medium", "high"]
    reasoning: str


def get_analyzed_incidents():
    response = supabase.table("incident_log").select("*").eq("status", "analyzed").execute()
    return response.data


def suggest_fix(root_cause):
    prompt = f"""
The root cause of a DevOps incident has been identified as: {root_cause}

Suggest a practical fix for this issue. Classify how risky it would be to apply this fix automatically.
"""

    response = groq_client.chat.completions.create(
        model="openai/gpt-oss-120b",
        messages=[
            {"role": "system", "content": "You are an expert DevOps engineer. Always respond in valid JSON format with keys: fix_description, risk_level, reasoning. risk_level must be exactly one of: low, medium, high."},
            {"role": "user", "content": prompt}
        ],
        response_format={"type": "json_object"}
    )

    raw_data = json.loads(response.choices[0].message.content)
    validated_result = FixPlan(**raw_data)

    return validated_result


def update_incident_with_plan(incident_id, fix_plan_result):
    combined_fix_plan = f"Fix: {fix_plan_result.fix_description} | Reasoning: {fix_plan_result.reasoning}"

    supabase.table("incident_log").update({
        "status": "planned",
        "fix_plan": combined_fix_plan,
        "risk_level": fix_plan_result.risk_level
    }).eq("id", incident_id).execute()


async def start_planning_agent():
    while True:
        analyzed_incidents = get_analyzed_incidents()

        if analyzed_incidents:
            for incident in analyzed_incidents:
                try:
                    print(f"Planning fix for incident ID: {incident['id']}")

                    fix_plan_result = suggest_fix(incident['root_cause'])
                    update_incident_with_plan(incident['id'], fix_plan_result)

                    print(f"Incident {incident['id']} planned. Risk level: {fix_plan_result.risk_level}")
                except Exception as e:
                    print(f"ERROR planning fix for incident {incident['id']}: {e}")
        else:
            print("No analyzed incidents. Waiting...")

        await asyncio.sleep(7)