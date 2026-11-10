"""FastAPI routers package for RollCall AI."""

from app.routers.students import router as students_router
from app.routers.rooms import router as rooms_router
from app.routers.sessions import router as sessions_router
from app.routers.attendance import router as attendance_router
from app.routers.analytics import router as analytics_router
from app.routers.reports import router as reports_router
from app.routers.agent import router as agent_router
from app.routers.auth import router as auth_router
from app.routers.me import router as me_router
from app.routers.meta import router as meta_router
from app.routers.admin import router as admin_router

__all__ = [
    "students_router",
    "rooms_router",
    "sessions_router",
    "attendance_router",
    "analytics_router",
    "reports_router",
    "agent_router",
    "auth_router",
    "me_router",
    "meta_router",
    "admin_router",
]

