"""SQLAlchemy 2.0 models preserving the exact RollCall schema and N1 RBAC extensions."""

from __future__ import annotations

import enum
from datetime import datetime, timezone
from typing import List, Optional
from uuid import uuid4

from sqlalchemy import (
    CheckConstraint,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    Integer,
    String,
    Float,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship
from app.db.base import Base


def _utcnow_iso() -> str:
    """Return current UTC time in fixed standard ISO 8601 format."""
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


class AttendanceStatus(str, enum.Enum):
    """The four canonical attendance states."""
    PRESENT = "PRESENT"
    ABSENT = "ABSENT"
    PENDING = "PENDING"
    UNREVIEWED = "UNREVIEWED"


class User(Base):
    __tablename__ = "users"

    user_id: Mapped[str] = mapped_column(String, primary_key=True)
    email: Mapped[str] = mapped_column(String, unique=True, nullable=False)
    role: Mapped[str] = mapped_column(String, nullable=False)
    hashed_password: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    is_active: Mapped[int] = mapped_column(Integer, nullable=False, default=1, server_default="1")
    created_at: Mapped[str] = mapped_column(String, nullable=False)

    teacher_subjects: Mapped[List["TeacherSubject"]] = relationship(
        "TeacherSubject", back_populates="user", cascade="all, delete-orphan", passive_deletes=True
    )
    sessions: Mapped[List["Session"]] = relationship(
        "Session",
        primaryjoin="Session.teacher_id == User.user_id",
        back_populates="teacher",
        passive_deletes=True,
    )

    pending_edits: Mapped[List["PendingEdit"]] = relationship(
        "PendingEdit", back_populates="user", cascade="all, delete-orphan", passive_deletes=True
    )
    audit_logs: Mapped[List["AuditLog"]] = relationship(
        "AuditLog", back_populates="actor"
    )
    auth_sessions: Mapped[List["AuthSession"]] = relationship(
        "AuthSession", back_populates="user", cascade="all, delete-orphan", passive_deletes=True
    )
    headed_departments: Mapped[List["Department"]] = relationship(
        "Department", back_populates="head_of_dept"
    )
    faculty_subjects_new: Mapped[List["FacultySubject"]] = relationship(
        "FacultySubject", back_populates="user", cascade="all, delete-orphan", passive_deletes=True
    )
    department_staff_records: Mapped[List["DepartmentStaff"]] = relationship(
        "DepartmentStaff", back_populates="user", cascade="all, delete-orphan", passive_deletes=True
    )
    coordinated_sessions: Mapped[List["Session"]] = relationship(
        "Session",
        primaryjoin="Session.coordinator_faculty_id == User.user_id",
        back_populates="coordinator",
    )

    def __repr__(self) -> str:
        return f"<User(user_id={self.user_id!r}, email={self.email!r}, role={self.role!r})>"


class TeacherSubject(Base):
    __tablename__ = "teacher_subjects"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[str] = mapped_column(
        String, ForeignKey("users.user_id", ondelete="CASCADE"), nullable=False
    )
    subject_code: Mapped[str] = mapped_column(String, nullable=False)

    user: Mapped["User"] = relationship("User", back_populates="teacher_subjects")

    __table_args__ = (
        UniqueConstraint("user_id", "subject_code", name="uq_teacher_subject"),
    )

    def __repr__(self) -> str:
        return f"<TeacherSubject(user_id={self.user_id!r}, subject_code={self.subject_code!r})>"


class AuditLog(Base):
    __tablename__ = "audit_log"

    log_id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    actor_id: Mapped[str] = mapped_column(
        String, ForeignKey("users.user_id", ondelete="RESTRICT"), nullable=False
    )
    action: Mapped[str] = mapped_column(String, nullable=False)
    session_id: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    usn: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    entity_type: Mapped[str] = mapped_column(String, nullable=False)
    entity_id: Mapped[str] = mapped_column(String, nullable=False)
    old_value: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    new_value: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    reason: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    timestamp: Mapped[str] = mapped_column(String, nullable=False)

    actor: Mapped["User"] = relationship("User", back_populates="audit_logs")

    __table_args__ = (
        Index("idx_audit_log_actor_ts", "actor_id", "timestamp"),
    )

    def __repr__(self) -> str:
        return f"<AuditLog(log_id={self.log_id}, actor_id={self.actor_id!r}, action={self.action!r})>"


class LoginAttempt(Base):
    __tablename__ = "login_attempts"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[Optional[str]] = mapped_column(
        String, ForeignKey("users.user_id", ondelete="SET NULL"), nullable=True
    )
    ip_address: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    success: Mapped[int] = mapped_column(Integer, nullable=False)
    timestamp: Mapped[str] = mapped_column(String, nullable=False)

    __table_args__ = (
        Index("idx_login_attempts_user_ts", "user_id", "timestamp"),
    )

    def __repr__(self) -> str:
        return f"<LoginAttempt(id={self.id}, user_id={self.user_id!r}, success={self.success})>"


class PendingEdit(Base):
    __tablename__ = "pending_edits"

    edit_id: Mapped[str] = mapped_column(String, primary_key=True)
    user_id: Mapped[str] = mapped_column(
        String, ForeignKey("users.user_id", ondelete="CASCADE"), nullable=False
    )
    session_id: Mapped[str] = mapped_column(String, nullable=False)
    attendance_id: Mapped[Optional[str]] = mapped_column(
        String, ForeignKey("attendance.attendance_id", ondelete="CASCADE"), nullable=True
    )
    usn: Mapped[str] = mapped_column(String, nullable=False)
    old_status: Mapped[str] = mapped_column(String, nullable=False)
    new_status: Mapped[str] = mapped_column(String, nullable=False)
    created_at: Mapped[str] = mapped_column(String, nullable=False)
    expires_at: Mapped[str] = mapped_column(String, nullable=False)
    consumed: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")

    user: Mapped["User"] = relationship("User", back_populates="pending_edits")

    __table_args__ = (
        Index("idx_pending_edits_user_expiry", "user_id", "expires_at", "consumed"),
    )

    def __repr__(self) -> str:
        return f"<PendingEdit(edit_id={self.edit_id!r}, user_id={self.user_id!r}, consumed={self.consumed})>"


class AuthSession(Base):
    __tablename__ = "auth_sessions"

    session_id: Mapped[str] = mapped_column(String, primary_key=True)
    user_id: Mapped[str] = mapped_column(
        String, ForeignKey("users.user_id", ondelete="CASCADE"), nullable=False
    )
    created_at: Mapped[str] = mapped_column(String, nullable=False)
    absolute_expiry: Mapped[str] = mapped_column(String, nullable=False)
    revoked_at: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    remember_me: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    user_agent: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    ip_address: Mapped[Optional[str]] = mapped_column(String, nullable=True)

    user: Mapped["User"] = relationship("User", back_populates="auth_sessions")
    refresh_tokens: Mapped[List["AuthRefreshToken"]] = relationship(
        "AuthRefreshToken", back_populates="session", cascade="all, delete-orphan", passive_deletes=True
    )

    __table_args__ = (
        Index("idx_auth_sessions_user_id", "user_id", "revoked_at"),
        Index("idx_auth_sessions_expiry", "absolute_expiry"),
    )

    def __repr__(self) -> str:
        return f"<AuthSession(session_id={self.session_id!r}, user_id={self.user_id!r}, revoked={self.revoked_at is not None})>"


class AuthRefreshToken(Base):
    __tablename__ = "auth_refresh_tokens"

    token_id: Mapped[str] = mapped_column(String, primary_key=True)
    session_id: Mapped[str] = mapped_column(
        String, ForeignKey("auth_sessions.session_id", ondelete="CASCADE"), nullable=False
    )
    token_hash: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    rotation_seq: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    created_at: Mapped[str] = mapped_column(String, nullable=False)
    consumed_at: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    revoked_at: Mapped[Optional[str]] = mapped_column(String, nullable=True)

    session: Mapped["AuthSession"] = relationship("AuthSession", back_populates="refresh_tokens")

    __table_args__ = (
        Index("idx_auth_refresh_tokens_hash", "token_hash", unique=True),
        Index("idx_auth_refresh_tokens_session", "session_id"),
    )

    def __repr__(self) -> str:
        return f"<AuthRefreshToken(token_id={self.token_id!r}, seq={self.rotation_seq}, consumed={self.consumed_at is not None})>"


class Student(Base):
    __tablename__ = "students"

    usn: Mapped[str] = mapped_column(String, primary_key=True)
    name: Mapped[str] = mapped_column(String, nullable=False)
    branch: Mapped[str] = mapped_column(String, nullable=False)
    dept_id: Mapped[Optional[str]] = mapped_column(
        String, ForeignKey("departments.dept_id", ondelete="RESTRICT"), nullable=True
    )
    semester_id: Mapped[Optional[str]] = mapped_column(
        String, ForeignKey("semesters.semester_id", ondelete="RESTRICT"), nullable=True
    )
    section_id: Mapped[Optional[str]] = mapped_column(
        String, ForeignKey("sections.section_id", ondelete="RESTRICT"), nullable=True
    )
    roll_no: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    batch_id: Mapped[Optional[str]] = mapped_column(
        String, ForeignKey("batches.batch_id", ondelete="RESTRICT"), nullable=True
    )

    # Relationship: cascades delete-orphan to match ON DELETE CASCADE
    attendance_records: Mapped[List["Attendance"]] = relationship(
        "Attendance", back_populates="student", cascade="all, delete-orphan", passive_deletes=True
    )
    dept: Mapped[Optional["Department"]] = relationship("Department", back_populates="students")
    semester: Mapped[Optional["Semester"]] = relationship("Semester", back_populates="students")
    section: Mapped[Optional["Section"]] = relationship("Section", back_populates="students")
    batch: Mapped[Optional["Batch"]] = relationship("Batch", back_populates="students")

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
    created_at: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    teacher_id: Mapped[Optional[str]] = mapped_column(
        String, ForeignKey("users.user_id", ondelete="RESTRICT"), nullable=True
    )
    subject_code: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    lifecycle_status: Mapped[str] = mapped_column(
        String, nullable=False, default="SCHEDULED"
    )  # SCHEDULED | IN_PROGRESS | COMPLETED (derived from allocations)
    coordinator_faculty_id: Mapped[Optional[str]] = mapped_column(
        String, ForeignKey("users.user_id", ondelete="RESTRICT"), nullable=True
    )

    # Relationship: teacher user
    teacher: Mapped[Optional["User"]] = relationship("User", foreign_keys=[teacher_id])
    coordinator: Mapped[Optional["User"]] = relationship("User", foreign_keys=[coordinator_faculty_id])

    # Relationship: cascades delete-orphan to match ON DELETE CASCADE
    attendance_records: Mapped[List["Attendance"]] = relationship(
        "Attendance", back_populates="session", cascade="all, delete-orphan", passive_deletes=True
    )

    allocations: Mapped[List["SessionAllocation"]] = relationship(
        "SessionAllocation", back_populates="session", cascade="all, delete-orphan", passive_deletes=True
    )

    __table_args__ = (
        Index("idx_sessions_teacher_created", "teacher_id", "created_at"),
        Index("idx_sessions_lifecycle", "lifecycle_status"),
    )

    def __repr__(self) -> str:
        return f"<Session(session_id={self.session_id!r}, date={self.date!r}, subject={self.subject!r})>"


class Attendance(Base):
    __tablename__ = "attendance"

    attendance_id: Mapped[str] = mapped_column(
        String, primary_key=True, default=lambda: str(uuid4())
    )
    session_id: Mapped[str] = mapped_column(
        String, ForeignKey("sessions.session_id", ondelete="CASCADE"), nullable=False
    )
    allocation_id: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    usn: Mapped[str] = mapped_column(
        String, ForeignKey("students.usn", ondelete="CASCADE"), nullable=False
    )
    room_id: Mapped[str] = mapped_column(
        String,
        ForeignKey("rooms.room_id", ondelete="RESTRICT"),
        nullable=False,
    )
    status: Mapped[str] = mapped_column(String, nullable=False)
    source: Mapped[str] = mapped_column(String, nullable=False)
    confidence: Mapped[float] = mapped_column(Float, nullable=False, default=1.0, server_default="1.0")
    recorded_at: Mapped[str] = mapped_column(String, nullable=False, default=_utcnow_iso)

    # Relationships
    session: Mapped["Session"] = relationship("Session", back_populates="attendance_records")
    student: Mapped["Student"] = relationship("Student", back_populates="attendance_records")
    room: Mapped["Room"] = relationship("Room", back_populates="attendance_records")
    allocation: Mapped[Optional["SessionAllocation"]] = relationship(
        "SessionAllocation",
        primaryjoin="SessionAllocation.allocation_id == Attendance.allocation_id",
        foreign_keys="Attendance.allocation_id",
        back_populates="attendance_records",
    )

    __table_args__ = (
        CheckConstraint(
            "status IN ('PRESENT', 'ABSENT', 'PENDING', 'UNREVIEWED')",
            name="check_attendance_status",
        ),
        Index("idx_attendance_session", "session_id"),
        Index("idx_attendance_usn", "usn"),
        Index("idx_attendance_room", "room_id"),
        Index("idx_attendance_allocation", "allocation_id"),
    )

    def __repr__(self) -> str:
        return (
            f"<Attendance(session={self.session_id!r}, usn={self.usn!r}, "
            f"room={self.room_id!r}, status={self.status!r}, confidence={self.confidence})>"
        )


class College(Base):
    """College / institution top-level container."""

    __tablename__ = "colleges"

    college_id: Mapped[str] = mapped_column(String, primary_key=True)
    name: Mapped[str] = mapped_column(String, nullable=False)
    code: Mapped[str] = mapped_column(String, nullable=False, unique=True)
    address: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    created_at: Mapped[str] = mapped_column(String, nullable=False, default=_utcnow_iso)

    departments: Mapped[List["Department"]] = relationship(
        "Department", back_populates="college", cascade="all, delete-orphan", passive_deletes=True
    )
    academic_years: Mapped[List["AcademicYear"]] = relationship(
        "AcademicYear", back_populates="college", cascade="all, delete-orphan", passive_deletes=True
    )

    def __repr__(self) -> str:
        return f"<College(college_id={self.college_id!r}, name={self.name!r})>"


class Department(Base):
    """Academic department within a college."""

    __tablename__ = "departments"

    dept_id: Mapped[str] = mapped_column(String, primary_key=True)
    college_id: Mapped[str] = mapped_column(
        String, ForeignKey("colleges.college_id", ondelete="CASCADE"), nullable=False
    )
    name: Mapped[str] = mapped_column(String, nullable=False)
    code: Mapped[str] = mapped_column(String, nullable=False)
    head_of_dept_id: Mapped[Optional[str]] = mapped_column(
        String, ForeignKey("users.user_id", ondelete="RESTRICT"), nullable=True
    )
    created_at: Mapped[str] = mapped_column(String, nullable=False, default=_utcnow_iso)

    college: Mapped["College"] = relationship("College", back_populates="departments")
    head_of_dept: Mapped[Optional["User"]] = relationship(
        "User", foreign_keys=[head_of_dept_id], back_populates="headed_departments"
    )
    students: Mapped[List["Student"]] = relationship(
        "Student", back_populates="dept", cascade="all, delete-orphan", passive_deletes=True
    )
    sections: Mapped[List["Section"]] = relationship(
        "Section", back_populates="dept", cascade="all, delete-orphan", passive_deletes=True
    )
    batches: Mapped[List["Batch"]] = relationship(
        "Batch", back_populates="dept", cascade="all, delete-orphan", passive_deletes=True
    )
    subjects: Mapped[List["Subject"]] = relationship(
        "Subject", back_populates="dept", cascade="all, delete-orphan", passive_deletes=True
    )
    faculty_subjects: Mapped[List["FacultySubject"]] = relationship(
        "FacultySubject", back_populates="dept", cascade="all, delete-orphan", passive_deletes=True
    )
    staff_records: Mapped[List["DepartmentStaff"]] = relationship(
        "DepartmentStaff", back_populates="dept", cascade="all, delete-orphan", passive_deletes=True
    )
    timetables: Mapped[List["Timetable"]] = relationship(
        "Timetable",
        primaryjoin="Timetable.dept_id == Department.dept_id",
        back_populates="dept",
        cascade="all, delete-orphan", passive_deletes=True
    )

    __table_args__ = (
        UniqueConstraint("college_id", "code", name="uq_department_college_code"),
        Index("idx_departments_college_id", "college_id"),
    )

    def __repr__(self) -> str:
        return f"<Department(dept_id={self.dept_id!r}, name={self.name!r})>"


class AcademicYear(Base):
    """Academic year within a college."""

    __tablename__ = "academic_years"

    year_id: Mapped[str] = mapped_column(String, primary_key=True)
    college_id: Mapped[str] = mapped_column(
        String, ForeignKey("colleges.college_id", ondelete="CASCADE"), nullable=False
    )
    year_label: Mapped[str] = mapped_column(String, nullable=False)  # e.g. "2025-26"
    start_date: Mapped[str] = mapped_column(String, nullable=False)
    end_date: Mapped[str] = mapped_column(String, nullable=False)
    is_active: Mapped[int] = mapped_column(Integer, nullable=False, default=1, server_default="1")

    college: Mapped["College"] = relationship("College", back_populates="academic_years")
    semesters: Mapped[List["Semester"]] = relationship(
        "Semester", back_populates="year", cascade="all, delete-orphan", passive_deletes=True
    )
    timetables: Mapped[List["Timetable"]] = relationship(
        "Timetable",
        primaryjoin="Timetable.year_id == AcademicYear.year_id",
        back_populates="year",
        cascade="all, delete-orphan", passive_deletes=True
    )

    __table_args__ = (
        UniqueConstraint("college_id", "year_label", name="uq_academic_year_college_label"),
        Index("idx_academic_years_college_id", "college_id"),
    )

    def __repr__(self) -> str:
        return f"<AcademicYear(year_id={self.year_id!r}, label={self.year_label!r})>"


class Semester(Base):
    """Semester within an academic year."""

    __tablename__ = "semesters"

    semester_id: Mapped[str] = mapped_column(String, primary_key=True)
    year_id: Mapped[str] = mapped_column(
        String, ForeignKey("academic_years.year_id", ondelete="CASCADE"), nullable=False
    )
    semester_label: Mapped[str] = mapped_column(String, nullable=False)  # e.g. "Fall", "Spring"
    semester_number: Mapped[int] = mapped_column(Integer, nullable=False)
    start_date: Mapped[str] = mapped_column(String, nullable=False)
    end_date: Mapped[str] = mapped_column(String, nullable=False)
    is_active: Mapped[int] = mapped_column(Integer, nullable=False, default=1, server_default="1")

    year: Mapped["AcademicYear"] = relationship("AcademicYear", back_populates="semesters")
    students: Mapped[List["Student"]] = relationship(
        "Student", back_populates="semester", cascade="all, delete-orphan", passive_deletes=True
    )
    sections: Mapped[List["Section"]] = relationship(
        "Section", back_populates="semester", cascade="all, delete-orphan", passive_deletes=True
    )
    batches: Mapped[List["Batch"]] = relationship(
        "Batch", back_populates="semester", cascade="all, delete-orphan", passive_deletes=True
    )
    timetables: Mapped[List["Timetable"]] = relationship(
        "Timetable",
        primaryjoin="Timetable.semester_id == Semester.semester_id",
        back_populates="semester",
        cascade="all, delete-orphan", passive_deletes=True
    )

    __table_args__ = (
        UniqueConstraint("year_id", "semester_number", name="uq_semester_year_number"),
        Index("idx_semesters_year_id", "year_id"),
    )

    def __repr__(self) -> str:
        return f"<Semester(semester_id={self.semester_id!r}, label={self.semester_label!r})>"


class Section(Base):
    """Class section within a department and semester."""

    __tablename__ = "sections"

    section_id: Mapped[str] = mapped_column(String, primary_key=True)
    dept_id: Mapped[str] = mapped_column(
        String, ForeignKey("departments.dept_id", ondelete="CASCADE"), nullable=False
    )
    semester_id: Mapped[str] = mapped_column(
        String, ForeignKey("semesters.semester_id", ondelete="CASCADE"), nullable=False
    )
    section_label: Mapped[str] = mapped_column(String, nullable=False)  # e.g. "A", "B"
    batch_size: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)

    dept: Mapped["Department"] = relationship("Department", back_populates="sections")
    semester: Mapped["Semester"] = relationship("Semester", back_populates="sections")
    students: Mapped[List["Student"]] = relationship(
        "Student", back_populates="section", cascade="all, delete-orphan", passive_deletes=True
    )
    batches: Mapped[List["Batch"]] = relationship(
        "Batch", back_populates="section", cascade="all, delete-orphan", passive_deletes=True
    )
    timetables: Mapped[List["Timetable"]] = relationship(
        "Timetable",
        primaryjoin="Timetable.section_id == Section.section_id",
        back_populates="section",
        cascade="all, delete-orphan", passive_deletes=True
    )

    __table_args__ = (
        UniqueConstraint("dept_id", "semester_id", "section_label", name="uq_section_dept_semester_label"),
        Index("idx_sections_dept_id", "dept_id"),
        Index("idx_sections_semester_id", "semester_id"),
    )

    def __repr__(self) -> str:
        return f"<Section(section_id={self.section_id!r}, label={self.section_label!r})>"


