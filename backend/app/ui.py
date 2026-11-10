"""
RollCall AI — Streamlit User Interface (Prompt 7)

Provides a 3-tab web dashboard:
- Tab 1: Upload (CSV or Photo, agent extraction, editable preview table for corrections, confirmation flow).
- Tab 2: Dashboard (Room-wise and Branch-wise summary tables, bar charts, Excel/PDF export downloads).
- Tab 3: Ask (Interactive chat with AttendanceAgent, logging tool execution).

Enforces the 4-state attendance model (PRESENT, ABSENT, PENDING, UNREVIEWED), strict pipeline ordering,
and anti-hallucination guardrails.
"""

from __future__ import annotations

import os
import sqlite3
import sys
import tempfile
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple, Union

import pandas as pd
import streamlit as st

# Ensure project root is available in sys.path
project_root = Path(__file__).resolve().parent.parent
if str(project_root) not in sys.path:
    sys.path.insert(0, str(project_root))

from app.agent import AttendanceAgent, AgentResponse, CONFIDENCE_CONFIRMATION_THRESHOLD
from app.db import (
    DEFAULT_DB_PATH,
    get_connection,
    init_db,
    get_all_sessions,
    get_all_rooms,
    get_all_students,
    get_session_attendance_details,
    insert_session,
    replace_session_attendance,
)
from tools.summary_tool import summary_tool, SummaryReport
from tools.export_tool import export_to_excel, export_to_pdf


# ==============================================================================
# Helper & Logic Functions (Tested by tests/test_ui.py)
# ==============================================================================

def get_or_create_agent(db_target: Optional[Union[str, Path]] = DEFAULT_DB_PATH) -> AttendanceAgent:
    """Return or initialize an AttendanceAgent instance with the active database target."""
    target_str = str(db_target) if db_target else None
    if "agent" not in st.session_state or st.session_state.get("agent_db_target") != target_str:
        st.session_state["agent"] = AttendanceAgent(db_target=target_str)
        st.session_state["agent_db_target"] = target_str
    return st.session_state["agent"]


def process_uploaded_file(
    agent: AttendanceAgent,
    uploaded_file: Any,
    session_id: Optional[str] = None,
    default_room: Optional[str] = None,
    default_branch: Optional[str] = None,
    master_usns: Optional[List[str]] = None,
    master_rooms: Optional[List[str]] = None,
) -> Tuple[AgentResponse, Path]:
    """
    Save an uploaded file to a temporary location and process it through the agent pipeline.
    Returns the AgentResponse and the temporary file path.
    """
    filename = uploaded_file.name
    suffix = Path(filename).suffix.lower()

    if suffix in (".png", ".jpg", ".jpeg", ".bmp", ".webp"):
        raw_bytes = uploaded_file.getbuffer() if hasattr(uploaded_file, "getbuffer") else uploaded_file.read()
        if not isinstance(raw_bytes, bytes) or not raw_bytes:
            return AttendanceAgent().process_request(
                user_input=f"Process attendance file: {filename}",
                file_path=None,
            ), Path(filename)

        with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
            tmp.write(raw_bytes)
            tmp_path = Path(tmp.name)

        # Photo processing: call the agent directly on the saved temp file.
        pass
    else:
        with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
            raw_bytes = uploaded_file.getbuffer() if hasattr(uploaded_file, "getbuffer") else uploaded_file.read()
            if isinstance(raw_bytes, bytes) and raw_bytes:
                tmp.write(raw_bytes)
                tmp_path = Path(tmp.name)
            else:
                tmp_path = Path(tmp.name)
                tmp_path.write_bytes(b"")

    query = f"Process attendance file: {filename}"
    response = agent.process_request(
        user_input=query,
        file_path=tmp_path,
        default_room=default_room,
        default_branch=default_branch,
        master_usns=master_usns,
        master_rooms=master_rooms,
    )
    return response, tmp_path


def revalidate_and_summarise(
    agent: AttendanceAgent,
    records: List[Dict[str, Any]],
    default_room: Optional[str] = None,
    default_branch: Optional[str] = None,
    master_usns: Optional[List[str]] = None,
    master_rooms: Optional[List[str]] = None,
) -> Tuple[AgentResponse, Path]:
    """
    Save edited records to a temporary CSV and run them through agent validation and summarisation.
    """
    df = pd.DataFrame(records)
    # Ensure standard column names
    col_map = {"room": "room_id", "dept": "branch", "department": "branch"}
    df = df.rename(columns=col_map)

    with tempfile.NamedTemporaryFile(delete=False, suffix=".csv", mode="w", newline="", encoding="utf-8") as tmp:
        df.to_csv(tmp.name, index=False)
        tmp_path = Path(tmp.name)

    response = agent.process_request(
        user_input="Revalidate corrected records from preview table",
        file_path=tmp_path,
        default_room=default_room,
        default_branch=default_branch,
        master_usns=master_usns,
        master_rooms=master_rooms,
    )
    return response, tmp_path


