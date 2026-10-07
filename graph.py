import asyncio
import random
import uuid
import sqlite3
from langgraph.graph import StateGraph, START, END
from langgraph.checkpoint.sqlite import SqliteSaver
from agents.state import IncidentState
from agents.monitoring_agent import monitoring_node
from agents.detective_agent import detective_node
from agents.planning_agent import planning_node
from agents.human_approval_agent import auto_apply_node, human_approval_node
from agents.report_agent import report_node
from supabase import create_client
import os
from dotenv import load_dotenv

# Load secrets (Supabase, Groq, Slack) from the .env file
load_dotenv()

# Database client (this file does not use it directly, but it is set up like the other files)
supabase_url = os.getenv("SUPABASE_URL")
supabase_key = os.getenv("SUPABASE_KEY")
supabase = create_client(supabase_url, supabase_key)

# ---------------------------------------------------------------
# Graph definition
# The graph connects all agents. IncidentState is the shared data
# that moves from one node to the next.
# ---------------------------------------------------------------
graph_builder = StateGraph(IncidentState)

# Each node is one agent (or one step) of the pipeline
graph_builder.add_node("monitoring", monitoring_node)
graph_builder.add_node("detective", detective_node)
graph_builder.add_node("planning", planning_node)
graph_builder.add_node("auto_apply", auto_apply_node)
graph_builder.add_node("human_approval", human_approval_node)
graph_builder.add_node("report", report_node)

# Fixed path: start -> monitoring -> detective
graph_builder.add_edge(START, "monitoring")
graph_builder.add_edge("monitoring", "detective")

# If the Detective failed there is nothing to plan, so the run ends here
def route_after_detective(state: IncidentState) -> str:
    if state.get("status") == "detective_failed":
        return "end"
    else:
        return "planning"


graph_builder.add_conditional_edges(
    "detective", route_after_detective,
    {"planning": "planning", "end": END}
)


# Low-risk fixes are applied automatically.
# Medium and high risk need a human decision.
def route_by_risk(state: IncidentState) -> str:
    if state.get("risk_level") == "low":
        return "auto_apply"
    else:
        return "human_approval"


graph_builder.add_conditional_edges(
    "planning", route_by_risk,
    {"auto_apply": "auto_apply", "human_approval": "human_approval"}
)

graph_builder.add_edge("auto_apply", "report")


# Only an approved incident gets a report. A rejected one ends here.
def route_after_approval(state: IncidentState) -> str:
    if state.get("status") == "approved_resolved":
        return "report"
    else:
        return "end"


graph_builder.add_conditional_edges(
    "human_approval", route_after_approval,
    {"report": "report", "end": END}
)

graph_builder.add_edge("report", END)

# ──  SQLite checkpointer (restart-safe) ──
# Saves the graph state after every node, so a paused or crashed run can continue later
sqlite_conn = sqlite3.connect("checkpoints.sqlite", check_same_thread=False)
checkpointer = SqliteSaver(sqlite_conn)

# Build the runnable graph (imported by main.py)
graph = graph_builder.compile(checkpointer=checkpointer)


# ---------------------------------------------------------------
# Pipeline loop
# ---------------------------------------------------------------

# Runs forever in the background. Every 30 seconds there is a 30% chance
# of a simulated anomaly, which starts one full graph run.
async def start_pipeline():
    while True:
        is_anomaly = random.random() < 0.3

        if is_anomaly:
            # Each run gets its own thread_id, so its state is saved separately
            thread_id = str(uuid.uuid4())
            config = {"configurable": {"thread_id": thread_id}}
            try:
                # thread_id passes into initial state
                result = graph.invoke({"thread_id": thread_id}, config=config)
                print(f"Graph run (thread {thread_id}) finished/paused. State:", result)
            except Exception as e:
                print(f"ERROR running graph: {e}")
        else:
            print("Normal. No anomaly detected.")

        await asyncio.sleep(30)