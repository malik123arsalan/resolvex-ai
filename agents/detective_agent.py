import os
import chromadb
import json
import random
from dotenv import load_dotenv
from groq import Groq
from supabase import create_client
from pydantic import BaseModel, field_validator
from agents.state import IncidentState

load_dotenv()

supabase_url = os.getenv("SUPABASE_URL")
supabase_key = os.getenv("SUPABASE_KEY")
supabase = create_client(supabase_url, supabase_key)

groq_client = Groq(api_key=os.getenv("GROQ_API_KEY"))

chroma_client = chromadb.PersistentClient(path="./chroma_data")
collection = chroma_client.get_or_create_collection(name="incidents")


# ── Tool 1: search ChromaDB for similar past incidents ──
def search_past_incidents(query: str) -> str:
    if collection.count() == 0:
        return "No past incidents found in the database."

    results = collection.query(query_texts=[query], n_results=1)
    distance = results['distances'][0][0]

    if distance <= 1.0:
        return f"Found similar past incident: {results['documents'][0][0]}"
    else:
        return "No sufficiently similar past incident found."


# ── Tool 2: simulated check for recent deployments ──
def check_recent_deployments(service_name: str = "general") -> str:
    had_deployment = random.random() < 0.4
    if had_deployment:
        minutes_ago = random.randint(5, 180)
        return f"A deployment was made {minutes_ago} minutes ago that could be related."
    else:
        return "No recent deployments found in the last 24 hours."


# ── Tool 3: simulated check for server logs ──
def check_server_logs(problem_type: str = "general") -> str:
    log_snippets = {
        "high_response_time": "Logs show repeated timeout warnings from the database connection pool.",
        "high_cpu_usage": "Logs show a background job consuming excessive CPU cycles.",
        "memory_leak": "Logs show gradually increasing heap usage with no corresponding garbage collection.",
        "disk_space_low": "Logs show large temp files not being cleaned up.",
        "database_connection_failure": "Logs show connection refused errors from the database host."
    }
    return log_snippets.get(problem_type, "No specific error patterns found in logs.")



class RootCauseAnalysis(BaseModel):
    root_cause: str
    confidence: float
    explanation: str

    @field_validator("confidence", mode="before")
    @classmethod
    def parse_confidence(cls, v):
        if isinstance(v, str):
            word_map = {"low": 0.3, "medium": 0.6, "high": 0.9}
            v_clean = v.strip().lower()
            if v_clean in word_map:
                return word_map[v_clean]
            try:
                return float(v)
            except ValueError:
                return 0.5
        return v




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


# ── Tool definitions (JSON schema) — tells the LLM what tools exist and how to call them ──
AVAILABLE_TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "search_past_incidents",
            "description": "Search the database of past resolved incidents to find a similar case and its root cause.",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "A description of the current incident to search for similar past cases."
                    }
                },
                "required": ["query"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "check_recent_deployments",
            "description": "Check if there was a recent code or infrastructure deployment that could explain the incident.",
            "parameters": {
                "type": "object",
                "properties": {
                    "service_name": {
                        "type": "string",
                        "description": "The name of the affected service, or 'general' if unknown."
                    }
                },
                "required": []
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "check_server_logs",
            "description": "Check server logs for error patterns related to a specific problem type.",
            "parameters": {
                "type": "object",
                "properties": {
                    "problem_type": {
                        "type": "string",
                        "description": "The type of problem, e.g. high_response_time, high_cpu_usage, memory_leak, disk_space_low, database_connection_failure."
                    }
                },
                "required": []
            }
        }
    }
]

# ── Maps tool name (string) to actual Python function — used to execute the tool the LLM picks ──
TOOL_FUNCTIONS = {
    "search_past_incidents": search_past_incidents,
    "check_recent_deployments": check_recent_deployments,
    "check_server_logs": check_server_logs
}


def detective_node(state: IncidentState) -> dict:
    try:
        print(f"Investigating incident ID: {state['id']}")

        # Step 1: Give the LLM the incident details and the list of available tools
        messages = [
            {"role": "system", "content": "You are an expert DevOps detective. Use the available tools to gather evidence before deciding the root cause. Use as many tools as needed, in any order."},
            {"role": "user", "content": f"Investigate this incident.\n\nProblem Type: {state['problem_type']}\nProblem Detail: {state['problem_detail']}\nSeverity: {state['severity']}"}
        ]

        max_iterations = 5

        for i in range(max_iterations):
            response = groq_client.chat.completions.create(
                model="openai/gpt-oss-120b",
                messages=messages,
                tools=AVAILABLE_TOOLS,
                tool_choice="auto"
            )

            message = response.choices[0].message

            # Step 2: Check if the LLM asked for a tool
            if message.tool_calls:
                messages.append(message)

                for tool_call in message.tool_calls:
                    tool_name = tool_call.function.name
                    tool_args = json.loads(tool_call.function.arguments)
                    print(f"LLM is calling tool: {tool_name} with args: {tool_args}")

                    # Step 3: Actually run the tool the LLM asked for
                    tool_function = TOOL_FUNCTIONS[tool_name]
                    tool_result = tool_function(**tool_args)

                    # Step 4: Send the tool's result back to the LLM
                    messages.append({
                        "role": "tool",
                        "tool_call_id": tool_call.id,
                        "content": tool_result
                    })
            else:
                # No tool call means the LLM is done investigating
                break
        else:
            supabase.table("incident_log").update({"status": "detective_failed"}).eq("id", state['id']).execute()
            return {"status": "detective_failed"}

        # Step 5: Ask the LLM for its final structured answer
        messages.append({
            "role": "user",
            "content": "Based on your investigation, give your final answer in valid JSON with keys: root_cause, confidence, explanation."
        })

        final_response = groq_client.chat.completions.create(
            model="openai/gpt-oss-120b",
            messages=messages,
            response_format={"type": "json_object"}
        )

        raw_data = json.loads(final_response.choices[0].message.content)
        result = RootCauseAnalysis(**raw_data)

        update_incident(state['id'], result.root_cause)
        add_to_chromadb(state['id'], state['problem_detail'], result.root_cause)

        print(f"Incident {state['id']} analyzed. Root cause: {result.root_cause}")

        return {
            "root_cause": result.root_cause,
            "status": "analyzed"
        }

    except Exception as e:
     print(f"ERROR processing incident {state['id']}: {e}")
     supabase.table("incident_log").update({"status": "detective_failed"}).eq("id", state['id']).execute()
     return {"status": "detective_failed"}