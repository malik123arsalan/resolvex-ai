from fastapi import FastAPI
from pydantic import BaseModel
import os
from dotenv import load_dotenv
from supabase import create_client
from graph import start_pipeline, graph
from langgraph.types import Command
import asyncio

app = FastAPI()

load_dotenv()

supabase_url = os.getenv("SUPABASE_URL")
supabase_key = os.getenv("SUPABASE_KEY")
supabase = create_client(supabase_url, supabase_key)


class Incident(BaseModel):
    id: int
    problem_type: str
    problem_detail: str
    severity: str


@app.on_event("startup")
async def startup_event():
    resume_incomplete_incidents()
    asyncio.create_task(start_pipeline())


def resume_incomplete_incidents():
    TERMINAL_STATUSES = ["reported", "rejected", "detective_failed", "planning_failed"]
    response = supabase.table("incident_log").select("*").execute()

    for incident in response.data:
        if incident["status"] not in TERMINAL_STATUSES and incident.get("thread_id"):
            print(f"Resuming incomplete incident {incident['id']} (was stuck at '{incident['status']}')")
            config = {"configurable": {"thread_id": incident["thread_id"]}}
            try:
                # None dene se graph apne last saved checkpoint se aage chalega
                graph.invoke(None, config=config)
            except Exception as e:
                print(f"ERROR resuming incident {incident['id']}: {e}")


@app.get("/")
def home():
    return {"message": "ResolveX API is live and working"}


@app.post("/incidents")
def create_incident(incident: Incident):
    response = supabase.table("incident_log").insert({
        "id": incident.id,
        "problem_type": incident.problem_type,
        "problem_detail": incident.problem_detail,
        "severity": incident.severity
    }).execute()
    return {"message": "Incident added successfully", "data": response.data}


@app.get("/incidents")
def get_all_incidents():
    response = supabase.table("incident_log").select("*").execute()
    return response.data


@app.get("/incidents/{incident_id}")
def get_incident_by_id(incident_id: int):
    response = supabase.table("incident_log").select("*").eq("id", incident_id).execute()

    if len(response.data) == 0:
        return {"error": "Incident not found"}

    return response.data


def get_thread_id(incident_id: int):
    response = supabase.table("incident_log").select("thread_id").eq("id", incident_id).execute()
    if not response.data or not response.data[0].get("thread_id"):
        return None
    return response.data[0]["thread_id"]


@app.post("/incidents/{incident_id}/approve")
def approve(incident_id: int):
    thread_id = get_thread_id(incident_id)
    if not thread_id:
        return {"error": "No pending approval found for this incident"}

    config = {"configurable": {"thread_id": thread_id}}
    try:
        result = graph.invoke(Command(resume="approve"), config=config)
        return {"message": "Incident approved", "state": result}
    except Exception as e:
        return {"error": f"Failed to resume graph: {e}"}


@app.post("/incidents/{incident_id}/reject")
def reject(incident_id: int):
    thread_id = get_thread_id(incident_id)
    if not thread_id:
        return {"error": "No pending approval found for this incident"}

    config = {"configurable": {"thread_id": thread_id}}
    try:
        result = graph.invoke(Command(resume="reject"), config=config)
        return {"message": "Incident rejected", "state": result}
    except Exception as e:
        return {"error": f"Failed to resume graph: {e}"}