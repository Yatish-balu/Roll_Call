"""SQLAlchemy 2.0 models preserving the exact RollCall schema."""

from __future__ import annotations

import enum
from typing import List
from sqlalchemy import (
    CheckConstraint,
    ForeignKey,
    Index,
    String,
    Float,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship
from app.db.base import Base


class AttendanceStatus(str, enum.Enum):
    """The four canonical attendance states."""
    PRESENT = "PRESENT"
    ABSENT = "ABSENT"
    PENDING = "PENDING"
    UNREVIEWED = "UNREVIEWED"


class Student(Base):
    __tablename__ = "students"

    usn: Mapped[str] = mapped_column(String, primary_key=True)
    name: Mapped[str] = mapped_column(String, nullable=False)
    branch: Mapped[str] = mapped_column(String, nullable=False)

    # Relationship: cascades delete-orphan to match ON DELETE CASCADE
    attendance_records: Mapped[List["Attendance"]] = relationship(
        "Attendance", back_populates="student", cascade="all, delete-orphan", passive_deletes=True
    )

    def __repr__(self) -> str:
        return f"<Student(usn={self.usn!r}, name={self.name!r}, branch={self.branch!r})>"


class Room(Base):
    __tablename__ = "rooms"

    room_id: Mapped[str] = mapped_column(String, primary_key=True)
    name: Mapped[str] = mapped_column(String, nullable=False)

    # Relationship: NO delete cascade, preserving DB-level ON DELETE RESTRICT
    attendance_records: Mapped[List["Attendance"]] = relationship(
        "Attendance", back_populates="room"
    )

    def __repr__(self) -> str:
        return f"<Room(room_id={self.room_id!r}, name={self.name!r})>"


class Session(Base):
    __tablename__ = "sessions"

    session_id: Mapped[str] = mapped_column(String, primary_key=True)
    date: Mapped[str] = mapped_column(String, nullable=False)  # Preserved as ISO string YYYY-MM-DD
    subject: Mapped[str] = mapped_column(String, nullable=False)

    # Relationship: cascades delete-orphan to match ON DELETE CASCADE
    attendance_records: Mapped[List["Attendance"]] = relationship(
        "Attendance", back_populates="session", cascade="all, delete-orphan", passive_deletes=True
    )

    def __repr__(self) -> str:
        return f"<Session(session_id={self.session_id!r}, date={self.date!r}, subject={self.subject!r})>"


class Attendance(Base):
    __tablename__ = "attendance"

    session_id: Mapped[str] = mapped_column(
        String,
        ForeignKey("sessions.session_id", ondelete="CASCADE"),
        primary_key=True,
    )
    usn: Mapped[str] = mapped_column(
        String,
        ForeignKey("students.usn", ondelete="CASCADE"),
        primary_key=True,
    )
    room_id: Mapped[str] = mapped_column(
        String,
        ForeignKey("rooms.room_id", ondelete="RESTRICT"),
        nullable=False,
    )
    status: Mapped[str] = mapped_column(String, nullable=False)
    source: Mapped[str] = mapped_column(String, nullable=False)
    confidence: Mapped[float] = mapped_column(Float, nullable=False, default=1.0, server_default="1.0")

    # Relationships
    session: Mapped["Session"] = relationship("Session", back_populates="attendance_records")
    student: Mapped["Student"] = relationship("Student", back_populates="attendance_records")
    room: Mapped["Room"] = relationship("Room", back_populates="attendance_records")

    __table_args__ = (
        CheckConstraint(
            "status IN ('PRESENT', 'ABSENT', 'PENDING', 'UNREVIEWED')",
            name="check_attendance_status",
        ),
        Index("idx_attendance_session", "session_id"),
        Index("idx_attendance_usn", "usn"),
        Index("idx_attendance_room", "room_id"),
    )

    def __repr__(self) -> str:
        return (
            f"<Attendance(session={self.session_id!r}, usn={self.usn!r}, "
            f"room={self.room_id!r}, status={self.status!r}, confidence={self.confidence})>"
        )

