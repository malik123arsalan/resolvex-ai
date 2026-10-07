import os
import json
from dotenv import load_dotenv
from groq import Groq
from supabase import create_client
from pydantic import BaseModel, Field
from agents.state import IncidentState
from agents.detective_agent import collection  # reuse the same ChromaDB collection

# Load secrets (Supabase, Groq) from the .env file
load_dotenv()

# Database client used to save the report and update the incident status
supabase_url = os.getenv("SUPABASE_URL")
supabase_key = os.getenv("SUPABASE_KEY")
supabase = create_client(supabase_url, supabase_key)

# LLM client used to write the report
groq_client = Groq(api_key=os.getenv("GROQ_API_KEY"))


# ---------------------------------------------------------------
# Output validation
# The length limits keep reports short for the dashboard and keep
# the text stored in the vector DB focused.
# ---------------------------------------------------------------
class IncidentReport(BaseModel):
    summary: str = Field(max_length=300)
    root_cause_recap: str = Field(max_length=200)
    fix_applied: str = Field(max_length=200)
    outcome: str = Field(max_length=150)
    additional_notes: str = Field(max_length=200, default="")


# ---------------------------------------------------------------
# Report generation
# ---------------------------------------------------------------

# Ask the LLM to write a short report from everything the earlier agents produced.
# This is a single LLM call with no tools and no loop.
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

    # JSON mode forces valid JSON, but it does not enforce our length limits
    response = groq_client.chat.completions.create(
        model="openai/gpt-oss-120b",
        messages=[
            {"role": "system", "content": "You are an expert DevOps engineer writing concise post-incident reports. Always respond in valid JSON only, respecting character limits strictly."},
            {"role": "user", "content": prompt}
        ],
        response_format={"type": "json_object"}
    )

    # Convert the JSON text to a dict, then validate it (this is where length limits are checked)
    raw_data = json.loads(response.choices[0].message.content)
    return IncidentReport(**raw_data)


# ---------------------------------------------------------------
# Helper functions
# ---------------------------------------------------------------

# Save the report in its own table, which the dashboard reads
def save_report_to_supabase(incident_id, report):
    supabase.table("incident_reports").insert({
        "incident_id": incident_id,
        "summary": report.summary,
        "root_cause_recap": report.root_cause_recap,
        "fix_applied": report.fix_applied,
        "outcome": report.outcome,
        "additional_notes": report.additional_notes
    }).execute()


# Add the report to the knowledge base, so future incidents can learn from it.
# This is the "self-improving" part of the system.
def save_report_to_chromadb(incident_id, report):
    # Join all fields into one text, because one embedding is created per document
    combined_text = (
        f"Summary: {report.summary} "
        f"Root Cause: {report.root_cause_recap} "
        f"Fix Applied: {report.fix_applied} "
        f"Outcome: {report.outcome} "
        f"Notes: {report.additional_notes}"
    )
    # The "report_" prefix keeps this ID different from the Detective's document for the same incident
    collection.add(documents=[combined_text], ids=[f"report_{incident_id}"])


# Final status of the incident lifecycle
def mark_as_reported(incident_id):
    supabase.table("incident_log").update({"status": "reported"}).eq("id", incident_id).execute()


# ---------------------------------------------------------------
# LangGraph node
# Last step of the graph: write the report and store it in both databases.
# ---------------------------------------------------------------
def report_node(state: IncidentState) -> dict:
    try:
        print(f"Generating report for incident ID: {state['id']}")

        # The steps run in order. If one fails, the later ones are skipped.
        report = generate_report(state)
        save_report_to_supabase(state['id'], report)
        save_report_to_chromadb(state['id'], report)
        mark_as_reported(state['id'])

        print(f"Report completed for incident {state['id']}")
        return {"status": "reported"}
    except Exception as e:
        # The failure is reported in the state, so the graph knows what happened
        print(f"ERROR generating report for incident {state['id']}: {e}")
        return {"status": "report_failed"}