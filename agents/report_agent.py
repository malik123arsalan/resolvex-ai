import os
import json
from dotenv import load_dotenv
from groq import Groq
from supabase import create_client
from pydantic import BaseModel, Field
from agents.state import IncidentState
from agents.detective_agent import collection  # reuse the same ChromaDB collection

load_dotenv()

supabase_url = os.getenv("SUPABASE_URL")
supabase_key = os.getenv("SUPABASE_KEY")
supabase = create_client(supabase_url, supabase_key)

groq_client = Groq(api_key=os.getenv("GROQ_API_KEY"))


class IncidentReport(BaseModel):
    summary: str = Field(max_length=300)
    root_cause_recap: str = Field(max_length=200)
    fix_applied: str = Field(max_length=200)
    outcome: str = Field(max_length=150)
    additional_notes: str = Field(max_length=200, default="")


def generate_report(state: IncidentState):
    prompt = f"""
Here is a resolved incident. Write a clear post-incident report.

Problem Type: {state['problem_type']}
Problem Detail: {state['problem_detail']}
Severity: {state['severity']}
Root Cause: {state['root_cause']}
Fix Plan: {state['fix_plan']}
Risk Level: {state['risk_level']}
Final Status: {state['status']}

Respond in valid JSON with these exact keys:
- summary (2-3 sentences, max 300 characters, what happened)
- root_cause_recap (1-2 sentences, max 200 characters, why it happened)
- fix_applied (1-2 sentences, max 200 characters, what fix was applied)
- outcome (1 sentence, max 150 characters, final result)
- additional_notes (1-2 sentences, max 200 characters, extra insight — empty string if none)

Keep every field short and strictly within the character limits given.
"""

    response = groq_client.chat.completions.create(
        model="openai/gpt-oss-120b",
        messages=[
            {"role": "system", "content": "You are an expert DevOps engineer writing concise post-incident reports. Always respond in valid JSON only, respecting character limits strictly."},
            {"role": "user", "content": prompt}
        ],
        response_format={"type": "json_object"}
    )

    raw_data = json.loads(response.choices[0].message.content)
    return IncidentReport(**raw_data)


def save_report_to_supabase(incident_id, report):
    supabase.table("incident_reports").insert({
        "incident_id": incident_id,
        "summary": report.summary,
        "root_cause_recap": report.root_cause_recap,
        "fix_applied": report.fix_applied,
        "outcome": report.outcome,
        "additional_notes": report.additional_notes
    }).execute()


def save_report_to_chromadb(incident_id, report):
    combined_text = (
        f"Summary: {report.summary} "
        f"Root Cause: {report.root_cause_recap} "
        f"Fix Applied: {report.fix_applied} "
        f"Outcome: {report.outcome} "
        f"Notes: {report.additional_notes}"
    )
    collection.add(documents=[combined_text], ids=[f"report_{incident_id}"])


def mark_as_reported(incident_id):
    supabase.table("incident_log").update({"status": "reported"}).eq("id", incident_id).execute()


# LangGraph node
def report_node(state: IncidentState) -> dict:
    try:
        print(f"Generating report for incident ID: {state['id']}")

        report = generate_report(state)
        save_report_to_supabase(state['id'], report)
        save_report_to_chromadb(state['id'], report)
        mark_as_reported(state['id'])

        print(f"Report completed for incident {state['id']}")
        return {"status": "reported"}
    except Exception as e:
        print(f"ERROR generating report for incident {state['id']}: {e}")
        return {"status": "report_failed"}