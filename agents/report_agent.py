import os
from dotenv import load_dotenv
from supabase import create_client
from groq import Groq
import json
import chromadb
from pydantic import BaseModel, Field
import asyncio

load_dotenv()

supabase_url = os.getenv("SUPABASE_URL")
supabase_key = os.getenv("SUPABASE_KEY")
supabase = create_client(supabase_url, supabase_key)


groq_client = Groq(api_key=os.getenv("GROQ_API_KEY"))

chroma_client = chromadb.PersistentClient(path="./chroma_data")
collection = chroma_client.get_or_create_collection(name="incidents")


class IncidentReport(BaseModel):
    summary: str = Field(max_length=300)
    root_cause_recap: str = Field(max_length=200)
    fix_applied: str = Field(max_length=200)
    outcome: str = Field(max_length=150)
    additional_notes: str = Field(max_length=200, default="")


# Part A — fetch incidents that are resolved but not yet reported
def get_reportable_incidents():
    response = supabase.table("incident_log").select("*").in_("status", ["auto_resolved", "approved_resolved"]).execute()
    return response.data


# Part B — generate a report for one incident using Groq
def generate_report(incident):
    prompt = f"""
Here is a resolved incident. Write a clear post-incident report.

Problem Type: {incident['problem_type']}
Problem Detail: {incident['problem_detail']}
Severity: {incident['severity']}
Root Cause: {incident['root_cause']}
Fix Plan: {incident['fix_plan']}
Risk Level: {incident['risk_level']}
Final Status: {incident['status']}

Respond in valid JSON with these exact keys:
- summary (2-3 sentences, max 300 characters, what happened)
- root_cause_recap (1-2 sentences, max 200 characters, why it happened)
- fix_applied (1-2 sentences, max 200 characters, what fix was applied)
- outcome (1 sentence, max 150 characters, final result)
- additional_notes (1-2 sentences, max 200 characters, any extra insight or pattern worth noting — leave empty string if nothing important)

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
    validated_report = IncidentReport(**raw_data)

    return validated_report



# Part C(i) — save the report into the incident_reports table
def save_report_to_supabase(incident_id, report):
    supabase.table("incident_reports").insert({
        "incident_id": incident_id,
        "summary": report.summary,
        "root_cause_recap": report.root_cause_recap,
        "fix_applied": report.fix_applied,
        "outcome": report.outcome,
        "additional_notes": report.additional_notes
    }).execute()



# Part C(ii) — add the report into ChromaDB for future RAG retrieval
def save_report_to_chromadb(incident_id, report):
    combined_text = (
        f"Summary: {report.summary} "
        f"Root Cause: {report.root_cause_recap} "
        f"Fix Applied: {report.fix_applied} "
        f"Outcome: {report.outcome} "
        f"Notes: {report.additional_notes}"
    )

    collection.add(
        documents=[combined_text],
        ids=[f"report_{incident_id}"]
    )



# Part D — mark incident as reported so it's not processed again
def mark_as_reported(incident_id):
    supabase.table("incident_log").update({
        "status": "reported"
    }).eq("id", incident_id).execute()


# Part E — polling loop connecting Part(A + B + C + D)
async def start_report_agent():
    while True:
        reportable_incidents = get_reportable_incidents()

        if reportable_incidents:
            for incident in reportable_incidents:
                try:
                    print(f"Generating report for incident ID: {incident['id']}")

                    report = generate_report(incident)
                    save_report_to_supabase(incident['id'], report)
                    save_report_to_chromadb(incident['id'], report)
                    mark_as_reported(incident['id'])

                    print(f"Report completed for incident {incident['id']}")

                except Exception as e:
                    print(f"ERROR generating report for incident {incident['id']}: {e}")
        else:
            print("No reportable incidents. Waiting...")

        await asyncio.sleep(10)