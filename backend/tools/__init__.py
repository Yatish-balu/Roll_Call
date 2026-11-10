"""Tools package for RollCall AI."""

try:
    from tools.read_csv_tool import read_csv_tool, read_csv_as_records
except Exception:
    read_csv_tool = None  # type: ignore[assignment]
    read_csv_as_records = None  # type: ignore[assignment]

try:
    from tools.read_photo_tool import read_photo_tool, PhotoExtractionResult, PhotoRow
except Exception:
    read_photo_tool = None  # type: ignore[assignment]
    PhotoExtractionResult = None  # type: ignore[assignment]
    PhotoRow = None  # type: ignore[assignment]

try:
    from tools.validate_tool import validate_tool, validate_attendance, ValidationResult, ValidationError
except Exception:
    validate_tool = None  # type: ignore[assignment]
    validate_attendance = None  # type: ignore[assignment]
    ValidationResult = None  # type: ignore[assignment]
    ValidationError = None  # type: ignore[assignment]

try:
    from tools.summary_tool import summary_tool, generate_summary, SummaryReport
except Exception:
    summary_tool = None  # type: ignore[assignment]
    generate_summary = None  # type: ignore[assignment]
    SummaryReport = None  # type: ignore[assignment]

from tools.query_tool import query_tool, safe_sql_query, query_attendance, query_session_stats, query_absentees, query_students, QueryResult

try:
    from tools.export_tool import export_tool, export_to_excel, export_to_pdf, ExportResult
except Exception:
    export_tool = None  # type: ignore[assignment]
    export_to_excel = None  # type: ignore[assignment]
    export_to_pdf = None  # type: ignore[assignment]
    ExportResult = None  # type: ignore[assignment]

from tools.database import setup_database, inspect_database

__all__ = [
    "read_csv_tool",
    "read_csv_as_records",
    "read_photo_tool",
    "PhotoExtractionResult",
    "PhotoRow",
    "validate_tool",
    "validate_attendance",
    "ValidationResult",
    "ValidationError",
    "summary_tool",
    "generate_summary",
    "SummaryReport",
    "query_tool",
    "safe_sql_query",
    "query_attendance",
    "query_session_stats",
    "query_absentees",
    "query_students",
    "QueryResult",
    "export_tool",
    "export_to_excel",
    "export_to_pdf",
    "ExportResult",
    "setup_database",
    "inspect_database",
]