class Batch(Base):
    """Student batch within a department, semester, and section."""

    __tablename__ = "batches"

    batch_id: Mapped[str] = mapped_column(String, primary_key=True)
    dept_id: Mapped[str] = mapped_column(
        String, ForeignKey("departments.dept_id", ondelete="CASCADE"), nullable=False
    )
    semester_id: Mapped[str] = mapped_column(
        String, ForeignKey("semesters.semester_id", ondelete="CASCADE"), nullable=False
    )
    section_id: Mapped[str] = mapped_column(
        String, ForeignKey("sections.section_id", ondelete="CASCADE"), nullable=False
    )
    batch_label: Mapped[str] = mapped_column(String, nullable=False)  # e.g. "A1", "A2"
    batch_type: Mapped[str] = mapped_column(String, nullable=False)  # "theory" | "lab"

    dept: Mapped["Department"] = relationship("Department", back_populates="batches")
    semester: Mapped["Semester"] = relationship("Semester", back_populates="batches")
    section: Mapped["Section"] = relationship("Section", back_populates="batches")
    students: Mapped[List["Student"]] = relationship(
        "Student", back_populates="batch", cascade="all, delete-orphan", passive_deletes=True
    )

    __table_args__ = (
        UniqueConstraint("dept_id", "semester_id", "section_id", "batch_label", name="uq_batch_dept_semester_section_label"),
        Index("idx_batches_dept_id", "dept_id"),
        Index("idx_batches_section_id", "section_id"),
    )

    def __repr__(self) -> str:
        return f"<Batch(batch_id={self.batch_id!r}, label={self.batch_label!r})>"


