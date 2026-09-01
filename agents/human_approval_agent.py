import os
from dotenv import load_dotenv
from supabase import create_client
import requests
from langgraph.types import interrupt
from agents.state import IncidentState

load_dotenv()

supabase_url = os.getenv("SUPABASE_URL")
supabase_key = os.getenv("SUPABASE_KEY")
supabase = create_client(supabase_url, supabase_key)

slack_webhook_url = os.getenv("SLACK_WEBHOOK_URL")


def auto_apply_fix(incident_id, fix_plan):
    print(f"AUTO-APPLYING fix for incident {incident_id}: {fix_plan}")
    supabase.table("incident_log").update({"status": "auto_resolved"}).eq("id", incident_id).execute()


def send_slack_alert(incident_id, fix_plan, risk_level):
    message = {
        "text": f"⚠️ *Approval Needed* — Incident #{incident_id}\n"
                f"*Risk Level:* {risk_level}\n"
                f"*Suggested Fix:* {fix_plan}"
    }
    response = requests.post(slack_webhook_url, json=message)
    if response.status_code == 200:
        print(f"Slack alert sent for incident {incident_id}")
    else:
        print(f"Failed to send Slack alert: {response.status_code} - {response.text}")

    supabase.table("incident_log").update({"status": "pending_approval"}).eq("id", incident_id).execute()


def approve_incident(incident_id):
    supabase.table("incident_log").update({"status": "approved_resolved"}).eq("id", incident_id).execute()
    print(f"APPROVED: Incident {incident_id} resolved.")


def reject_incident(incident_id):
    supabase.table("incident_log").update({"status": "rejected"}).eq("id", incident_id).execute()
    print(f"REJECTED: Incident {incident_id} fix was not applied.")


# LangGraph node — auto-apply path (low risk)
def auto_apply_node(state: IncidentState) -> dict:
    try:
        auto_apply_fix(state['id'], state['fix_plan'])
        return {"status": "auto_resolved"}
    except Exception as e:
        print(f"ERROR auto-applying fix for incident {state['id']}: {e}")
        return {"status": "auto_apply_failed"}


# LangGraph node — human approval path (medium/high risk)
def human_approval_node(state: IncidentState) -> dict:
    try:
        send_slack_alert(state['id'], state['fix_plan'], state['risk_level'])
    except Exception as e:
        print(f"ERROR sending Slack alert for incident {state['id']}: {e}")
        return {"status": "slack_failed"}

    # Graph pauses here until resumed with Command(resume="approve"/"reject")
    decision = interrupt({
        "incident_id": state['id'],
        "fix_plan": state['fix_plan'],
        "risk_level": state['risk_level']
    })

    try:
        if decision == "approve":
            approve_incident(state['id'])
            return {"status": "approved_resolved"}
        else:
            reject_incident(state['id'])
            return {"status": "rejected"}
    except Exception as e:
        print(f"ERROR finalizing decision for incident {state['id']}: {e}")
        return {"status": "approval_failed"}