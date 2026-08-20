import os
from dotenv import load_dotenv
from supabase import create_client
import requests
import asyncio

load_dotenv()

supabase_url = os.getenv("SUPABASE_URL")
supabase_key = os.getenv("SUPABASE_KEY")
supabase = create_client(supabase_url, supabase_key)

slack_webhook_url = os.getenv("SLACK_WEBHOOK_URL")


def get_planned_incidents():
    response = supabase.table("incident_log").select("*").eq("status", "planned").execute()
    return response.data


def decide_action(risk_level):
    if risk_level == "low":
        return "auto_apply"
    else:  # for both medium and high
        return "needs_approval"


def auto_apply_fix(incident_id, fix_plan):
    print(f"AUTO-APPLYING fix for incident {incident_id}: {fix_plan}")
    print("Fix applied successfully (simulated).")

    supabase.table("incident_log").update({
        "status": "auto_resolved"
    }).eq("id", incident_id).execute()


def send_slack_alert(incident_id, fix_plan, risk_level):
    message = {
        "text": f"⚠️ *Approval Needed* — Incident #{incident_id}\n"
                f"*Risk Level:* {risk_level}\n"
                f"*Suggested Fix:* {fix_plan}\n"
                f"Reply here to approve/reject (manual for now)."
    }

    response = requests.post(slack_webhook_url, json=message)

    if response.status_code == 200:
        print(f"Slack alert sent for incident {incident_id}")
    else:
        print(f"Failed to send Slack alert: {response.status_code} - {response.text}")

    supabase.table("incident_log").update({
        "status": "pending_approval"
    }).eq("id", incident_id).execute()


def approve_incident(incident_id):
    response = supabase.table("incident_log").select("*").eq("id", incident_id).execute()

    if not response.data:
        return None

    incident = response.data[0]

    print(f"APPROVED: Applying fix for incident {incident_id}: {incident['fix_plan']}")
    print("Fix applied successfully (human-approved).")

    supabase.table("incident_log").update({
        "status": "approved_resolved"
    }).eq("id", incident_id).execute()

    return incident


def reject_incident(incident_id):
    supabase.table("incident_log").update({
        "status": "rejected"
    }).eq("id", incident_id).execute()

    print(f"REJECTED: Incident {incident_id} fix was not applied.")


async def start_human_approval_agent():
    while True:
        planned_incidents = get_planned_incidents()

        if planned_incidents:
            for incident in planned_incidents:
                try:
                    print(f"Reviewing incident ID: {incident['id']}")

                    action = decide_action(incident['risk_level'])

                    if action == "auto_apply":
                        auto_apply_fix(incident['id'], incident['fix_plan'])
                    else:
                        send_slack_alert(incident['id'], incident['fix_plan'], incident['risk_level'])

                except Exception as e:
                    print(f"ERROR reviewing incident {incident['id']}: {e}")
        else:
            print("No planned incidents. Waiting...")

        await asyncio.sleep(7)