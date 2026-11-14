"""FastAPI routers package for RollCall AI."""

from app.routers.students import router as students_router
from app.routers.rooms import router as rooms_router
from app.routers.sessions import router as sessions_router
from app.routers.timetable import router as timetable_router
from app.routers.attendance import router as attendance_router
from app.routers.analytics import router as analytics_router
from app.routers.reports import router as reports_router
from app.routers.agent import router as agent_router
from app.routers.auth import router as auth_router
from app.routers.me import router as me_router
from app.routers.meta import router as meta_router
from app.routers.admin import router as admin_router
from app.routers.profile import router as profile_router
from app.routers.calendar import router as calendar_router
from app.routers.agent_stream import router as agent_stream_router

__all__ = [
    "students_router",
    "rooms_router",
    "sessions_router",
    "timetable_router",
    "attendance_router",
    "analytics_router",
    "reports_router",
    "agent_router",
    "agent_stream_router",
    "auth_router",
    "me_router",
    "meta_router",
    "admin_router",
    "profile_router",
    "calendar_router",
]

