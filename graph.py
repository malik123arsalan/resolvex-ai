import asyncio
import random
import uuid
from langgraph.graph import StateGraph, START, END
from langgraph.checkpoint.memory import InMemorySaver
from agents.state import IncidentState
from agents.monitoring_agent import monitoring_node
from agents.detective_agent import detective_node
from agents.planning_agent import planning_node
from agents.human_approval_agent import auto_apply_node, human_approval_node
from agents.report_agent import report_node

graph_builder = StateGraph(IncidentState)

graph_builder.add_node("monitoring", monitoring_node)
graph_builder.add_node("detective", detective_node)
graph_builder.add_node("planning", planning_node)
graph_builder.add_node("auto_apply", auto_apply_node)
graph_builder.add_node("human_approval", human_approval_node)
graph_builder.add_node("report", report_node)

graph_builder.add_edge(START, "monitoring")
graph_builder.add_edge("monitoring", "detective")
graph_builder.add_edge("detective", "planning")


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

checkpointer = InMemorySaver()
graph = graph_builder.compile(checkpointer=checkpointer)


async def start_pipeline():
    while True:
        is_anomaly = random.random() < 0.3

        if is_anomaly:
            thread_id = str(uuid.uuid4())
            config = {"configurable": {"thread_id": thread_id}}
            try:
                result = graph.invoke({}, config=config)
                print(f"Graph run (thread {thread_id}) finished/paused. State:", result)
            except Exception as e:
                print(f"ERROR running graph: {e}")
        else:
            print("Normal. No anomaly detected.")

        await asyncio.sleep(5)