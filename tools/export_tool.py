"""Export tool for generating structured Excel (.xlsx) and PDF (.pdf) reports.

Supports room-wise summaries, branch-wise summaries, and detail records.
Preserves all four attendance states (PRESENT, ABSENT, PENDING, UNREVIEWED).
Strictly uses confirmed attendance percentage: PRESENT / (PRESENT + ABSENT) * 100,
handling zero denominator without division errors.
Verifies file generation before claiming success.
"""

from __future__ import annotations

import os
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Union
import pandas as pd

from tools.summary_tool import SummaryReport, summary_tool

# ReportLab imports for PDF generation
from reportlab.lib import colors
from reportlab.lib.pagesizes import letter, landscape
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.platypus import (
    SimpleDocTemplate,
    Paragraph,
    Spacer,
    Table,
    TableStyle,
    KeepTogether,
)


@dataclass
class ExportResult:
    """Result of an export operation."""

    success: bool
    format: str
    file_path: str
    file_size_bytes: int
    row_count: int
    summary_sheets: List[str]
    message: str
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


def _prepare_export_dataframes(
    data: Union[pd.DataFrame, List[Dict[str, Any]], SummaryReport, Dict[str, Any]]
) -> Tuple[Optional[pd.DataFrame], Optional[pd.DataFrame], Optional[pd.DataFrame]]:
    """
    Extract (detail_df, room_df, branch_df) from input data.
    Generates summary tables automatically if raw records are provided.
    """
    detail_df: Optional[pd.DataFrame] = None
    room_df: Optional[pd.DataFrame] = None
    branch_df: Optional[pd.DataFrame] = None

    if isinstance(data, SummaryReport):
        room_df = data.room_wise.copy() if data.room_wise is not None else None
        branch_df = data.branch_wise.copy() if data.branch_wise is not None else None
    elif isinstance(data, dict):
        if "room_wise" in data or "branch_wise" in data:
            if "room_wise" in data:
                room_df = pd.DataFrame(data["room_wise"])
            if "branch_wise" in data:
                branch_df = pd.DataFrame(data["branch_wise"])
            if "detail" in data or "records" in data:
                detail_df = pd.DataFrame(data.get("detail") or data.get("records"))
        else:
            # Single dictionary or records map
            detail_df = pd.DataFrame([data])
    elif isinstance(data, pd.DataFrame):
        detail_df = data.copy()
    elif isinstance(data, list):
        detail_df = pd.DataFrame(data)
    else:
        raise ValueError(f"Unsupported data format for export: {type(data)}")

    # If detail_df is present and summaries not precomputed, compute summaries using summary_tool
    if detail_df is not None and not detail_df.empty and (room_df is None or branch_df is None):
        summary_rep = summary_tool(detail_df)
        if room_df is None:
            room_df = summary_rep.room_wise.copy()
        if branch_df is None:
            branch_df = summary_rep.branch_wise.copy()

    return detail_df, room_df, branch_df


def _validate_output_path(output_path: Union[str, Path], overwrite: bool = False) -> Path:
    """Validate path, ensure parent directory exists, and check overwrite rule."""
    path = Path(output_path).resolve()
    if path.exists() and not overwrite:
        raise FileExistsError(
            f"File already exists at '{path}'. Set overwrite=True to allow overwriting."
        )
    path.parent.mkdir(parents=True, exist_ok=True)
    return path


