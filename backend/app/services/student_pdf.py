"""Student roster PDF generation with server-side branch and semester filters.

The filters are applied by the database query, never in the browser, so the
generated document and the reported student count always describe exactly the
same population.
"""

from __future__ import annotations

import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4, landscape
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

from app.db.models import Semester, Student

VALID_SEMESTERS = (1, 2, 3, 4, 5, 6, 7, 8)


def normalise_semester(value: Optional[Any]) -> Optional[int]:
    """Validate a semester filter value (1 - 8)."""
    if value is None or value == "":
        return None
    try:
        number = int(value)
    except (TypeError, ValueError):
        raise ValueError("Semester must be a whole number between 1 and 8.")
    if number not in VALID_SEMESTERS:
        raise ValueError("Semester must be between 1 and 8.")
    return number


def build_student_query(
    scope_condition=None,
    branch: Optional[str] = None,
    semester: Optional[int] = None,
):
    """Build the filtered student query (filters are applied server-side)."""
    from sqlalchemy import select

    stmt = select(Student)
    if scope_condition is not None:
        stmt = stmt.where(scope_condition)
    if branch and branch.strip() and branch.strip().upper() != "ALL":
        stmt = stmt.where(Student.branch == branch.strip().upper())
    if semester is not None:
        semester_ids = select(Semester.semester_id).where(
            Semester.semester_number == semester
        )
        stmt = stmt.where(Student.semester_id.in_(semester_ids))
    return stmt.order_by(Student.branch, Student.usn)


def describe_filters(branch: Optional[str], semester: Optional[int]) -> str:
    parts = []
    if branch and branch.strip() and branch.strip().upper() != "ALL":
        parts.append(f"Branch: {branch.strip().upper()}")
    else:
        parts.append("Branch: All")
    if semester is not None:
        parts.append(f"Semester: {semester}")
    else:
        parts.append("Semester: All")
    return " | ".join(parts)


def export_students_pdf(
    students: List[Dict[str, Any]],
    output_path: str | Path,
    title: str = "RollCall AI Student Roster",
    branch: Optional[str] = None,
    semester: Optional[int] = None,
) -> Dict[str, Any]:
    """Render the (already filtered) student roster into a PDF file."""
    styles = getSampleStyleSheet()
    title_style = ParagraphStyle(
        "RosterTitle",
        parent=styles["Title"],
        fontSize=16,
        leading=20,
        textColor=colors.HexColor("#3F451F"),
        spaceAfter=2,
    )
    meta_style = ParagraphStyle(
        "RosterMeta",
        parent=styles["Normal"],
        fontSize=9,
        leading=13,
        textColor=colors.HexColor("#6C5119"),
    )
    body_style = ParagraphStyle(
        "RosterBody",
        parent=styles["Normal"],
        fontSize=8.5,
        leading=12,
    )

    path = Path(output_path)
    doc = SimpleDocTemplate(
        str(path),
        pagesize=landscape(A4),
        leftMargin=12 * mm,
        rightMargin=12 * mm,
        topMargin=12 * mm,
        bottomMargin=12 * mm,
        title=title,
    )

    story = [
        Paragraph(title, title_style),
        Paragraph(
            f"Generated {datetime.datetime.now().strftime('%d %b %Y, %H:%M')} &nbsp;|&nbsp; "
            f"{describe_filters(branch, semester)} &nbsp;|&nbsp; "
            f"Students: {len(students)}",
            meta_style,
        ),
        Spacer(1, 6 * mm),
    ]

    header = ["USN", "Student Name", "Branch", "Department", "Semester", "Section", "Batch"]
    rows = [header]
    for student in students:
        rows.append(
            [
                str(student.get("usn", "")),
                str(student.get("name", "")),
                str(student.get("branch", "")),
                str(student.get("dept_id") or "-"),
                str(student.get("semester_number") or student.get("semester_id") or "-"),
                str(student.get("section_label") or student.get("section_id") or "-"),
                str(student.get("batch_label") or student.get("batch_id") or "-"),
            ]
        )

    table = Table(rows, repeatRows=1, colWidths=[32 * mm, 60 * mm, 24 * mm, 30 * mm, 22 * mm, 22 * mm, 22 * mm])
    table.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#3F451F")),
                ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
                ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
                ("FONTSIZE", (0, 0), (-1, -1), 8.5),
                ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                ("GRID", (0, 0), (-1, -1), 0.25, colors.HexColor("#E4DDCA")),
                ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#FBF8F0")]),
                ("TOPPADDING", (0, 0), (-1, -1), 4),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
            ]
        )
    )
    story.append(table)

    if not students:
        story.append(Spacer(1, 6 * mm))
        story.append(
            Paragraph(
                "No students matched the selected filters. "
                "Clear the branch or semester filter and try again.",
                body_style,
            )
        )

    doc.build(story)
    return {
        "path": str(path),
        "row_count": len(students),
        "branch": branch,
        "semester": semester,
    }
