import os
import json
from dotenv import load_dotenv
from supabase import create_client
from pydantic import BaseModel
from typing import Literal
from groq import Groq
from agents.state import IncidentState

load_dotenv()

supabase_url = os.getenv("SUPABASE_URL")
supabase_key = os.getenv("SUPABASE_KEY")
supabase = create_client(supabase_url, supabase_key)

groq_client = Groq(api_key=os.getenv("GROQ_API_KEY"))


class FixPlan(BaseModel):
    fix_description: str
    risk_level: Literal["low", "medium", "high"]
    reasoning: str


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
    return FixPlan(**raw_data)


def update_incident_with_plan(incident_id, fix_plan_result):
    combined_fix_plan = f"Fix: {fix_plan_result.fix_description} | Reasoning: {fix_plan_result.reasoning}"
    supabase.table("incident_log").update({
        "status": "planned",
        "fix_plan": combined_fix_plan,
        "risk_level": fix_plan_result.risk_level
    }).eq("id", incident_id).execute()


# LangGraph node
def planning_node(state: IncidentState) -> dict:
    try:
        print(f"Planning fix for incident ID: {state['id']}")

        fix_plan_result = suggest_fix(state['root_cause'])
        combined_fix_plan = f"Fix: {fix_plan_result.fix_description} | Reasoning: {fix_plan_result.reasoning}"
        update_incident_with_plan(state['id'], fix_plan_result)

        print(f"Incident {state['id']} planned. Risk level: {fix_plan_result.risk_level}")

        return {
            "fix_plan": combined_fix_plan,
            "risk_level": fix_plan_result.risk_level,
            "status": "planned"
        }
    except Exception as e:
        print(f"ERROR planning fix for incident {state['id']}: {e}")
        return {"status": "planning_failed"}