def export_to_excel(
    data: Union[pd.DataFrame, List[Dict[str, Any]], SummaryReport, Dict[str, Any]],
    output_path: Union[str, Path],
    overwrite: bool = False,
) -> ExportResult:
    """
    Export attendance data to an Excel (.xlsx) workbook with multiple sheets:
    - 'Room_Summary': Room-wise metrics and percentages.
    - 'Branch_Summary': Branch-wise metrics and percentages.
    - 'Attendance_Details': Individual student records (if available).
    """
    target_path = _validate_output_path(output_path, overwrite=overwrite)
    detail_df, room_df, branch_df = _prepare_export_dataframes(data)

    sheets_written: List[str] = []
    total_rows = 0

    with pd.ExcelWriter(target_path, engine="openpyxl") as writer:
        if room_df is not None and not room_df.empty:
            room_df.to_excel(writer, sheet_name="Room_Summary", index=False)
            sheets_written.append("Room_Summary")
            total_rows += len(room_df)

        if branch_df is not None and not branch_df.empty:
            branch_df.to_excel(writer, sheet_name="Branch_Summary", index=False)
            sheets_written.append("Branch_Summary")
            total_rows += len(branch_df)

        if detail_df is not None and not detail_df.empty:
            detail_df.to_excel(writer, sheet_name="Attendance_Details", index=False)
            sheets_written.append("Attendance_Details")
            total_rows += len(detail_df)

        # Fallback empty sheet if all are empty
        if not sheets_written:
            pd.DataFrame({"Status": ["No data"]}).to_excel(
                writer, sheet_name="Summary", index=False
            )
            sheets_written.append("Summary")

    # Strict verification that file was created and is non-empty
    if not target_path.exists() or target_path.stat().st_size == 0:
        raise RuntimeError(f"Excel export failed: file '{target_path}' was not generated.")

    file_size = target_path.stat().st_size
    return ExportResult(
        success=True,
        format="excel",
        file_path=str(target_path),
        file_size_bytes=file_size,
        row_count=total_rows,
        summary_sheets=sheets_written,
        message=f"Successfully exported Excel workbook with sheets: {', '.join(sheets_written)}.",
        metadata={"sheets": sheets_written},
    )


