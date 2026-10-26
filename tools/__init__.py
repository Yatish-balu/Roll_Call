"""Tools package for RollCall AI."""

from tools.read_csv_tool import read_csv_tool, read_csv_as_records
from tools.read_photo_tool import PhotoExtractionResult, PhotoRow
from tools.validate_tool import validate_tool, validate_attendance, ValidationResult, ValidationError
from tools.summary_tool import summary_tool, generate_summary, SummaryReport
from tools.query_tool import query_tool, safe_sql_query, query_attendance, query_session_stats, query_absentees, query_students, QueryResult
from tools.export_tool import export_tool, export_to_excel, export_to_pdf, ExportResult
from tools.database import setup_database, inspect_database

# AUDIT FIX (L-6): `read_photo_tool` is both the module name and a function name.
# Importing the function into this package previously shadowed the submodule, so
# `import tools.read_photo_tool` yielded the function instead of the module. The
# function re-export is intentionally omitted — import it from the submodule:
#     from tools.read_photo_tool import read_photo_tool
import tools.read_photo_tool as _read_photo_tool_module

__all__ = [
    "read_csv_tool",
    "read_csv_as_records",
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
