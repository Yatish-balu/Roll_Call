"""Application Tool Catalogue Package for RollCall AI.

Provides centralized registration of all agent tools into the ToolRegistry:
- Timetable & Academic Setup tools (get_my_timetable, get_day_schedule, create_session)
- Core Legacy tools wrapped (read_csv, read_photo, validate_attendance, generate_summary, query_attendance, export_attendance)
- Risk-Tiered Attendance tools (single_attendance_correction, bulk_attendance_proposal)
- Profile & Analytics tools (get_my_profile, get_defaulters_analysis)
"""

from __future__ import annotations

import logging
from typing import Optional

from app.agent.registry import ToolRegistry, tool_registry
from app.agent.tools.attendance_tools import (
    BULK_ATTENDANCE_PROPOSAL_TOOL,
    EXPORT_ATTENDANCE_TOOL,
    GENERATE_SUMMARY_TOOL,
    QUERY_ATTENDANCE_TOOL,
    READ_CSV_TOOL,
    READ_PHOTO_TOOL,
    SINGLE_ATTENDANCE_CORRECTION_TOOL,
    VALIDATE_ATTENDANCE_TOOL,
)
from app.agent.tools.profile_analytics_tools import (
    GET_DEFAULTERS_ANALYSIS_TOOL,
    GET_MY_PROFILE_TOOL,
)
from app.agent.tools.timetable_tools import (
    CREATE_SESSION_TOOL,
    GET_DAY_SCHEDULE_TOOL,
    GET_MY_TIMETABLE_TOOL,
)

logger = logging.getLogger("rollcall.agent.tools")

ALL_TOOLS = [
    # Academic & Schedule
    GET_MY_TIMETABLE_TOOL,
    GET_DAY_SCHEDULE_TOOL,
    CREATE_SESSION_TOOL,
    # Attendance & Document Intake
    READ_CSV_TOOL,
    READ_PHOTO_TOOL,
    VALIDATE_ATTENDANCE_TOOL,
    GENERATE_SUMMARY_TOOL,
    QUERY_ATTENDANCE_TOOL,
    EXPORT_ATTENDANCE_TOOL,
    SINGLE_ATTENDANCE_CORRECTION_TOOL,
    BULK_ATTENDANCE_PROPOSAL_TOOL,
    # Profile & Analytics
    GET_MY_PROFILE_TOOL,
    GET_DEFAULTERS_ANALYSIS_TOOL,
]


def register_all_tools(target_registry: Optional[ToolRegistry] = None) -> ToolRegistry:
    """Register all defined application tools into the global or specified ToolRegistry."""
    reg = target_registry or tool_registry
    for tool_def in ALL_TOOLS:
        reg.register(tool_def)
    logger.info("Successfully registered %d application tools into ToolRegistry.", len(ALL_TOOLS))
    return reg


__all__ = [
    "ALL_TOOLS",
    "register_all_tools",
    "GET_MY_TIMETABLE_TOOL",
    "GET_DAY_SCHEDULE_TOOL",
    "CREATE_SESSION_TOOL",
    "READ_CSV_TOOL",
    "READ_PHOTO_TOOL",
    "VALIDATE_ATTENDANCE_TOOL",
    "GENERATE_SUMMARY_TOOL",
    "QUERY_ATTENDANCE_TOOL",
    "EXPORT_ATTENDANCE_TOOL",
    "SINGLE_ATTENDANCE_CORRECTION_TOOL",
    "BULK_ATTENDANCE_PROPOSAL_TOOL",
    "GET_MY_PROFILE_TOOL",
    "GET_DEFAULTERS_ANALYSIS_TOOL",
]