class Subject(Base):
    """Academic subject offered by a department."""

    __tablename__ = "subjects"

    subject_code: Mapped[str] = mapped_column(String, primary_key=True)  # globally unique, e.g. "CS-301"
    dept_id: Mapped[str] = mapped_column(
        String, ForeignKey("departments.dept_id", ondelete="RESTRICT"), nullable=False
    )
    name: Mapped[str] = mapped_column(String, nullable=False)
    credits: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    hours_per_week: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    subject_type: Mapped[str] = mapped_column(String, nullable=False)  # "theory" | "lab"

    dept: Mapped["Department"] = relationship("Department", back_populates="subjects")
    faculty_assignments: Mapped[List["FacultySubject"]] = relationship(
        "FacultySubject", back_populates="subject", cascade="all, delete-orphan", passive_deletes=True
    )

    __table_args__ = (
        Index("idx_subjects_dept_id", "dept_id"),
    )

    def __repr__(self) -> str:
        return f"<Subject(subject_code={self.subject_code!r}, name={self.name!r})>"


class FacultySubject(Base):
    """Faculty-subject-department assignment (extends teacher_subjects with dept scoping)."""

    __tablename__ = "faculty_subjects"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[str] = mapped_column(
        String, ForeignKey("users.user_id", ondelete="CASCADE"), nullable=False
    )
    subject_code: Mapped[str] = mapped_column(
        String, ForeignKey("subjects.subject_code", ondelete="CASCADE"), nullable=False
    )
    dept_id: Mapped[str] = mapped_column(
        String, ForeignKey("departments.dept_id", ondelete="CASCADE"), nullable=False
    )

    user: Mapped["User"] = relationship("User", back_populates="faculty_subjects_new")
    subject: Mapped["Subject"] = relationship("Subject", back_populates="faculty_assignments")
    dept: Mapped["Department"] = relationship("Department", back_populates="faculty_subjects")

    __table_args__ = (
        UniqueConstraint("user_id", "subject_code", "dept_id", name="uq_faculty_subject_dept"),
        Index("idx_faculty_subjects_user_id", "user_id"),
        Index("idx_faculty_subjects_subject_code", "subject_code"),
    )

    def __repr__(self) -> str:
        return f"<FacultySubject(user_id={self.user_id!r}, subject_code={self.subject_code!r})>"


