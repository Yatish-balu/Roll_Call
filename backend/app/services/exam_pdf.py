"""ReportLab PDF generation for official DSCE Form-B and Exam Absentees Statement."""

from __future__ import annotations

import io
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional
from xml.sax.saxutils import escape

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import HRFlowable, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

from app.db.models import Exam, ExamSeating, RoomAssignment


def _escape(val: Any) -> str:
    """Escape text for safe ReportLab XML rendering."""
    s = str(val) if val is not None else ""
    # Defend against CSV injection characters if rendered
    if s.startswith(("=", "+", "-", "@")):
        s = "'" + s
    return escape(s)


def generate_printable_form_b_pdf(
    exam: Exam,
    room: RoomAssignment,
    roster: List[ExamSeating],
) -> bytes:
    """Generate blank printable Form-B matching the official DSCE examination format."""
    buf = io.BytesIO()
    doc = SimpleDocTemplate(
        buf,
        pagesize=A4,
        leftMargin=10 * mm,
        rightMargin=10 * mm,
        topMargin=10 * mm,
        bottomMargin=10 * mm,
    )

    styles = getSampleStyleSheet()
    title_style = ParagraphStyle(
        "HeaderTitle",
        parent=styles["Normal"],
        fontName="Helvetica-Bold",
        fontSize=12,
        leading=14,
        alignment=1,  # Center
        textColor=colors.HexColor("#1A202C"),
    )
    subtitle_style = ParagraphStyle(
        "HeaderSubtitle",
        parent=styles["Normal"],
        fontName="Helvetica",
        fontSize=8.5,
        leading=11,
        alignment=1,
        textColor=colors.HexColor("#4A5568"),
    )
    exam_title_style = ParagraphStyle(
        "ExamTitle",
        parent=styles["Normal"],
        fontName="Helvetica-Bold",
        fontSize=10,
        leading=13,
        alignment=1,
        textColor=colors.HexColor("#2D3748"),
    )
    subhead_style = ParagraphStyle(
        "SubHead",
        parent=styles["Normal"],
        fontName="Helvetica-Bold",
        fontSize=9,
        leading=11,
    )
    cell_style = ParagraphStyle(
        "Cell",
        parent=styles["Normal"],
        fontName="Helvetica",
        fontSize=7.5,
        leading=9,
    )
    cell_bold = ParagraphStyle(
        "CellBold",
        parent=styles["Normal"],
        fontName="Helvetica-Bold",
        fontSize=7.5,
        leading=9,
    )

    elements = []

    # 1. Header
    elements.append(Paragraph("DAYANANDA SAGAR COLLEGE OF ENGINEERING", title_style))
    elements.append(
        Paragraph("(An Autonomous Institute Affiliated to VTU, Belagavi)<br/>Shavige Malleshwara Hills, Kumaraswamy Layout, Bengaluru-560078", subtitle_style)
    )
    elements.append(Spacer(1, 2 * mm))
    dept = exam.department or "Department of Computer Science and Engineering"
    elements.append(Paragraph(f"<b>{_escape(dept)}</b>", subtitle_style))
    elements.append(Spacer(1, 2 * mm))
    elements.append(Paragraph(f"<b>{_escape(exam.name)}</b>", exam_title_style))
    elements.append(Spacer(1, 3 * mm))

    # 2. Meta bar (Semester | Form-B | Room No)
    sem_str = f"Semester-{exam.semester}" if exam.semester else "Semester: All"
    meta_table_data = [
        [
            Paragraph(f"<b>{sem_str}</b>", subhead_style),
            Paragraph("<b>Form-B</b>", ParagraphStyle("FormB", parent=title_style, fontSize=11)),
            Paragraph(f"<b>Room No. {_escape(room.room_no)}</b>", ParagraphStyle("RoomR", parent=subhead_style, alignment=2)),
        ]
    ]
    meta_table = Table(meta_table_data, colWidths=[60 * mm, 70 * mm, 60 * mm])
    meta_table.setStyle(
        TableStyle([
            ("ALIGN", (0, 0), (0, 0), "LEFT"),
            ("ALIGN", (1, 0), (1, 0), "CENTER"),
            ("ALIGN", (2, 0), (2, 0), "RIGHT"),
            ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 2),
        ])
    )
    elements.append(meta_table)
    elements.append(HRFlowable(width="100%", thickness=1, color=colors.HexColor("#718096"), spaceBefore=2, spaceAfter=4))

    # 3. Student Roster Table
    header_col = f"{exam.date}<br/>{exam.subject_code}"
    table_data = [
        [
            Paragraph("<b>Sl.<br/>No</b>", cell_bold),
            Paragraph("<b>USN</b>", cell_bold),
            Paragraph("<b>STUDENT NAME</b>", cell_bold),
            Paragraph("<b>Branch</b>", cell_bold),
            Paragraph(f"<b>{header_col}</b><br/><font size=6 color='#718096'>(Signature or 'Ab')</font>", cell_bold),
        ]
    ]

    for student in roster:
        # If student already marked, display it, else empty box for signature
        sig_display = ""
        if student.status == "PRESENT":
            sig_display = "<b>Signed / Present</b>"
        elif student.status == "ABSENT" and room.status == "SUBMITTED":
            sig_display = "<font color='red'><b>Ab</b></font>"

        table_data.append([
            Paragraph(str(student.sl_no), cell_style),
            Paragraph(f"<b>{_escape(student.usn)}</b>", cell_style),
            Paragraph(_escape(student.name), cell_style),
            Paragraph(_escape(student.branch), cell_style),
            Paragraph(sig_display, cell_style),
        ])

    # Summary rows matching DSCE format
    total_stds = len(roster)
    present_cnt = sum(1 for s in roster if s.status == "PRESENT")
    absent_cnt = total_stds - present_cnt if room.status == "SUBMITTED" else 0
    absent_str = "NIL" if absent_cnt == 0 else str(absent_cnt)
    present_str = str(present_cnt) if room.status == "SUBMITTED" else "____"

    table_data.append([
        "", "", Paragraph("<b>No. of Students Present</b>", cell_bold), "", Paragraph(present_str, cell_bold)
    ])
    table_data.append([
        "", "", Paragraph("<b>No. of Students Absent</b>", cell_bold), "", Paragraph(absent_str if room.status == "SUBMITTED" else "____", cell_bold)
    ])
    table_data.append([
        "", "", Paragraph("<b>Initials of Invigilator</b>", cell_bold), "", Paragraph("____", cell_bold)
    ])
    table_data.append([
        "", "", Paragraph("<b>Signature of Invigilator</b>", cell_bold), "", Paragraph("____________________", cell_bold)
    ])
    table_data.append([
        "", "", Paragraph("<b>Signature of Squad</b>", cell_bold), "", Paragraph("____________________", cell_bold)
    ])

    col_widths = [12 * mm, 32 * mm, 70 * mm, 20 * mm, 56 * mm]
    t = Table(table_data, colWidths=col_widths, repeatRows=1)
    
    t_style = [
        ("GRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#A0AEC0")),
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#EDF2F7")),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("ALIGN", (0, 0), (0, -1), "CENTER"),
        ("TOPPADDING", (0, 0), (-1, -1), 2),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 2),
    ]
    # Merge summary rows
    offset = len(roster) + 1
    for r in range(offset, offset + 5):
        t_style.append(("SPAN", (2, r), (3, r)))
        t_style.append(("BACKGROUND", (2, r), (-1, r), colors.HexColor("#F7FAFC")))

    t.setStyle(TableStyle(t_style))
    elements.append(t)
    elements.append(Spacer(1, 8 * mm))

    # 4. Footer signatures
    footer_data = [
        [
            Paragraph("<b>Test Coordinator</b><br/><font size=7 color='#718096'>Signature with Date</font>", cell_style),
            Paragraph("<b>Professor & Head of Department</b><br/><font size=7 color='#718096'>Seal & Signature</font>", ParagraphStyle("HOD", parent=cell_style, alignment=2)),
        ]
    ]
    footer_table = Table(footer_data, colWidths=[95 * mm, 95 * mm])
    elements.append(footer_table)

    doc.build(elements)
    return buf.getvalue()


