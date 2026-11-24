"""Seed 5th Semester Cyber Security (CY) students and faculty from official DSCE documents.

- 66 Students with USN, Name, Semester (SEM-5), Branch (CY), and assigned Proctor.
- 12 Teachers with teacher usernames, bcrypt hashed password 'TeacherPass_2026!',
  tentative OTP test emails, and subject mappings from the 5th sem timetable.
"""

import os
import bcrypt
from datetime import datetime, timezone
from sqlalchemy import create_engine, text
from dotenv import load_dotenv

load_dotenv(r"c:\Users\Bhanu Prasad\OneDrive\Desktop\Ai_proj\Roll_Call\backend\.env")
engine = create_engine(os.getenv("DATABASE_URL"))

now_iso = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
default_pw = "TeacherPass_2026!"
hashed_pw = bcrypt.hashpw(default_pw.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")

# 1. Teachers from Timetable & Proctor List
TEACHERS = [
    {
        "user_id": "tajuddin",
        "name": "Dr. Mohammed Tajuddin",
        "email": "tajuddin@dsce.edu.in",
        "designation": "Professor & HoD",
        "branch": "CY",
        "subjects": ["ECS", "22CY53"]
    },
    {
        "user_id": "mangala",
        "name": "Mangala L",
        "email": "1ds24cy015@dsce.edu.in",  # Tentative test email for OTP
        "designation": "Assistant Professor",
        "branch": "CY",
        "subjects": ["SE", "22CY51"]
    },
    {
        "user_id": "pallavi",
        "name": "Dr. Pallavi Kulkarni",
        "email": "gbhanuprasad63@gmail.com",  # Tentative test email for OTP
        "designation": "Associate Professor",
        "branch": "CY",
        "subjects": ["CN", "22CY52"]
    },
    {
        "user_id": "mathews",
        "name": "Mathews Kuruvila",
        "email": "1ds24cy021@dsce.edu.in",  # Tentative test email for OTP
        "designation": "Assistant Professor",
        "branch": "CY",
        "subjects": ["ECS", "22CY53"]
    },
    {
        "user_id": "padmavathi",
        "name": "Padmavathi S",
        "email": "yatishb1980@gmail.com",  # Tentative test email for OTP
        "designation": "Assistant Professor",
        "branch": "CY",
        "subjects": ["AI", "22CY551"]
    },
    {
        "user_id": "nida_afreen",
        "name": "Nida Afreen Rizvi",
        "email": "1ds24cy035@dsce.edu.in",  # Tentative test email for OTP
        "designation": "Assistant Professor",
        "branch": "CY",
        "subjects": ["RM", "22RMK56"]
    },
    {
        "user_id": "deepthi",
        "name": "Dr. Deepthi V S",
        "email": "deepthi.vs@dsce.edu.in",
        "designation": "Associate Professor",
        "branch": "CY",
        "subjects": ["ACS", "22CYL54"]
    },
    {
        "user_id": "sowmya",
        "name": "Dr. Sowmya S",
        "email": "sowmya.s@dsce.edu.in",
        "designation": "Assistant Professor",
        "branch": "CY",
        "subjects": ["EVS", "22ESK57"]
    },
    {
        "user_id": "vinod",
        "name": "Dr. Vinod H C",
        "email": "vinod.hc@dsce.edu.in",
        "designation": "Associate Professor",
        "branch": "CY",
        "subjects": ["ACS", "ECS"]
    },
    {
        "user_id": "rakshitha",
        "name": "Dr. Rakshitha Kiran P",
        "email": "rakshitha.kp@dsce.edu.in",
        "designation": "Assistant Professor & Coordinator",
        "branch": "CY",
        "subjects": ["CN", "22CY52"]
    },
    {
        "user_id": "veena_dhavalgi",
        "name": "Prof. Veena Dhavalgi",
        "email": "veena.d@dsce.edu.in",
        "designation": "Assistant Professor",
        "branch": "CY",
        "subjects": ["CN", "ECS"]
    },
    {
        "user_id": "shresta",
        "name": "Ms. Shresta Mangala L",
        "email": "shresta.m@dsce.edu.in",
        "designation": "Assistant Professor",
        "branch": "CY",
        "subjects": ["SE", "22CY51"]
    },
]

# 2. Subjects from Timetable
SUBJECTS = [
    ("22CY51", "CSE-CY", "Software Engineering", 4, 4, "THEORY"),
    ("22CY52", "CSE-CY", "Computer Networks & Security", 4, 4, "THEORY"),
    ("22CY53", "CSE-CY", "Essential of Cyber Security", 4, 4, "THEORY"),
    ("22ESK57", "CSE-CY", "Environment Studies", 2, 2, "THEORY"),
    ("22CYL54", "CSE-CY", "Adv. Cyber Security", 4, 4, "LAB"),
    ("22CY551", "CSE-CY", "AI in Cyber Security", 3, 3, "THEORY"),
    ("22RMK56", "CSE-CY", "Research Methodology & IPR", 3, 3, "THEORY"),
]

# 3. All 66 Students from Proctor List PDF (SL. 1 to 66)
STUDENTS = [
    # Page 1
    (1, "1DS24CY001", "MARIGERI AAKASH UMESH", "tajuddin"),
    (2, "1DS24CY002", "ABHINAV KUMAR", "tajuddin"),
    (3, "1DS24CY003", "ABHISHEK RAMESH MAGADUM", "tajuddin"),
    (4, "1DS24CY004", "ABHISHEK TIWARI", "tajuddin"),
    (5, "1DS24CY005", "ADITHYA B SHETTY", "tajuddin"),
    (6, "1DS24CY006", "AKASH M RATHOD", "tajuddin"),
    (7, "1DS24CY007", "AKSHAY BHIMAPPA KOKATANUR", "vinod"),
    (8, "1DS24CY008", "BHUSHAN ANANTH", "vinod"),
    (9, "1DS24CY009", "CHINMAYEE D", "nida_afreen"),
    (10, "1DS24CY010", "DARSHAN GUPTA", "nida_afreen"),
    (11, "1DS24CY011", "DEVANSH PATERIYA", "nida_afreen"),
    (12, "1DS24CY012", "DHARSHAN P", "deepthi"),
    (13, "1DS24CY013", "DILEEP M G", "deepthi"),
    (14, "1DS24CY014", "DISHA SINGH", "deepthi"),
    (15, "1DS24CY015", "GULIVINDALA BHANU PRASAD", "deepthi"),
    (16, "1DS24CY016", "HARSHA S", "vinod"),
    (17, "1DS24CY017", "KESHAV LATH", "deepthi"),
    (18, "1DS24CY019", "LAKSHYA SOLANKI", "deepthi"),
    (19, "1DS24CY020", "LEKHANA Y R", "veena_dhavalgi"),
    (20, "1DS24CY021", "MAHADEV H", "veena_dhavalgi"),
    (21, "1DS24CY022", "MANNAN DIPESH KOTHARI", "veena_dhavalgi"),
    (22, "1DS24CY023", "MOHAMMED NUMAN", "mathews"),
    (23, "1DS24CY024", "NAVANEETHAN", "mathews"),
    (24, "1DS24CY025", "NEHA N", "padmavathi"),
    (25, "1DS24CY026", "NITHIN A", "padmavathi"),
    (26, "1DS24CY027", "POORNIMA RAVEENDRA TALAWAR", "padmavathi"),
    (27, "1DS24CY028", "PRAKRUTHI H R", "padmavathi"),
    (28, "1DS24CY029", "R M NAKSHA NIVEDITHA", "padmavathi"),
    # Page 2
    (29, "1DS24CY031", "RAWAL HARSHVARDHAN RAMESHKUMAR", "padmavathi"),
    (30, "1DS24CY032", "RIYA SISODIYA", "nida_afreen"),
    (31, "1DS24CY033", "SADHWI SARGAM", "nida_afreen"),
    (32, "1DS24CY034", "SAHASTRANSHU MISHRA", "veena_dhavalgi"),
    (33, "1DS24CY035", "SAMPADA AJAY DESAI", "mathews"),
    (34, "1DS24CY037", "SANCHITHA S", "shresta"),
    (35, "1DS24CY038", "SANDEEP G", "shresta"),
    (36, "1DS24CY039", "SANDESH K C", "shresta"),
    (37, "1DS24CY040", "SARA BI", "shresta"),
    (38, "1DS24CY041", "SHRESTHA CHANDRA", "mathews"),
    (39, "1DS24CY042", "SHRIKARI PRASAD PEDDAMATHAM", "shresta"),
    (40, "1DS24CY043", "SIDDALINGESHWAR SANGAMANATH GIDDAPPAGOL", "shresta"),
    (41, "1DS24CY044", "SIDDHI AGARWAL", "nida_afreen"),
    (42, "1DS24CY045", "SINCHAN METRE", "nida_afreen"),
    (43, "1DS24CY046", "SINCHANA T R", "mathews"),
    (44, "1DS24CY047", "SNEHA", "rakshitha"),
    (45, "1DS24CY048", "SOWRAV C", "rakshitha"),
    (46, "1DS24CY049", "SRI CHARN M V HAZARE", "rakshitha"),
    (47, "1DS24CY050", "STEVE ABRAHAM NIXON", "rakshitha"),
    (48, "1DS24CY052", "SURAJ SANDILYA", "rakshitha"),
    (49, "1DS24CY053", "SYED MOHAMMED KAZIM RAZA", "rakshitha"),
    (50, "1DS24CY054", "TEJA K", "mathews"),
    (51, "1DS24CY055", "TEJASWA RAJ", "mathews"),
    (52, "1DS24CY056", "THRUPTHI PRABHU", "mathews"),
    (53, "1DS24CY057", "UBED URF GAFOOR ATTAR", "nida_afreen"),
    (54, "1DS24CY058", "URVASHI PARWAT", "veena_dhavalgi"),
    (55, "1DS24CY059", "VINAY NAGESH MADIVAL", "pallavi"),
    (56, "1DS24CY060", "YATISH BALU", "pallavi"),
    (57, "1DS24CY061", "YUGESH K", "pallavi"),
    (58, "1DS24CY400", "GEETHA N", "pallavi"),
    (59, "1DS24CY401", "KIRAN N U", "pallavi"),
    (60, "1DS24CY402", "MAHAMMED SAJEED MUKTAR SHAIKH", "pallavi"),
    (61, "1DS24CY403", "MURULI K M", "vinod"),
    (62, "1DS24CY404", "NIPUN ADARSH", "vinod"),
    (63, "1DS24CY405", "SAKSHI", "veena_dhavalgi"),
    (64, "1DS24CY406", "SHREYAS JAKARADDI", "veena_dhavalgi"),
    # Page 3
    (65, "1DS23CY025", "JHENKAR K", "veena_dhavalgi"),
    (66, "1DS23CY054", "SOURAJIT SENGUP", "veena_dhavalgi"),
]


def run_seed():
    with engine.begin() as conn:
        print("=== 0. Releasing gbhanuprasad63@gmail.com from bhanu_prasad to avoid unique conflict ===")
        conn.execute(text("UPDATE users SET email = 'gbhanuprasad63+user@gmail.com' WHERE user_id = 'bhanu_prasad'"))

        print("=== 1. Ensuring Columns in Database ===")
        # Ensure proctor_id exists on students
        conn.execute(text("ALTER TABLE students ADD COLUMN IF NOT EXISTS proctor_id VARCHAR"))

        # Ensure user_profiles table exists
        conn.execute(text("""
            CREATE TABLE IF NOT EXISTS user_profiles (
                user_id VARCHAR PRIMARY KEY REFERENCES users(user_id) ON DELETE CASCADE,
                full_name VARCHAR,
                mobile VARCHAR,
                email VARCHAR,
                branch VARCHAR,
                designation VARCHAR,
                experience_years INTEGER,
                qualifications TEXT,
                specialization TEXT,
                expertise JSONB,
                mastered_subjects JSONB,
                photo_url TEXT,
                updated_at VARCHAR
            )
        """))

        print("=== 2. Upserting Subjects ===")
        for code, dept, name, cred, hrs, stype in SUBJECTS:
            conn.execute(
                text("""
                    INSERT INTO subjects (subject_code, dept_id, name, credits, hours_per_week, subject_type)
                    VALUES (:code, :dept, :name, :cred, :hrs, :stype)
                    ON CONFLICT (subject_code) DO UPDATE SET
                        name = EXCLUDED.name,
                        dept_id = EXCLUDED.dept_id,
                        subject_type = EXCLUDED.subject_type
                """),
                {"code": code, "dept": dept, "name": name, "cred": cred, "hrs": hrs, "stype": stype}
            )
        print(f"Upserted {len(SUBJECTS)} subjects")

        print("=== 3. Upserting Faculty Accounts ===")
        for t in TEACHERS:
            # 1. users table
            conn.execute(
                text("""
                    INSERT INTO users (user_id, email, hashed_password, role, is_active, created_at)
                    VALUES (:uid, :em, :hp, 'FACULTY', 1, :ts)
                    ON CONFLICT (user_id) DO UPDATE SET
                        email = EXCLUDED.email,
                        hashed_password = EXCLUDED.hashed_password,
                        is_active = 1,
                        role = 'FACULTY'
                """),
                {"uid": t["user_id"], "em": t["email"], "hp": hashed_pw, "ts": now_iso}
            )

            # 2. user_profiles table
            conn.execute(
                text("""
                    INSERT INTO user_profiles (user_id, full_name, email, branch, designation, updated_at)
                    VALUES (:uid, :fname, :em, :branch, :desig, :ts)
                    ON CONFLICT (user_id) DO UPDATE SET
                        full_name = EXCLUDED.full_name,
                        email = EXCLUDED.email,
                        branch = EXCLUDED.branch,
                        designation = EXCLUDED.designation,
                        updated_at = EXCLUDED.updated_at
                """),
                {
                    "uid": t["user_id"],
                    "fname": t["name"],
                    "em": t["email"],
                    "branch": t["branch"],
                    "desig": t["designation"],
                    "ts": now_iso
                }
            )

            # 3. teacher_subjects & faculty_subjects mapping
            for sub in t["subjects"]:
                exists = conn.execute(
                    text("SELECT 1 FROM teacher_subjects WHERE user_id = :uid AND subject_code = :sub"),
                    {"uid": t["user_id"], "sub": sub}
                ).fetchone()
                if not exists:
                    conn.execute(
                        text("INSERT INTO teacher_subjects (user_id, subject_code) VALUES (:uid, :sub)"),
                        {"uid": t["user_id"], "sub": sub}
                    )

                exists_fs = conn.execute(
                    text("SELECT 1 FROM faculty_subjects WHERE user_id = :uid AND subject_code = :sub"),
                    {"uid": t["user_id"], "sub": sub}
                ).fetchone()
                if not exists_fs:
                    conn.execute(
                        text("""
                            INSERT INTO faculty_subjects (user_id, subject_code, dept_id, semester)
                            VALUES (:uid, :sub, 'CSE-CY', 5)
                        """),
                        {"uid": t["user_id"], "sub": sub}
                    )

        print(f"Created/updated {len(TEACHERS)} faculty accounts with password '{default_pw}'")

        print("=== 4. Inserting 66 5th-Semester CY Students ===")
        conn.execute(text("DELETE FROM students WHERE semester_id = 'SEM-5' OR branch = 'CY'"))
        for sl_no, usn, name, proctor_id in STUDENTS:
            conn.execute(
                text("""
                    INSERT INTO students (usn, name, branch, dept_id, semester_id, roll_no, proctor_id)
                    VALUES (:usn, :name, 'CY', 'CSE-CY', 'SEM-5', :roll, :pid)
                    ON CONFLICT (usn) DO UPDATE SET
                        name = EXCLUDED.name,
                        branch = EXCLUDED.branch,
                        dept_id = EXCLUDED.dept_id,
                        semester_id = EXCLUDED.semester_id,
                        roll_no = EXCLUDED.roll_no,
                        proctor_id = EXCLUDED.proctor_id
                """),
                {
                    "usn": usn,
                    "name": name,
                    "roll": str(sl_no),
                    "pid": proctor_id
                }
            )
        print(f"Inserted {len(STUDENTS)} 5th-semester students successfully!")


if __name__ == "__main__":
    run_seed()