class DepartmentStaff(Base):
    """Staff membership linking users to departments with a role_in_dept."""

    __tablename__ = "department_staff"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[str] = mapped_column(
        String, ForeignKey("users.user_id", ondelete="CASCADE"), nullable=False
    )
    dept_id: Mapped[str] = mapped_column(
        String, ForeignKey("departments.dept_id", ondelete="CASCADE"), nullable=False
    )
    role_in_dept: Mapped[str] = mapped_column(String, nullable=False)  # "COORDINATOR" | "FACULTY" | "VIEWER"

    user: Mapped["User"] = relationship("User", back_populates="department_staff_records")
    dept: Mapped["Department"] = relationship("Department", back_populates="staff_records")

    __table_args__ = (
        UniqueConstraint("user_id", "dept_id", name="uq_department_staff"),
        Index("idx_department_staff_user_id", "user_id"),
        Index("idx_department_staff_dept_id", "dept_id"),
    )

    def __repr__(self) -> str:
        return f"<DepartmentStaff(user_id={self.user_id!r}, dept_id={self.dept_id!r})>"


class Timetable(Base):
    """Container for a department's timetable for a semester/section/year."""

    __tablename__ = "timetables"

    timetable_id: Mapped[str] = mapped_column(String, primary_key=True)
    dept_id: Mapped[str] = mapped_column(
        String, ForeignKey("departments.dept_id", ondelete="CASCADE"), nullable=False
    )
    semester_id: Mapped[str] = mapped_column(
        String, ForeignKey("semesters.semester_id", ondelete="CASCADE"), nullable=False
    )
    section_id: Mapped[str] = mapped_column(
        String, ForeignKey("sections.section_id", ondelete="CASCADE"), nullable=False
    )
    year_id: Mapped[str] = mapped_column(
        String, ForeignKey("academic_years.year_id", ondelete="CASCADE"), nullable=False
    )
    effective_from: Mapped[str] = mapped_column(String, nullable=False)
    effective_to: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    revision_number: Mapped[int] = mapped_column(Integer, nullable=False, default=1, server_default="1")
    is_active: Mapped[int] = mapped_column(Integer, nullable=False, default=1, server_default="1")
    created_at: Mapped[str] = mapped_column(String, nullable=False, default=_utcnow_iso)

    dept: Mapped["Department"] = relationship(
        "Department",
        primaryjoin="Department.dept_id == Timetable.dept_id",
        back_populates="timetables"
    )
    semester: Mapped["Semester"] = relationship(
        "Semester",
        primaryjoin="Semester.semester_id == Timetable.semester_id",
        back_populates="timetables"
    )
    section: Mapped["Section"] = relationship(
        "Section",
        primaryjoin="Section.section_id == Timetable.section_id",
        back_populates="timetables"
    )
    year: Mapped["AcademicYear"] = relationship(
        "AcademicYear",
        primaryjoin="AcademicYear.year_id == Timetable.year_id",
        back_populates="timetables"
    )
    entries: Mapped[List["TimetableEntry"]] = relationship(
        "TimetableEntry", back_populates="timetable", cascade="all, delete-orphan", passive_deletes=True
    )

    __table_args__ = (
        UniqueConstraint(
            "dept_id", "semester_id", "section_id", "year_id", name="uq_timetable_dept_semester_section_year"
        ),
        Index("idx_timetables_dept_id", "dept_id"),
        Index("idx_timetables_is_active", "is_active"),
    )

    def __repr__(self) -> str:
        return f"<Timetable(timetable_id={self.timetable_id!r}, dept_id={self.dept_id!r})>"


