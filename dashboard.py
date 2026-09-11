import streamlit as st
import os
import requests
from dotenv import load_dotenv
from supabase import create_client
import pandas as pd

load_dotenv()

# ---- Supabase connection (same as main.py) ----
supabase_url = os.getenv("SUPABASE_URL")
supabase_key = os.getenv("SUPABASE_KEY")
supabase = create_client(supabase_url, supabase_key)

# ---- Page config ----
st.set_page_config(
    page_title="ResolveX AI Dashboard",
    page_icon="🤖",
    layout="wide"
)

# ---- Custom CSS: cards, fonts, spacing ----
st.markdown("""
<style>
    .block-container {
        padding-top: 2rem;
    }
    h2, h3 {
        margin-top: 1.5rem !important;
    }
    #MainMenu {visibility: hidden;}
    footer {visibility: hidden;}
</style>
""", unsafe_allow_html=True)


# ---- Color maps (single source of truth, reused everywhere) ----
STATUS_COLORS = {
    "detected": "#6B7280",
    "analyzed": "#3B82F6",
    "pending_approval": "#F59E0B",
    "reported": "#22C55E",
    "rejected": "#EF4444",
}

SEVERITY_COLORS = {
    "low": "#3B82F6",
    "medium": "#F59E0B",
    "high": "#EF4444",
}

RISK_COLORS = {
    "low": "#3B82F6",
    "medium": "#F59E0B",
    "high": "#EF4444",
}

COLUMN_LABELS = {
    "id": "ID",
    "created_at": "Created At",
    "problem_type": "Problem Type",
    "problem_detail": "Problem Detail",
    "severity": "Severity",
    "status": "Status",
    "root_cause": "Root Cause",
    "risk_level": "Risk Level",
    "fix_plan": "Fix Plan",
    "thread_id": "Thread ID",
}

FASTAPI_BASE_URL = "http://localhost:8000"


@st.cache_data(ttl=10)
def fetch_incidents():
    response = supabase.table("incident_log").select("*").execute()
    return response.data


@st.cache_data(ttl=10)
def fetch_reports():
    response = supabase.table("incident_reports").select("*").execute()
    return response.data


def render_metric_card(column, label, value, color):
    with column:
        st.markdown(f"""
        <div style="
            background-color: {color}1a;
            border: 1px solid {color};
            border-radius: 10px;
            padding: 16px 14px;
            text-align: center;
        ">
            <div style="font-size: 12px; color: #aaaaaa; margin-bottom: 6px;">{label}</div>
            <div style="font-size: 26px; font-weight: 700; color: {color};">{value}</div>
        </div>
        """, unsafe_allow_html=True)


def style_status(value):
    color = STATUS_COLORS.get(value, "#374151")
    return f"background-color: {color}33; color: {color}; font-weight: 600;"


def style_severity(value):
    color = SEVERITY_COLORS.get(value, "#374151")
    return f"background-color: {color}33; color: {color}; font-weight: 600;"


# ================= PAGE CONTENT =================

# ---- Title + Refresh button ----
col_title, col_refresh = st.columns([5, 1])
with col_title:
    st.title("🤖 ResolveX AI — Incident Dashboard")
    st.caption("Autonomous incident detection and resolution — live view")
with col_refresh:
    if st.button("🔄 Refresh"):
        fetch_incidents.clear()
        fetch_reports.clear()
        st.rerun()

incidents = fetch_incidents()

if not incidents:
    st.info("Abhi koi incident nahi hai.")
    st.stop()

df = pd.DataFrame(incidents)
df["created_at"] = pd.to_datetime(df["created_at"]).dt.strftime("%d %b, %H:%M")

# ---- Metrics row ----
col1, col2, col3, col4, col5 = st.columns(5)
render_metric_card(col1, "TOTAL", len(df), "#60A5FA")
render_metric_card(col2, "DETECTED", len(df[df["status"] == "detected"]), STATUS_COLORS["detected"])
render_metric_card(col3, "ANALYZED", len(df[df["status"] == "analyzed"]), STATUS_COLORS["analyzed"])
render_metric_card(col4, "PENDING APPROVAL", len(df[df["status"] == "pending_approval"]), STATUS_COLORS["pending_approval"])
render_metric_card(col5, "REPORTED", len(df[df["status"] == "reported"]), STATUS_COLORS["reported"])

st.markdown("---")

# ---- Incidents table ----
st.subheader("📋 All Incidents")

preferred_order = ["id", "created_at", "problem_type", "problem_detail",
                   "severity", "status", "root_cause", "risk_level", "fix_plan"]
existing_cols = [c for c in preferred_order if c in df.columns]
display_df = df[existing_cols].rename(columns=COLUMN_LABELS)

styled_df = display_df.style
if "Status" in display_df.columns:
    styled_df = styled_df.map(style_status, subset=["Status"])
if "Severity" in display_df.columns:
    styled_df = styled_df.map(style_severity, subset=["Severity"])

st.dataframe(styled_df, use_container_width=True, hide_index=True)

st.markdown("---")

# ---- Incident Detail View ----
st.subheader("🔍 Incident Detail View")

