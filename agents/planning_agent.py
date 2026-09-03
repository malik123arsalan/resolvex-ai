import os
import json
import random
from dotenv import load_dotenv
from supabase import create_client
from pydantic import BaseModel
from typing import Literal
from groq import Groq
from agents.state import IncidentState

load_dotenv()

supabase_url = os.getenv("SUPABASE_URL")
supabase_key = os.getenv("SUPABASE_KEY")
supabase = create_client(supabase_url, supabase_key)

groq_client = Groq(api_key=os.getenv("GROQ_API_KEY"))


# ── Tool 1: simulated check for rollback availability ──
def check_rollback_availability(service_name: str = "general") -> str:
    has_rollback = random.random() < 0.6
    if has_rollback:
        return "A stable previous version is available for rollback if needed."
    else:
        return "No recent stable version found — rollback is not readily available."


# ── Tool 2: simulated downtime estimate ──
def estimate_downtime(fix_type: str) -> str:
    downtime_estimates = {
        "restart": "Estimated downtime: under 30 seconds.",
        "config_change": "Estimated downtime: none, hot-reloadable.",
        "code_deployment": "Estimated downtime: 2-5 minutes during rollout.",
        "scaling": "Estimated downtime: none, scales without interruption."
    }
    return downtime_estimates.get(fix_type, "Estimated downtime: unknown, assume moderate risk.")


# ── Tool 3: search ChromaDB for similar past fixes ──
def check_similar_past_fixes(query: str) -> str:
    from agents.detective_agent import collection

    if collection.count() == 0:
        return "No past fix history found."

    results = collection.query(query_texts=[query], n_results=1)
    distance = results['distances'][0][0]

    if distance <= 1.0:
        return f"Found a similar past case: {results['documents'][0][0]}"
    else:
        return "No similar past fix found."

class FixPlan(BaseModel):
    fix_description: str
    risk_level: Literal["low", "medium", "high"]
    reasoning: str

# ── Tool definitions (JSON schema) ──
AVAILABLE_TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "check_rollback_availability",
            "description": "Check if a stable previous version exists that the system could roll back to if this fix fails.",
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
            "name": "estimate_downtime",
            "description": "Estimate how much downtime a proposed fix would cause, based on the type of fix.",
            "parameters": {
                "type": "object",
                "properties": {
                    "fix_type": {
                        "type": "string",
                        "description": "The category of fix being considered: restart, config_change, code_deployment, or scaling."
                    }
                },
                "required": ["fix_type"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "check_similar_past_fixes",
            "description": "Search past resolved incidents to see if a similar fix was applied before and how it went.",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "A description of the root cause to search for similar past fixes."
                    }
                },
                "required": ["query"]
            }
        }
    }
]

TOOL_FUNCTIONS = {
    "check_rollback_availability": check_rollback_availability,
    "estimate_downtime": estimate_downtime,
    "check_similar_past_fixes": check_similar_past_fixes
}



def update_incident_with_plan(incident_id, fix_plan_result):
    combined_fix_plan = f"Fix: {fix_plan_result.fix_description} | Reasoning: {fix_plan_result.reasoning}"
    supabase.table("incident_log").update({
        "status": "planned",
        "fix_plan": combined_fix_plan,
        "risk_level": fix_plan_result.risk_level
    }).eq("id", incident_id).execute()


def planning_node(state: IncidentState) -> dict:
    try:
        print(f"Planning fix for incident ID: {state['id']}")

        messages = [
            {"role": "system", "content": "You are an expert DevOps engineer planning a fix. Use the available tools to gather evidence before deciding the fix and its risk level. Use as many tools as needed, in any order."},
            {"role": "user", "content": f"Plan a fix for this incident.\n\nRoot Cause: {state['root_cause']}\nProblem Type: {state['problem_type']}\nSeverity: {state['severity']}"}
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

            if message.tool_calls:
                messages.append(message)

                for tool_call in message.tool_calls:
                    tool_name = tool_call.function.name
                    tool_args = json.loads(tool_call.function.arguments)
                    print(f"LLM is calling tool: {tool_name} with args: {tool_args}")

                    tool_function = TOOL_FUNCTIONS[tool_name]
                    tool_result = tool_function(**tool_args)

                    messages.append({
                        "role": "tool",
                        "tool_call_id": tool_call.id,
                        "content": tool_result
                    })
            else:
                break
        else:
            return {"status": "planning_failed"}

        messages.append({
            "role": "user",
            "content": "Based on your investigation, give your final answer in valid JSON with keys: fix_description, risk_level, reasoning. risk_level must be exactly one of: low, medium, high."
        })

        final_response = groq_client.chat.completions.create(
            model="openai/gpt-oss-120b",
            messages=messages,
            response_format={"type": "json_object"}
        )

        raw_data = json.loads(final_response.choices[0].message.content)
        fix_plan_result = FixPlan(**raw_data)

        combined_fix_plan = f"Fix: {fix_plan_result.fix_description} | Reasoning: {fix_plan_result.reasoning}"
        update_incident_with_plan(state['id'], fix_plan_result)

        print(f"Incident {state['id']} planned. Risk level: {fix_plan_result.risk_level}")

        return {
            "fix_plan": combined_fix_plan,
            "risk_level": fix_plan_result.risk_level,
            "status": "planned"
        }

    except Exception as e:
     print(f"ERROR planning fix for incident {state['id']}: {e}")
     supabase.table("incident_log").update({"status": "planning_failed"}).eq("id", state['id']).execute()
     return {"status": "planning_failed"}