class TimetableEntry(Base):
    """Recurring weekly timetable slot within a timetable."""

    __tablename__ = "timetable_entries"

    entry_id: Mapped[str] = mapped_column(String, primary_key=True)
    timetable_id: Mapped[str] = mapped_column(
        String, ForeignKey("timetables.timetable_id", ondelete="CASCADE"), nullable=False
    )
    day_of_week: Mapped[str] = mapped_column(String, nullable=False)  # Mon-Sat
    period_number: Mapped[int] = mapped_column(Integer, nullable=False)
    start_time: Mapped[str] = mapped_column(String, nullable=False)  # HH:MM
    end_time: Mapped[str] = mapped_column(String, nullable=False)  # HH:MM
    subject_code: Mapped[str] = mapped_column(
        String, ForeignKey("subjects.subject_code", ondelete="RESTRICT"), nullable=False
    )
    room_id: Mapped[str] = mapped_column(
        String, ForeignKey("rooms.room_id", ondelete="RESTRICT"), nullable=False
    )
    faculty_id: Mapped[Optional[str]] = mapped_column(
        String, ForeignKey("users.user_id", ondelete="RESTRICT"), nullable=True
    )
    batch_id: Mapped[Optional[str]] = mapped_column(
        String, ForeignKey("batches.batch_id", ondelete="RESTRICT"), nullable=True
    )
    duration_minutes: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)

    timetable: Mapped["Timetable"] = relationship("Timetable", back_populates="entries")
    subject: Mapped["Subject"] = relationship("Subject")
    room: Mapped["Room"] = relationship("Room")
    faculty: Mapped[Optional["User"]] = relationship(
        "User", primaryjoin="User.user_id == TimetableEntry.faculty_id"
    )
    batch: Mapped[Optional["Batch"]] = relationship(
        "Batch", primaryjoin="Batch.batch_id == TimetableEntry.batch_id"
    )
    allocations: Mapped[List["SessionAllocation"]] = relationship(
        "SessionAllocation", back_populates="timetable_entry", cascade="all, delete-orphan", passive_deletes=True
    )

    __table_args__ = (
        Index("idx_timetable_entries_timetable_id", "timetable_id"),
        Index("idx_timetable_entries_day_of_week", "day_of_week"),
        Index("idx_timetable_entries_room_id", "room_id"),
        Index("idx_timetable_entries_faculty_id", "faculty_id"),
        Index("idx_timetable_entries_batch_id", "batch_id"),
    )

    def __repr__(self) -> str:
        return f"<TimetableEntry(entry_id={self.entry_id!r}, day={self.day_of_week!r})>"


