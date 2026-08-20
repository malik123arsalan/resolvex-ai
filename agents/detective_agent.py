import os
import chromadb
from dotenv import load_dotenv
from groq import Groq
from supabase import create_client
import json
from pydantic import BaseModel
import asyncio

load_dotenv()

# Setup Supabase connection
supabase_url = os.getenv("SUPABASE_URL")
supabase_key = os.getenv("SUPABASE_KEY")
supabase = create_client(supabase_url, supabase_key)

# Setup Groq connection
groq_client = Groq(api_key=os.getenv("GROQ_API_KEY"))

# Setup ChromaDB with persistent storage (data survives restarts)
chroma_client = chromadb.PersistentClient(path="./chroma_data")
collection = chroma_client.get_or_create_collection(name="incidents")

def get_new_incidents():
    response = supabase.table("incident_log").select("*").eq("status", "detected").execute()
    return response.data

def find_similar_incident(problem_detail):
    # Check if ChromaDB collection is empty
    if collection.count() == 0:
        return None

    results = collection.query(
        query_texts=[problem_detail],
        n_results=1
    )

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
    validated_result = RootCauseAnalysis(**raw_data)

    return validated_result


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


async def start_detective_agent():
    while True:
        new_incidents = get_new_incidents()

        if new_incidents:
            for incident in new_incidents:
                try:
                    print(f"Processing incident ID: {incident['id']}")

                    similar = find_similar_incident(incident['problem_detail'])
                    result = analyze_incident(incident['problem_detail'], similar)
                    update_incident(incident['id'], result.root_cause)
                    add_to_chromadb(incident['id'], incident['problem_detail'], result.root_cause)

                    print(f"Incident {incident['id']} analyzed. Root cause: {result.root_cause}")
                except Exception as e:
                    print(f"ERROR processing incident {incident['id']}: {e}")
                    # Ek incident fail hua to bhi loop agle incident/cycle pe chalta rahega
        else:
            print("No new incidents. Waiting...")

        await asyncio.sleep(7)