def generate_exam_absentees_statement_pdf(
    exam: Exam,
    room_summaries: List[Dict[str, Any]],
    branch_summaries: List[Dict[str, Any]],
) -> bytes:
    """Generate consolidated Exam Absentees Statement for the Chief Superintendent / Exam Cell."""
    buf = io.BytesIO()
    doc = SimpleDocTemplate(
        buf,
        pagesize=A4,
        leftMargin=12 * mm,
        rightMargin=12 * mm,
        topMargin=12 * mm,
        bottomMargin=12 * mm,
    )

    styles = getSampleStyleSheet()
    title_style = ParagraphStyle(
        "Title",
        parent=styles["Normal"],
        fontName="Helvetica-Bold",
        fontSize=13,
        leading=16,
        alignment=1,
        textColor=colors.HexColor("#1A202C"),
    )
    subtitle_style = ParagraphStyle(
        "Sub",
        parent=styles["Normal"],
        fontName="Helvetica",
        fontSize=9,
        leading=12,
        alignment=1,
        textColor=colors.HexColor("#4A5568"),
    )
    h2_style = ParagraphStyle(
        "H2",
        parent=styles["Normal"],
        fontName="Helvetica-Bold",
        fontSize=10,
        leading=13,
        textColor=colors.HexColor("#2D3748"),
    )
    cell_style = ParagraphStyle("C", parent=styles["Normal"], fontName="Helvetica", fontSize=8, leading=10)
    cell_bold = ParagraphStyle("CB", parent=styles["Normal"], fontName="Helvetica-Bold", fontSize=8, leading=10)

    elements = []

    # Header
    elements.append(Paragraph("DAYANANDA SAGAR COLLEGE OF ENGINEERING", title_style))
    elements.append(Paragraph("OFFICE OF THE CONTROLLER OF EXAMINATIONS<br/>CONSOLIDATED ABSENTEE STATEMENT", subtitle_style))
    elements.append(Spacer(1, 3 * mm))
    elements.append(Paragraph(f"<b>Exam:</b> {_escape(exam.name)} &nbsp;&nbsp;|&nbsp;&nbsp; <b>Date:</b> {exam.date} &nbsp;&nbsp;|&nbsp;&nbsp; <b>Time:</b> {exam.start_time} - {exam.end_time}", cell_style))
    elements.append(HRFlowable(width="100%", thickness=1, color=colors.HexColor("#A0AEC0"), spaceBefore=3, spaceAfter=5))

    # Room-Wise Table
    elements.append(Paragraph("<b>1. Room-Wise Attendance Summary</b>", h2_style))
    elements.append(Spacer(1, 2 * mm))

    room_table_data = [
        [
            Paragraph("<b>Room No.</b>", cell_bold),
            Paragraph("<b>Block</b>", cell_bold),
            Paragraph("<b>Invigilator</b>", cell_bold),
            Paragraph("<b>Allotted</b>", cell_bold),
            Paragraph("<b>Present</b>", cell_bold),
            Paragraph("<b>Absent</b>", cell_bold),
            Paragraph("<b>Status</b>", cell_bold),
        ]
    ]

    total_allotted = 0
    total_present = 0
    total_absent = 0

    all_absentees = []

    for r in room_summaries:
        tot = r.get("total_students", 0)
        pres = r.get("present_count", 0)
        ab = r.get("absent_count", 0)
        total_allotted += tot
        total_present += pres
        total_absent += ab

        for a in r.get("absentees", []):
            all_absentees.append({**a, "room_no": r.get("room_no")})

        room_table_data.append([
            Paragraph(_escape(r.get("room_no")), cell_style),
            Paragraph(_escape(r.get("block_name", "-")), cell_style),
            Paragraph(_escape(r.get("invigilator_id", "Unassigned")), cell_style),
            Paragraph(str(tot), cell_style),
            Paragraph(str(pres), cell_style),
            Paragraph(f"<font color='red'><b>{ab}</b></font>" if ab > 0 else "0", cell_style),
            Paragraph(r.get("status", "SCHEDULED"), cell_style),
        ])

    # Total row
    room_table_data.append([
        Paragraph("<b>TOTAL</b>", cell_bold),
        "", "",
        Paragraph(f"<b>{total_allotted}</b>", cell_bold),
        Paragraph(f"<b>{total_present}</b>", cell_bold),
        Paragraph(f"<font color='red'><b>{total_absent}</b></font>", cell_bold),
        "",
    ])

    rt = Table(room_table_data, colWidths=[25 * mm, 30 * mm, 40 * mm, 20 * mm, 20 * mm, 20 * mm, 31 * mm])
    rt.setStyle(TableStyle([
        ("GRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#CBD5E0")),
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#EDF2F7")),
        ("BACKGROUND", (0, -1), (-1, -1), colors.HexColor("#F7FAFC")),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("ALIGN", (3, 0), (5, -1), "CENTER"),
        ("TOPPADDING", (0, 0), (-1, -1), 2.5),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 2.5),
    ]))
    elements.append(rt)
    elements.append(Spacer(1, 5 * mm))

    # Branch-Wise Summary
    elements.append(Paragraph("<b>2. Branch-Wise Attendance Distribution</b>", h2_style))
    elements.append(Spacer(1, 2 * mm))

    branch_table_data = [
        [
            Paragraph("<b>Branch Code</b>", cell_bold),
            Paragraph("<b>Total Registered</b>", cell_bold),
            Paragraph("<b>Present Count</b>", cell_bold),
            Paragraph("<b>Absent Count</b>", cell_bold),
            Paragraph("<b>Attendance %</b>", cell_bold),
        ]
    ]

    for b in branch_summaries:
        branch_table_data.append([
            Paragraph(f"<b>{_escape(b.get('branch'))}</b>", cell_style),
            Paragraph(str(b.get("total_students", 0)), cell_style),
            Paragraph(str(b.get("present_count", 0)), cell_style),
            Paragraph(str(b.get("absent_count", 0)), cell_style),
            Paragraph(f"{b.get('attendance_percentage', 0.0):.1f}%", cell_style),
        ])

    bt = Table(branch_table_data, colWidths=[35 * mm, 35 * mm, 35 * mm, 35 * mm, 46 * mm])
    bt.setStyle(TableStyle([
        ("GRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#CBD5E0")),
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#EDF2F7")),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("ALIGN", (1, 0), (-1, -1), "CENTER"),
        ("TOPPADDING", (0, 0), (-1, -1), 2.5),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 2.5),
    ]))
    elements.append(bt)
    elements.append(Spacer(1, 5 * mm))

    # Detailed Absentees List
    elements.append(Paragraph(f"<b>3. Detailed List of Absentees (Total: {len(all_absentees)})</b>", h2_style))
    elements.append(Spacer(1, 2 * mm))

    if all_absentees:
        abs_data = [
            [
                Paragraph("<b>Sl</b>", cell_bold),
                Paragraph("<b>Room</b>", cell_bold),
                Paragraph("<b>USN</b>", cell_bold),
                Paragraph("<b>Student Name</b>", cell_bold),
                Paragraph("<b>Branch</b>", cell_bold),
            ]
        ]
        for idx, a in enumerate(all_absentees, 1):
            abs_data.append([
                Paragraph(str(idx), cell_style),
                Paragraph(_escape(a.get("room_no", "-")), cell_style),
                Paragraph(f"<font color='red'><b>{_escape(a.get('usn'))}</b></font>", cell_style),
                Paragraph(_escape(a.get("name")), cell_style),
                Paragraph(_escape(a.get("branch")), cell_style),
            ])
        at = Table(abs_data, colWidths=[12 * mm, 25 * mm, 35 * mm, 80 * mm, 34 * mm])
        at.setStyle(TableStyle([
            ("GRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#CBD5E0")),
            ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#FFF5F5")),
            ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
            ("TOPPADDING", (0, 0), (-1, -1), 2),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 2),
        ]))
        elements.append(at)
    else:
        elements.append(Paragraph("<i>No absentees reported across all examination rooms (100% Attendance).</i>", cell_style))

    elements.append(Spacer(1, 10 * mm))

    # Signatures
    elements.append(Table([
        [
            Paragraph("<b>Exam Cell Coordinator</b><br/><font size=7 color='#718096'>Verified & Entered</font>", cell_style),
            Paragraph("<b>Chief Superintendent</b><br/><font size=7 color='#718096'>Approved & Sealed</font>", ParagraphStyle("CS", parent=cell_style, alignment=2)),
        ]
    ], colWidths=[93 * mm, 93 * mm]))

    doc.build(elements)
    return buf.getvalue()