class SessionAllocation(Base):
    """Actualized session instance derived from a timetable entry on a specific date."""

    __tablename__ = "session_allocations"

    allocation_id: Mapped[str] = mapped_column(String, primary_key=True)
    session_id: Mapped[str] = mapped_column(
        String, ForeignKey("sessions.session_id", ondelete="CASCADE"), nullable=False
    )
    timetable_entry_id: Mapped[Optional[str]] = mapped_column(
        String, ForeignKey("timetable_entries.entry_id", ondelete="SET NULL"), nullable=True
    )
    allocation_date: Mapped[str] = mapped_column(String, nullable=False)
    room_id: Mapped[str] = mapped_column(
        String, ForeignKey("rooms.room_id", ondelete="RESTRICT"), nullable=False
    )
    start_time: Mapped[str] = mapped_column(String, nullable=False)
    end_time: Mapped[str] = mapped_column(String, nullable=False)
    batch_id: Mapped[Optional[str]] = mapped_column(
        String, ForeignKey("batches.batch_id", ondelete="RESTRICT"), nullable=True
    )
    faculty_id: Mapped[Optional[str]] = mapped_column(
        String, ForeignKey("users.user_id", ondelete="RESTRICT"), nullable=True
    )
    lifecycle_status: Mapped[str] = mapped_column(
        String, nullable=False, default="SCHEDULED"
    )  # SCHEDULED | IN_PROGRESS | COMPLETED
    created_at: Mapped[str] = mapped_column(String, nullable=False, default=_utcnow_iso)

    session: Mapped["Session"] = relationship("Session", back_populates="allocations")
    timetable_entry: Mapped[Optional["TimetableEntry"]] = relationship(
        "TimetableEntry", back_populates="allocations"
    )
    room: Mapped["Room"] = relationship("Room", primaryjoin="Room.room_id == SessionAllocation.room_id")
    batch: Mapped[Optional["Batch"]] = relationship(
        "Batch", primaryjoin="Batch.batch_id == SessionAllocation.batch_id"
    )
    faculty: Mapped[Optional["User"]] = relationship(
        "User", primaryjoin="User.user_id == SessionAllocation.faculty_id"
    )
    attendance_records: Mapped[List["Attendance"]] = relationship(
        "Attendance",
        primaryjoin="Attendance.allocation_id == SessionAllocation.allocation_id",
        foreign_keys="Attendance.allocation_id",
        back_populates="allocation",
    )

    __table_args__ = (
        Index("idx_session_allocations_session_id", "session_id"),
        Index("idx_session_allocations_allocation_date", "allocation_date"),
        Index("idx_session_allocations_room_id", "room_id"),
        Index("idx_session_allocations_faculty_id", "faculty_id"),
        Index("idx_session_allocations_batch_id", "batch_id"),
        Index("idx_session_allocations_lifecycle", "lifecycle_status"),
    )

    def __repr__(self) -> str:
        return f"<SessionAllocation(allocation_id={self.allocation_id!r}, date={self.allocation_date!r})>"
