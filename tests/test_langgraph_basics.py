from typing import TypedDict
from langgraph.graph import StateGraph, START, END


# Step 1: State define  — what is inside the state
class CounterState(TypedDict):
    count: int


# Step 2: Node functions — Take every state and return updated part
def increment_node(state: CounterState) -> dict:
    new_count = state["count"] + 1
    print(f"Incrementing: {state['count']} -> {new_count}")
    return {"count": new_count}


# This is the NEW part: a decision function
def should_continue(state: CounterState) -> str:
    if state["count"] < 3:
        return "continue"
    else:
        return "stop"


# Step 3: Create Graph 
graph_builder = StateGraph(CounterState)

graph_builder.add_node("increment", increment_node)

graph_builder.add_edge(START, "increment")

# This is the NEW part: conditional edge
graph_builder.add_conditional_edges(
    "increment",
    should_continue,
    {
        "continue": "increment",
        "stop": END
    }
)

# Step 4: Compile it — Now this is a runnable graph
graph = graph_builder.compile()

# Step 5: Run it
result = graph.invoke({"count": 0})
print("Returned final state:", result)