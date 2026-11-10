"""Tool wrapper allowing the LLM agent to propose an attendance edit (Prompt N7).

CRITICAL SECURITY CONSTRAINT:
This tool only stages an edit proposal and returns a confirmation card payload.
It CANNOT commit or confirm an edit. There is NO 'confirm' parameter in this tool.
"""

from __future__ import annotations

from typing import Any, Dict, Optional
from app.services.pending_edits import prepare_edit


def update_attendance_tool(
    user: Any,
    subject: str,
    usn: str,
    new_status: str,
    date: Optional[str] = None,
    db: Optional[Any] = None,
) -> Dict[str, Any]:
    """Propose an attendance change for confirmation.
    
    Parameters:
      user: Authenticated user object from verified session/token (never from LLM text).
      subject: Subject or course name / code.
      usn: Student University Seat Number.
      new_status: 'Present' or 'Absent'.
      date: Optional date string ('today' or 'YYYY-MM-DD').
    """
    return prepare_edit(
        user=user,
        subject=subject,
        usn=usn,
        new_status=new_status,
        date_str=date,
        db=db,
    )