def calculate_metrics_summary(summary_data: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    """
    Extract overall metrics cleanly, preserving the 4-state attendance model.
    """
    if not summary_data or "overall" not in summary_data:
        return {
            "present": 0,
            "absent": 0,
            "pending": 0,
            "unreviewed": 0,
            "confirmed": 0,
            "total": 0,
            "confirmed_percentage": 0.0,
        }
    overall = summary_data["overall"]
    pct = overall.get("confirmed_percentage", overall.get("percentage", 0.0))
    return {
        "present": overall.get("present", 0),
        "absent": overall.get("absent", 0),
        "pending": overall.get("pending", 0),
        "unreviewed": overall.get("unreviewed", 0),
        "confirmed": overall.get("confirmed", 0),
        "total": overall.get("total", 0),
        "confirmed_percentage": pct,
    }


def commit_session_to_database(
    db_target: Union[str, Path],
    session_id: str,
    records: List[Dict[str, Any]],
    date: str = "2026-10-25",
    subject: str = "RollCall Attendance",
) -> Tuple[bool, str]:
    """
    Write confirmed attendance records into SQLite database with full transaction integrity.
    """
    if not records:
        return False, "No records to commit."
    
    conn = get_connection(db_target)
    try:
        init_db(conn)
        # Ensure session exists; ignore duplicate insert if it already exists.
        try:
            insert_session(conn, session_id=session_id, date=date, subject=subject)
        except sqlite3.IntegrityError:
            pass
        
        # Prepare attendance rows
        formatted_records = []
        for r in records:
            formatted_records.append({
                "session_id": session_id,
                "usn": str(r.get("usn", "")).strip().upper(),
                "room_id": str(r.get("room_id", r.get("room", "LH-101"))).strip(),
                "status": str(r.get("status", "UNREVIEWED")).strip().upper(),
                "source": str(r.get("source", "UI_CONFIRMED")).strip(),
                "confidence": float(r.get("confidence", 1.0)),
            })
        try:
            rows_affected = replace_session_attendance(conn, session_id=session_id, records=formatted_records)
            return True, f"Successfully committed {rows_affected} records for session '{session_id}'."
        except Exception as exc:
            return False, f"Failed to commit attendance: {exc}"
    finally:
        conn.close()



def generate_export_buffers(summary_report_obj: SummaryReport) -> Tuple[bytes, bytes]:
    """
    Generate downloadable Excel and PDF bytes in memory.
    """
    with tempfile.TemporaryDirectory() as tmp_dir:
        excel_path = Path(tmp_dir) / "attendance_summary.xlsx"
        pdf_path = Path(tmp_dir) / "attendance_summary.pdf"

        export_to_excel(summary_report_obj, excel_path)
        export_to_pdf(summary_report_obj, pdf_path)

        with open(excel_path, "rb") as f:
            excel_bytes = f.read()
        with open(pdf_path, "rb") as f:
            pdf_bytes = f.read()

    return excel_bytes, pdf_bytes


# ==============================================================================
# UI Component Renderers
# ==============================================================================

def render_agent_activity_log(logs: List[Dict[str, Any]]) -> None:
    """Render a styled agent tool execution badge list."""
    if not logs:
        st.info("ℹ️ No tools executed for this request yet.")
        return

    with st.expander(f"🛠️ Agent Activity Log ({len(logs)} tool call{'s' if len(logs) != 1 else ''})", expanded=True):
        for idx, call in enumerate(logs, start=1):
            tool = call.get("tool_name", "unknown_tool")
            status = "✅ PASS" if call.get("success") else "❌ FAIL"
            duration = call.get("duration_seconds", 0.0)
            summary = call.get("result_summary", "")
            error = call.get("error_message")

            col1, col2, col3 = st.columns([3, 1, 1])
            col1.markdown(f"**Step {idx}: `{tool}`**")
            col2.markdown(f"`{status}`")
            col3.markdown(f"⏱️ `{duration:.3f}s`")
            if summary:
                st.caption(f"Result: {summary}")
            if error:
                st.error(f"Error: {error}")
            st.divider()


def render_upload_tab(agent: AttendanceAgent) -> None:
    """Render the Upload & Review Tab."""
    st.subheader("📤 Upload Attendance Records")
    st.write(
        "Upload a **CSV file** or an **attendance sheet photo** (`.jpg`, `.png`). "
        "The agent will automatically parse, extract, and validate each student record against the roster."
    )

    col_up, col_conf = st.columns([2, 1])
    with col_up:
        uploaded_file = st.file_uploader(
            "Choose CSV or Photo",
            type=["csv", "jpg", "jpeg", "png"],
            help="Supported: .csv, .jpg, .jpeg, .png",
            key="file_uploader_widget",
        )
    with col_conf:
        session_id_input = st.text_input(
            "Target Session ID",
            value=st.session_state.get("active_session_id", "SESS-20261025-01"),
            help="Session identifier to link this attendance batch",
        )
        st.session_state["active_session_id"] = session_id_input
        default_room = st.text_input("Default Room ID (optional)", value="LH-101")
        default_branch = st.text_input("Default Branch (optional)", value="CSE")

    if uploaded_file is not None:
        process_btn = st.button("🚀 Process Attendance with Agent", type="primary", use_container_width=True)
        if process_btn:
            with st.spinner("Agent is inspecting file and invoking tools..."):
                response, tmp_file = process_uploaded_file(
                    agent=agent,
                    uploaded_file=uploaded_file,
                    session_id=session_id_input,
                    default_room=default_room,
                    default_branch=default_branch,
                )
                st.session_state["latest_response"] = response
                st.session_state["current_records"] = response.data or []
                st.session_state["temp_file_path"] = str(tmp_file)

    # Display active response / records
    response: Optional[AgentResponse] = st.session_state.get("latest_response")
    if response:
        # Show tool activity log
        render_agent_activity_log(response.tool_calls)

        # Handle Needs Confirmation / Validation Issues
        if response.needs_confirmation or not response.success:
            st.warning("⚠️ **Review & Confirmation Required**")
            st.markdown(
                f"> **Agent Message**: {response.message}\n\n"
                f"Issues were detected (e.g. low OCR confidence `< {CONFIDENCE_CONFIRMATION_THRESHOLD}`, "
                f"duplicate USN, missing room/branch, or conflicting statuses). "
                f"Please review and correct the rows below before summarising or saving."
            )
            
            if response.confirmation_request and response.confirmation_request.issues:
                st.error("**Itemized Validation Issues:**\n- " + "\n- ".join(response.confirmation_request.issues))

            # Editable Preview Table
            records_to_edit = st.session_state.get("current_records", [])
            if records_to_edit:
                st.markdown("### ✍️ Editable Preview Table")
                st.caption("You can edit values directly in the cells below, then click **'Confirm & Re-validate Records'**.")
                
                df_editor = pd.DataFrame(records_to_edit)
                # Standardize column list for clean editing
                expected_cols = ["usn", "name", "branch", "room_id", "status", "confidence"]
                for c in expected_cols:
                    if c not in df_editor.columns:
                        if c == "status":
                            df_editor[c] = "UNREVIEWED"
                        elif c == "confidence":
                            df_editor[c] = 1.0
                        else:
                            df_editor[c] = ""
                
                # Order columns
                df_editor = df_editor[[c for c in expected_cols if c in df_editor.columns]]

                edited_df = st.data_editor(
                    df_editor,
                    num_rows="dynamic",
                    use_container_width=True,
                    key="records_data_editor",
                    column_config={
                        "status": st.column_config.SelectboxColumn(
                            "Status",
                            help="Attendance status",
                            options=["PRESENT", "ABSENT", "PENDING", "UNREVIEWED"],
                            required=True,
                        ),
                        "confidence": st.column_config.NumberColumn(
                            "Confidence",
                            help="OCR extraction confidence (0.0 to 1.0)",
                            min_value=0.0,
                            max_value=1.0,
                            step=0.01,
                        ),
                    },
                )

                if st.button("✅ Confirm & Re-validate Records", type="primary", use_container_width=True):
                    with st.spinner("Re-validating corrected records..."):
                        corrected_records = edited_df.to_dict(orient="records")
                        new_resp, _ = revalidate_and_summarise(
                            agent=agent,
                            records=corrected_records,
                            default_room=default_room,
                            default_branch=default_branch,
                        )
                        st.session_state["latest_response"] = new_resp
                        st.session_state["current_records"] = new_resp.data or corrected_records
                        st.rerun()

        else:
            # Clean validation success
            st.success("✅ **Attendance Dataset Successfully Validated!**")
            st.markdown(f"> **Agent Message**: {response.message}")
            
            records = st.session_state.get("current_records", [])
            if records:
                st.dataframe(pd.DataFrame(records), use_container_width=True)

            # Option to commit to database
            db_target = st.session_state.get("agent_db_target", DEFAULT_DB_PATH)
            if st.button("💾 Save Confirmed Attendance to Database", type="secondary"):
                with st.spinner("Saving records to SQLite database..."):
                    ok, msg = commit_session_to_database(
                        db_target=db_target,
                        session_id=session_id_input,
                        records=records,
                    )
                    if ok:
                        st.success(msg)
                    else:
                        st.error(msg)


def render_dashboard_tab(agent: AttendanceAgent) -> None:
    """Render the Dashboard & Analytics Tab."""
    st.subheader("📊 Attendance Dashboard & Summary Analytics")

    # Check for active validated summary or database session selection
    response: Optional[AgentResponse] = st.session_state.get("latest_response")
    active_summary: Optional[Dict[str, Any]] = None

    if response and response.summary_report:
        active_summary = response.summary_report
        st.info("Displaying summary from the currently validated upload.")
    else:
        # Load from database session
        db_target = st.session_state.get("agent_db_target", DEFAULT_DB_PATH)
        conn = get_connection(db_target)
        sessions = get_all_sessions(conn)
        conn.close()

        if sessions:
            sess_ids = [s["session_id"] for s in sessions]
            selected_sess = st.selectbox("Or view historical database session:", sess_ids)
            if selected_sess:
                conn = get_connection(db_target)
                records = get_session_attendance_details(conn, selected_sess)
                conn.close()
                if records:
                    rep = summary_tool(records)
                    active_summary = rep.to_dict()
                    st.session_state["db_loaded_summary_obj"] = rep
        else:
            st.warning("No attendance data found. Please upload a file in the **Upload** tab first.")
            return

    if not active_summary:
        st.info("No active summary report available. Upload attendance data to view analytics.")
        return

    # 1. Metrics Cards
    metrics = calculate_metrics_summary(active_summary)
    m1, m2, m3, m4, m5 = st.columns(5)
    m1.metric("🟢 Present", metrics["present"])
    m2.metric("🔴 Absent", metrics["absent"])
    m3.metric("🟡 Pending", metrics["pending"])
    m4.metric("⚪ Unreviewed", metrics["unreviewed"])
    m5.metric(
        "📈 Confirmed Rate",
        f"{metrics['confirmed_percentage']:.2f}%",
        help="PRESENT / (PRESENT + ABSENT) * 100. PENDING and UNREVIEWED are preserved as unresolved.",
    )

    st.caption(
        f"**Ground Truth**: Confirmed records: `{metrics['confirmed']}` (Present: {metrics['present']} + "
        f"Absent: {metrics['absent']}). Total records: `{metrics['total']}`."
    )
    st.divider()

    # 2. Room-wise and Branch-wise Tables and Charts
    tab_room, tab_branch = st.tabs(["🏢 Room-Wise Summary", "🎓 Branch-Wise Summary"])

    room_df = pd.DataFrame(active_summary.get("room_wise", []))
    branch_df = pd.DataFrame(active_summary.get("branch_wise", []))

    with tab_room:
        if not room_df.empty:
            st.dataframe(room_df, use_container_width=True)
            if "room_id" in room_df.columns and "present" in room_df.columns:
                chart_data = room_df.set_index("room_id")[["present", "absent"]]
                st.bar_chart(chart_data)
        else:
            st.write("No room-wise records available.")

    with tab_branch:
        if not branch_df.empty:
            st.dataframe(branch_df, use_container_width=True)
            if "branch" in branch_df.columns and "present" in branch_df.columns:
                chart_data = branch_df.set_index("branch")[["present", "absent"]]
                st.bar_chart(chart_data)
        else:
            st.write("No branch-wise records available.")

    st.divider()

    # 3. Export Downloads
    st.markdown("### 📥 Export Verified Summary")
    summary_obj = st.session_state.get("db_loaded_summary_obj")
    if not summary_obj:
        # Reconstruct SummaryReport from active_summary dict
        summary_obj = SummaryReport(
            room_wise=room_df,
            branch_wise=branch_df,
            overall=active_summary.get("overall", {}),
        )

    try:
        excel_bytes, pdf_bytes = generate_export_buffers(summary_obj)
        exp_col1, exp_col2 = st.columns(2)
        with exp_col1:
            st.download_button(
                label="📄 Download Excel Report (.xlsx)",
                data=excel_bytes,
                file_name=f"RollCall_Summary_{st.session_state.get('active_session_id', 'export')}.xlsx",
                mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                use_container_width=True,
            )
        with exp_col2:
            st.download_button(
                label="📑 Download PDF Report (.pdf)",
                data=pdf_bytes,
                file_name=f"RollCall_Summary_{st.session_state.get('active_session_id', 'export')}.pdf",
                mime="application/pdf",
                use_container_width=True,
            )
    except Exception as exc:
        st.error(f"Failed to generate export files: {exc}")


def render_ask_tab(agent: AttendanceAgent) -> None:
    """Render the Ask (Agent Chat) Tab."""
    st.subheader("💬 Ask RollCall AI")
    st.write("Ask natural-language questions about attendance statistics, absentees, or students.")

    # Initialize chat history
    if "chat_history" not in st.session_state:
        st.session_state["chat_history"] = [
            {
                "role": "assistant",
                "content": "Hello! I am your RollCall AI attendance assistant. You can ask me questions about attendance records, absentees in a session, or student rosters.",
                "tools": [],
            }
        ]

    # Sample query prompts
    st.markdown("**Sample queries to try:**")
    q_col1, q_col2, q_col3 = st.columns(3)
    sample_query = None
    if q_col1.button("Who was absent in SESS-20261024-01?"):
        sample_query = "Who was absent in session SESS-20261024-01?"
    if q_col2.button("Attendance percentage in SESS-20261024-01?"):
        sample_query = "What is the attendance percentage for session SESS-20261024-01?"
    if q_col3.button("List all students in CSE branch"):
        sample_query = "List all students in CSE branch"

    # Display chat messages
    for msg in st.session_state["chat_history"]:
        with st.chat_message(msg["role"]):
            st.write(msg["content"])
            if msg.get("tools"):
                render_agent_activity_log(msg["tools"])

    # Chat input
    user_query = st.chat_input("Ask a question about attendance or students...")
    query_to_run = user_query or sample_query

    if query_to_run:
        # Add user query to history
        st.session_state["chat_history"].append({"role": "user", "content": query_to_run, "tools": []})
        with st.chat_message("user"):
            st.write(query_to_run)

        # Process with agent
        with st.chat_message("assistant"):
            with st.spinner("RollCall AI is retrieving data..."):
                resp: AgentResponse = agent.process_request(query_to_run)
                st.write(resp.message)
                if resp.tool_calls:
                    render_agent_activity_log(resp.tool_calls)

                # Append assistant reply to history
                st.session_state["chat_history"].append({
                    "role": "assistant",
                    "content": resp.message,
                    "tools": resp.tool_calls,
                })


# ==============================================================================
# Main Application Entrypoint
# ==============================================================================

def main() -> None:
    st.set_page_config(
        page_title="RollCall AI — Intelligent Attendance Agent",
        page_icon="🎓",
        layout="wide",
        initial_sidebar_state="expanded",
    )

    # Sidebar
    st.sidebar.title("🎓 RollCall AI")
    st.sidebar.caption("Intelligent Multi-Modal Attendance Agent")
    st.sidebar.markdown("---")

    db_target = st.sidebar.text_input("Database Target", value=DEFAULT_DB_PATH)
    agent = get_or_create_agent(db_target=db_target)

    # Inspect DB status in sidebar
    try:
        conn = get_connection(db_target)
        init_db(conn)
        students = get_all_students(conn)
        sessions = get_all_sessions(conn)
        rooms = get_all_rooms(conn)
        conn.close()
        st.sidebar.success(f"🟢 Database Connected\n- Students: {len(students)}\n- Sessions: {len(sessions)}\n- Rooms: {len(rooms)}")
    except Exception as exc:
        st.sidebar.error(f"🔴 DB Error: {exc}")

    if st.sidebar.button("🔄 Reset App State"):
        for key in list(st.session_state.keys()):
            del st.session_state[key]
        st.rerun()

    st.sidebar.markdown("---")
    st.sidebar.caption("Group 7 | 4-Phase Antigravity Workflow")

    # Main Tabs
    tab_upload, tab_dash, tab_ask = st.tabs(["📤 Upload & Review", "📊 Dashboard & Analytics", "💬 Ask RollCall AI"])

    with tab_upload:
        render_upload_tab(agent)

    with tab_dash:
        render_dashboard_tab(agent)

    with tab_ask:
        render_ask_tab(agent)


if __name__ == "__main__":
    main()