def export_to_pdf(
    data: Union[pd.DataFrame, List[Dict[str, Any]], SummaryReport, Dict[str, Any]],
    output_path: Union[str, Path],
    title: str = "RollCall AI Attendance Report",
    overwrite: bool = False,
) -> ExportResult:
    """
    Export attendance data to a clean, professional PDF report using ReportLab.
    Includes Room-wise summary table, Branch-wise summary table, and Detail records.
    """
    target_path = _validate_output_path(output_path, overwrite=overwrite)
    detail_df, room_df, branch_df = _prepare_export_dataframes(data)

    doc = SimpleDocTemplate(
        str(target_path),
        pagesize=landscape(letter),
        leftMargin=36,
        rightMargin=36,
        topMargin=36,
        bottomMargin=36,
    )
    styles = getSampleStyleSheet()

    # Custom styles
    title_style = ParagraphStyle(
        "ReportTitle",
        parent=styles["Heading1"],
        fontName="Helvetica-Bold",
        fontSize=18,
        leading=22,
        textColor=colors.HexColor("#1e293b"),
        spaceAfter=12,
    )
    heading_style = ParagraphStyle(
        "SectionHeading",
        parent=styles["Heading2"],
        fontName="Helvetica-Bold",
        fontSize=13,
        leading=16,
        textColor=colors.HexColor("#0f172a"),
        spaceBefore=14,
        spaceAfter=6,
    )
    cell_style = ParagraphStyle(
        "TableCell",
        parent=styles["Normal"],
        fontName="Helvetica",
        fontSize=8,
        leading=10,
    )
    header_cell_style = ParagraphStyle(
        "HeaderCell",
        parent=styles["Normal"],
        fontName="Helvetica-Bold",
        fontSize=9,
        leading=11,
        textColor=colors.white,
    )

    story: List[Any] = []
    story.append(Paragraph(title, title_style))
    story.append(Spacer(1, 8))

    sheets_included: List[str] = []
    total_rows = 0

    def _df_to_table(df: pd.DataFrame, header_bg: str = "#2563eb") -> Table:
        table_data = []
        # Header row
        header_row = [Paragraph(str(col).replace("_", " ").title(), header_cell_style) for col in df.columns]
        table_data.append(header_row)

        for _, row in df.iterrows():
            row_cells = [Paragraph(str(val) if pd.notna(val) else "", cell_style) for val in row]
            table_data.append(row_cells)

        t = Table(table_data, repeatRows=1)
        t.setStyle(
            TableStyle(
                [
                    ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor(header_bg)),
                    ("ALIGN", (0, 0), (-1, -1), "LEFT"),
                    ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                    ("INNERGRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#cbd5e1")),
                    ("BOX", (0, 0), (-1, -1), 1.0, colors.HexColor("#94a3b8")),
                    ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#f8fafc")]),
                    ("TOPPADDING", (0, 0), (-1, -1), 4),
                    ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
                ]
            )
        )
        return t

    # 1. Room-wise Summary Section
    if room_df is not None and not room_df.empty:
        story.append(Paragraph("1. Room-Wise Attendance Summary", heading_style))
        story.append(_df_to_table(room_df, header_bg="#1e40af"))
        story.append(Spacer(1, 14))
        sheets_included.append("Room_Summary")
        total_rows += len(room_df)

    # 2. Branch-wise Summary Section
    if branch_df is not None and not branch_df.empty:
        story.append(Paragraph("2. Branch-Wise Attendance Summary", heading_style))
        story.append(_df_to_table(branch_df, header_bg="#0d9488"))
        story.append(Spacer(1, 14))
        sheets_included.append("Branch_Summary")
        total_rows += len(branch_df)

    # 3. Detailed Attendance Records (limited to first 250 rows to keep document performant)
    if detail_df is not None and not detail_df.empty:
        story.append(Paragraph(f"3. Detailed Attendance Records (Total: {len(detail_df)})", heading_style))
        # Select most important columns if available
        desired_cols = ["session_id", "usn", "student_name", "branch", "room_id", "status", "confidence"]
        display_cols = [c for c in desired_cols if c in detail_df.columns]
        if not display_cols:
            display_cols = list(detail_df.columns[:8])
        preview_df = detail_df[display_cols].head(250)
        story.append(_df_to_table(preview_df, header_bg="#475569"))
        sheets_included.append("Attendance_Details")
        total_rows += len(detail_df)

    if not sheets_included:
        story.append(Paragraph("No attendance data available to report.", heading_style))
        sheets_included.append("No_Data")

    doc.build(story)

    # Verify file existence and non-zero size
    if not target_path.exists() or target_path.stat().st_size == 0:
        raise RuntimeError(f"PDF export failed: file '{target_path}' was not generated.")

    file_size = target_path.stat().st_size
    return ExportResult(
        success=True,
        format="pdf",
        file_path=str(target_path),
        file_size_bytes=file_size,
        row_count=total_rows,
        summary_sheets=sheets_included,
        message=f"Successfully generated PDF report at '{target_path}'.",
        metadata={"sections": sheets_included},
    )


def export_tool(
    data: Union[pd.DataFrame, List[Dict[str, Any]], SummaryReport, Dict[str, Any]],
    format: str = "excel",
    output_path: Optional[Union[str, Path]] = None,
    overwrite: bool = True,
    title: str = "RollCall AI Attendance Report",
    **kwargs: Any,
) -> ExportResult:
    """
    Unified entry point for exporting attendance datasets.

    Args:
        data: Attendance records (DataFrame, List of dicts, or SummaryReport).
        format: 'excel' (or 'xlsx') or 'pdf'.
        output_path: Destination file path. If None, writes to 'data/exports/'.
        overwrite: Allow overwriting existing files (default: True).
        title: Title used in PDF report.

    Returns:
        ExportResult object with generated file details.
    """
    clean_fmt = str(format).strip().lower()

    if output_path is None:
        exports_dir = Path("data/exports")
        exports_dir.mkdir(parents=True, exist_ok=True)
        ext = ".xlsx" if clean_fmt in ("excel", "xlsx") else ".pdf"
        output_path = exports_dir / f"attendance_export_{os.getpid()}{ext}"

    if clean_fmt in ("excel", "xlsx"):
        return export_to_excel(data=data, output_path=output_path, overwrite=overwrite)
    elif clean_fmt == "pdf":
        return export_to_pdf(data=data, output_path=output_path, title=title, overwrite=overwrite)
    else:
        raise ValueError(f"Unsupported export format '{format}'. Allowed formats: 'excel', 'pdf'.")
