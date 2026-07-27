from fastapi import FastAPI
from pydantic import BaseModel

app = FastAPI()

class Incident(BaseModel):
    id: int
    problem_type: str
    problem_detail: str
    severity: str

incidents = []

@app.get("/")
def home():
    return {"message": "ResolveX API is live and working"}

@app.post("/incidents")
def create_incident(incident: Incident):
    incidents.append(incident)
    return {"message": "Incident added successfully", "data": incident}

@app.get("/incidents")
def get_all_incidents():
    return incidents

@app.get("/incidents/{incident_id}")
def get_incident_by_id(incident_id: int):
    for incident in incidents:
        if incident.id == incident_id:
            return incident
    return {"error": "Incident not found"}