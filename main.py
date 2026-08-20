from fastapi import FastAPI
from pydantic import BaseModel
import os
from dotenv import load_dotenv
from supabase import create_client
from agents.monitoring_agent import start_monitoring
from agents.detective_agent import start_detective_agent
from agents.planning_agent import start_planning_agent
from agents.human_approval_agent import start_human_approval_agent
from agents.human_approval_agent import start_human_approval_agent, approve_incident, reject_incident
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
    asyncio.create_task(start_monitoring())
    asyncio.create_task(start_detective_agent())
    asyncio.create_task(start_planning_agent())
    asyncio.create_task(start_human_approval_agent())

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

@app.post("/incidents/{incident_id}/approve")
def approve_incident_endpoint(incident_id: int):
    incident = approve_incident(incident_id)

    if incident is None:
        return {"error": "Incident not found"}

    return {"message": f"Incident {incident_id} approved and fix applied", "status": "approved_resolved"}


@app.post("/incidents/{incident_id}/reject")
def reject_incident_endpoint(incident_id: int):
    reject_incident(incident_id)
    return {"message": f"Incident {incident_id} rejected", "status": "rejected"}