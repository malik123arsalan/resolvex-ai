import os
import json
import random
from dotenv import load_dotenv
from supabase import create_client
from pydantic import BaseModel
from typing import Literal
from groq import Groq
from agents.state import IncidentState

# Load secrets (Supabase, Groq) from the .env file
load_dotenv()

# Database client used to save the fix plan
supabase_url = os.getenv("SUPABASE_URL")
supabase_key = os.getenv("SUPABASE_KEY")
supabase = create_client(supabase_url, supabase_key)

# LLM client used to plan the fix
groq_client = Groq(api_key=os.getenv("GROQ_API_KEY"))


# ---------------------------------------------------------------
# Tools
# The LLM decides which of these to call. We only run them.
# Tools must return plain text, because the LLM reads the result.
# ---------------------------------------------------------------

# ── Tool 1: simulated check for rollback availability ──
def check_rollback_availability(service_name: str = "general") -> str:
    # Simulated data: a stable version exists about 60% of the time
    has_rollback = random.random() < 0.6
    if has_rollback:
        return "A stable previous version is available for rollback if needed."
    else:
        return "No recent stable version found — rollback is not readily available."


# ── Tool 2: simulated downtime estimate ──
def estimate_downtime(fix_type: str) -> str:
    # Typical downtime for each kind of fix
    downtime_estimates = {
        "restart": "Estimated downtime: under 30 seconds.",
        "config_change": "Estimated downtime: none, hot-reloadable.",
        "code_deployment": "Estimated downtime: 2-5 minutes during rollout.",
        "scaling": "Estimated downtime: none, scales without interruption."
    }
    # Unknown fix types get a cautious default message
    return downtime_estimates.get(fix_type, "Estimated downtime: unknown, assume moderate risk.")


# ── Tool 3: search ChromaDB for similar past fixes ──
def check_similar_past_fixes(query: str) -> str:
    # Reuse the same ChromaDB collection that the Detective Agent created
    from agents.detective_agent import collection

    # Nothing to search yet
    if collection.count() == 0:
        return "No past fix history found."

    # Find the closest past incident (a smaller distance means more similar)
    results = collection.query(query_texts=[query], n_results=1)
    distance = results['distances'][0][0]

    # Only trust the match if it is close enough
    if distance <= 1.0:
        return f"Found a similar past case: {results['documents'][0][0]}"
    else:
        return "No similar past fix found."


# ---------------------------------------------------------------
# Output validation
# ---------------------------------------------------------------
class FixPlan(BaseModel):
    fix_description: str
    # Only these three exact values are accepted, because the approval step depends on them
    risk_level: Literal["low", "medium", "high"]
    reasoning: str


# ── Tool definitions (JSON schema) ──
# The LLM only sees these descriptions, so they must clearly explain when to use each tool.
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

# Maps tool name (string) to the real Python function.
# The LLM only returns a tool name as text, so we look up the function here.
TOOL_FUNCTIONS = {
    "check_rollback_availability": check_rollback_availability,
    "estimate_downtime": estimate_downtime,
    "check_similar_past_fixes": check_similar_past_fixes
}


# ---------------------------------------------------------------
# Helper functions
# ---------------------------------------------------------------

# Save the fix plan and risk level, and mark the incident as planned.
# Fix and reasoning are joined into one text, because the table has a single fix_plan column.
def update_incident_with_plan(incident_id, fix_plan_result):
    combined_fix_plan = f"Fix: {fix_plan_result.fix_description} | Reasoning: {fix_plan_result.reasoning}"
    supabase.table("incident_log").update({
        "status": "planned",
        "fix_plan": combined_fix_plan,
        "risk_level": fix_plan_result.risk_level
    }).eq("id", incident_id).execute()


# ---------------------------------------------------------------
# LangGraph node
# Third step of the graph: use the root cause to plan a fix and rate its risk.
# ---------------------------------------------------------------
def planning_node(state: IncidentState) -> dict:
    try:
        print(f"Planning fix for incident ID: {state['id']}")

        # Give the LLM the root cause found by the Detective Agent
        messages = [
            {"role": "system", "content": "You are an expert DevOps engineer planning a fix. Use the available tools to gather evidence before deciding the fix and its risk level. Use as many tools as needed, in any order."},
            {"role": "user", "content": f"Plan a fix for this incident.\n\nRoot Cause: {state['root_cause']}\nProblem Type: {state['problem_type']}\nSeverity: {state['severity']}"}
        ]

        # Safety limit, so the LLM cannot keep calling tools forever
        max_iterations = 5

        for i in range(max_iterations):
            response = groq_client.chat.completions.create(
                model="openai/gpt-oss-120b",
                messages=messages,
                tools=AVAILABLE_TOOLS,
                tool_choice="auto"
            )

            message = response.choices[0].message

            # Check if the LLM asked for a tool
            if message.tool_calls:
                # Keep the LLM's request in the history, so tool results can be matched to it
                messages.append(message)

                # The LLM may ask for several tools in one turn
                for tool_call in message.tool_calls:
                    tool_name = tool_call.function.name
                    tool_args = json.loads(tool_call.function.arguments)
                    print(f"LLM is calling tool: {tool_name} with args: {tool_args}")

                    # Run the tool the LLM asked for
                    tool_function = TOOL_FUNCTIONS[tool_name]
                    tool_result = tool_function(**tool_args)

                    # Send the tool's result back to the LLM
                    messages.append({
                        "role": "tool",
                        "tool_call_id": tool_call.id,
                        "content": tool_result
                    })
            else:
                # No tool call means the LLM is done gathering evidence
                break
        else:
            # The loop ended without a break: the LLM never finished within the limit
            return {"status": "planning_failed"}

        # Ask the LLM for its final structured answer
        messages.append({
            "role": "user",
            "content": "Based on your investigation, give your final answer in valid JSON with keys: fix_description, risk_level, reasoning. risk_level must be exactly one of: low, medium, high."
        })

        final_response = groq_client.chat.completions.create(
            model="openai/gpt-oss-120b",
            messages=messages,
            response_format={"type": "json_object"}
        )

        # Convert the JSON text to a dict, then validate it with Pydantic
        raw_data = json.loads(final_response.choices[0].message.content)
        fix_plan_result = FixPlan(**raw_data)

        # Save the plan in the database
        combined_fix_plan = f"Fix: {fix_plan_result.fix_description} | Reasoning: {fix_plan_result.reasoning}"
        update_incident_with_plan(state['id'], fix_plan_result)

        print(f"Incident {state['id']} planned. Risk level: {fix_plan_result.risk_level}")

        # Pass the plan and risk level to the next agent (Human Approval) through the shared state.
        # The risk level decides whether a human must approve the fix.
        return {
            "fix_plan": combined_fix_plan,
            "risk_level": fix_plan_result.risk_level,
            "status": "planned"
        }

    except Exception as e:
        # Any failure marks the incident as failed, so the rest of the system knows
        print(f"ERROR planning fix for incident {state['id']}: {e}")
        supabase.table("incident_log").update({"status": "planning_failed"}).eq("id", state['id']).execute()
        return {"status": "planning_failed"}