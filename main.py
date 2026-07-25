from fastapi import FastAPI
from pydantic import BaseModel

app = FastAPI()

class Incident(BaseModel):
    id: int
    problem_type: str
    problem_detail: str
    severity: str

@app.get("/")
def home():
    return {"message": "ResolveX API is live and working"}