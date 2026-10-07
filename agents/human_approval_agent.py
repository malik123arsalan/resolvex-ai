import os
from dotenv import load_dotenv
from supabase import create_client
import requests
from langgraph.types import interrupt
from agents.state import IncidentState

# Load secrets (Supabase, Slack) from the .env file
load_dotenv()

# Database client used to update the incident status
supabase_url = os.getenv("SUPABASE_URL")
supabase_key = os.getenv("SUPABASE_KEY")
supabase = create_client(supabase_url, supabase_key)

# Secret Slack webhook URL. Anyone with this URL can post to our channel,
# so it must stay in environment variables and never in the code.
slack_webhook_url = os.getenv("SLACK_WEBHOOK_URL")


# ---------------------------------------------------------------
# Helper functions
# ---------------------------------------------------------------

# Low-risk path: apply the fix without asking a human.
# Note: this is a simulation. It only records the result in the database.
def auto_apply_fix(incident_id, fix_plan):
    print(f"AUTO-APPLYING fix for incident {incident_id}: {fix_plan}")
    supabase.table("incident_log").update({"status": "auto_resolved"}).eq("id", incident_id).execute()


# Notify the team on Slack and mark the incident as waiting for a decision
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
        # A failed alert is only logged, it does not stop the approval flow
        print(f"Failed to send Slack alert: {response.status_code} - {response.text}")

    # The dashboard reads this status to show the incident in the "Pending Approval" list
    supabase.table("incident_log").update({"status": "pending_approval"}).eq("id", incident_id).execute()


# Record that a human approved the fix
def approve_incident(incident_id):
    supabase.table("incident_log").update({"status": "approved_resolved"}).eq("id", incident_id).execute()
    print(f"APPROVED: Incident {incident_id} resolved.")


# Record that a human rejected the fix
def reject_incident(incident_id):
    supabase.table("incident_log").update({"status": "rejected"}).eq("id", incident_id).execute()
    print(f"REJECTED: Incident {incident_id} fix was not applied.")


# ---------------------------------------------------------------
# LangGraph nodes
# Fourth step of the graph. The graph chooses one of these two nodes
# based on the risk level from the Planning Agent.
# ---------------------------------------------------------------

# LangGraph node — auto-apply path (low risk)
def auto_apply_node(state: IncidentState) -> dict:
    try:
        auto_apply_fix(state['id'], state['fix_plan'])
        return {"status": "auto_resolved"}
    except Exception as e:
        # The failure is reported in the state so the graph knows what happened
        print(f"ERROR auto-applying fix for incident {state['id']}: {e}")
        return {"status": "auto_apply_failed"}


# LangGraph node — human approval path (medium/high risk)
def human_approval_node(state: IncidentState) -> dict:
    # Step 1: Tell the team that a decision is needed
    try:
        send_slack_alert(state['id'], state['fix_plan'], state['risk_level'])
    except Exception as e:
        print(f"ERROR sending Slack alert for incident {state['id']}: {e}")
        return {"status": "slack_failed"}

    # Step 2: Pause the graph and wait for a human decision.
    # The state is saved by the checkpointer, so the wait can be long and survive a restart.
    # This call is kept outside try/except on purpose, because interrupt() works by
    # raising a special exception that must not be caught.
    # Graph pauses here until resumed with Command(resume="approve"/"reject")
    decision = interrupt({
        "incident_id": state['id'],
        "fix_plan": state['fix_plan'],
        "risk_level": state['risk_level']
    })

    # Step 3: Apply the human decision.
    # Anything other than "approve" is treated as a rejection, which is the safe default.
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