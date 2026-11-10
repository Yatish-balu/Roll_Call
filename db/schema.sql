-- db/schema.sql
-- Schema definition for RollCall AI on Supabase PostgreSQL

CREATE TABLE IF NOT EXISTS students (
    usn VARCHAR(50) PRIMARY KEY,
    name VARCHAR(255) NOT NULL,
    branch VARCHAR(100) NOT NULL
);

CREATE TABLE IF NOT EXISTS rooms (
    room_id VARCHAR(50) PRIMARY KEY,
    name VARCHAR(255) NOT NULL
);

CREATE TABLE IF NOT EXISTS sessions (
    session_id VARCHAR(100) PRIMARY KEY,
    date VARCHAR(50) NOT NULL,
    subject VARCHAR(255) NOT NULL
);

CREATE TABLE IF NOT EXISTS attendance (
    session_id VARCHAR(100) NOT NULL,
    usn VARCHAR(50) NOT NULL,
    room_id VARCHAR(50) NOT NULL,
    status VARCHAR(20) NOT NULL CHECK (status IN ('PRESENT', 'ABSENT', 'PENDING', 'UNREVIEWED', 'P', 'A')),
    source VARCHAR(100) NOT NULL,
    confidence DOUBLE PRECISION NOT NULL DEFAULT 1.0,
    PRIMARY KEY (session_id, usn),
    CONSTRAINT fk_attendance_session FOREIGN KEY (session_id) REFERENCES sessions(session_id) ON DELETE CASCADE,
    CONSTRAINT fk_attendance_student FOREIGN KEY (usn) REFERENCES students(usn) ON DELETE CASCADE,
    CONSTRAINT fk_attendance_room FOREIGN KEY (room_id) REFERENCES rooms(room_id) ON DELETE RESTRICT
);

-- Indexes on session_id, room_id, usn
CREATE INDEX IF NOT EXISTS idx_attendance_session_id ON attendance(session_id);
CREATE INDEX IF NOT EXISTS idx_attendance_room_id ON attendance(room_id);
CREATE INDEX IF NOT EXISTS idx_attendance_usn ON attendance(usn);

