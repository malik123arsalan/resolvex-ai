from typing import TypedDict


class IncidentState(TypedDict):
    id: int
    thread_id: str   
    problem_type: str
    problem_detail: str
    severity: str
    root_cause: str
    fix_plan: str
    risk_level: str
    status: str