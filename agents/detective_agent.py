import os
import chromadb
import json
from dotenv import load_dotenv
from groq import Groq
from supabase import create_client
from pydantic import BaseModel
from agents.state import IncidentState

load_dotenv()

supabase_url = os.getenv("SUPABASE_URL")
supabase_key = os.getenv("SUPABASE_KEY")
supabase = create_client(supabase_url, supabase_key)

groq_client = Groq(api_key=os.getenv("GROQ_API_KEY"))

chroma_client = chromadb.PersistentClient(path="./chroma_data")
collection = chroma_client.get_or_create_collection(name="incidents")


def find_similar_incident(problem_detail):
    if collection.count() == 0:
        return None

    results = collection.query(query_texts=[problem_detail], n_results=1)
    distance = results['distances'][0][0]
    DISTANCE_THRESHOLD = 1.0

    if distance <= DISTANCE_THRESHOLD:
        return results['documents'][0][0]
    else:
        return None


class RootCauseAnalysis(BaseModel):
    root_cause: str
    confidence: float
    explanation: str


def analyze_incident(problem_detail, similar_incident):
    if similar_incident:
        prompt = f"""
Here is a similar past incident: {similar_incident}

New incident: {problem_detail}

Based on the past incident, what is the likely root cause of the new incident?
"""
    else:
        prompt = f"""
New incident: {problem_detail}

No similar past incident was found. Based on your general knowledge, what is the likely root cause?
"""

    response = groq_client.chat.completions.create(
        model="openai/gpt-oss-120b",
        messages=[
            {"role": "system", "content": "You are an expert DevOps engineer. Always respond in valid JSON format with keys: root_cause, confidence, explanation."},
            {"role": "user", "content": prompt}
        ],
        response_format={"type": "json_object"}
    )

    raw_data = json.loads(response.choices[0].message.content)
    return RootCauseAnalysis(**raw_data)


def update_incident(incident_id, root_cause):
    supabase.table("incident_log").update({
        "status": "analyzed",
        "root_cause": root_cause
    }).eq("id", incident_id).execute()


def add_to_chromadb(incident_id, problem_detail, root_cause):
    collection.add(
        documents=[f"{problem_detail} - Root cause: {root_cause}"],
        ids=[str(incident_id)]
    )


# LangGraph node — replaces the old start_detective_agent() polling loop body
def detective_node(state: IncidentState) -> dict:
    try:
        print(f"Processing incident ID: {state['id']}")

        similar = find_similar_incident(state['problem_detail'])
        result = analyze_incident(state['problem_detail'], similar)
        update_incident(state['id'], result.root_cause)
        add_to_chromadb(state['id'], state['problem_detail'], result.root_cause)

        print(f"Incident {state['id']} analyzed. Root cause: {result.root_cause}")

        return {
            "root_cause": result.root_cause,
            "status": "analyzed"
        }
    except Exception as e:
        print(f"ERROR processing incident {state['id']}: {e}")
        return {"status": "detective_failed"}