df["dropdown_label"] = df["id"].astype(str) + " — " + df["problem_type"].astype(str)
selected_label = st.selectbox("Select an incident to inspect:", df["dropdown_label"])

selected_id = selected_label.split(" — ")[0]
incident = df[df["id"].astype(str) == selected_id].iloc[0]

badge_col1, badge_col2, badge_col3 = st.columns(3)
with badge_col1:
    status_color = "green" if incident['status'] == 'reported' else "orange" if incident['status'] == 'pending_approval' else "red" if incident['status'] == 'rejected' else "blue"
    st.markdown(f"**Status:** :{status_color}[{incident['status'].upper()}]")
with badge_col2:
    st.markdown(f"**Severity:** {incident.get('severity', 'N/A').upper()}")
with badge_col3:
    risk = incident.get('risk_level') or "Not yet planned"
    st.markdown(f"**Risk Level:** {risk if risk == 'Not yet planned' else risk.upper()}")

st.markdown(f"**Problem:** {incident.get('problem_detail', 'N/A')}")
st.markdown(f"**Reported at:** {incident.get('created_at', 'N/A')}")

st.markdown("#### 🕵️ Root Cause")
st.info(incident.get("root_cause") or "Not yet analyzed.")

st.markdown("#### 🛠️ Fix Plan")
st.success(incident.get("fix_plan") or "Not yet planned.")

st.markdown("---")

# ---- Report Viewer ----
st.subheader("📄 Incident Reports")

reports = fetch_reports()

if not reports:
    st.info("Abhi koi report generate nahi hua.")
else:
    reports_df = pd.DataFrame(reports)
    reports_df["report_label"] = "Incident " + reports_df["incident_id"].astype(str)

    selected_report_label = st.selectbox(
        "Select a report to read:",
        reports_df["report_label"],
        key="report_selector"
    )

    selected_incident_id = selected_report_label.replace("Incident ", "")
    report_row = reports_df[reports_df["incident_id"].astype(str) == selected_incident_id].iloc[0]

    st.markdown(f"#### Report — Incident {selected_incident_id}")
    st.caption(f"Generated at: {report_row['created_at']}")

    st.markdown("**📝 Summary**")
    st.write(report_row["summary"] or "N/A")

    st.markdown("**🕵️ Root Cause Recap**")
    st.info(report_row["root_cause_recap"] or "N/A")

    st.markdown("**🛠️ Fix Applied**")
    st.success(report_row["fix_applied"] or "N/A")

    st.markdown("**✅ Outcome**")
    st.write(report_row["outcome"] or "N/A")

    notes = report_row["additional_notes"]
    if notes and notes.strip():
        st.markdown("**📌 Additional Notes**")
        st.write(notes)

st.markdown("---")

# ---- Approve / Reject Pending Incidents ----
st.subheader("✅ Pending Approvals")

pending_df = df[df["status"] == "pending_approval"]

if pending_df.empty:
    st.info("Abhi koi incident approval ke liye pending nahi hai.")
else:
    for _, row in pending_df.iterrows():
        with st.container(border=True):
            col_info, col_approve, col_reject = st.columns([4, 1, 1])

            with col_info:
                st.markdown(f"**Incident {row['id']}** — {row['problem_type']}")
                st.caption(row['problem_detail'] if row['problem_detail'] else "")
                if row.get('fix_plan'):
                    st.caption(f"Proposed fix: {row['fix_plan']}")

            with col_approve:
                if st.button("✅ Approve", key=f"approve_{row['id']}"):
                    with st.spinner("Approving..."):
                        try:
                            response = requests.post(
                                f"{FASTAPI_BASE_URL}/incidents/{row['id']}/approve",
                                timeout=45
                            )
                            data = response.json()

                            if response.status_code == 200 and "error" not in data:
                                st.success(f"Incident {row['id']} approved!")
                                fetch_incidents.clear()
                                st.rerun()
                            else:
                                error_msg = data.get("error", f"HTTP {response.status_code}")
                                st.error(f"Approve failed: {error_msg}")

                        except requests.exceptions.ConnectionError:
                            st.error("FastAPI server chal nahi raha. Terminal me `uvicorn main:app` chalao.")
                        except requests.exceptions.Timeout:
                            st.error("Server response me bahut time laga (timeout).")

            with col_reject:
                if st.button("❌ Reject", key=f"reject_{row['id']}"):
                    with st.spinner("Rejecting..."):
                        try:
                            response = requests.post(
                                f"{FASTAPI_BASE_URL}/incidents/{row['id']}/reject",
                                timeout=45
                            )
                            data = response.json()

                            if response.status_code == 200 and "error" not in data:
                                st.warning(f"Incident {row['id']} rejected.")
                                fetch_incidents.clear()
                                st.rerun()
                            else:
                                error_msg = data.get("error", f"HTTP {response.status_code}")
                                st.error(f"Reject failed: {error_msg}")

                        except requests.exceptions.ConnectionError:
                            st.error("FastAPI server chal nahi raha. Terminal me `uvicorn main:app` chalao.")
                        except requests.exceptions.Timeout:
                            st.error("Server response me bahut time laga (timeout).")