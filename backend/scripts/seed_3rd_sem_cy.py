"""Seed 3rd Semester Cyber Security (CY) students from official DSCE Student List PDF.

Enrolls 71 students under:
- Branch: 'CY'
- Department: 'CSE-CY'
- Semester: 'SEM-3'
"""

import os
from sqlalchemy import create_engine, text
from dotenv import load_dotenv

load_dotenv(r"c:\Users\Bhanu Prasad\OneDrive\Desktop\Ai_proj\Roll_Call\backend\.env")
engine = create_engine(os.getenv("DATABASE_URL"))

STUDENTS_3RD_SEM = [
    (1, "1DS24CY018", "KUMAR NIRAV"),
    (2, "1DS24CY036", "SAMUDRA CHETAN"),
    (3, "1DS24CY051", "SURAJ GOWDA K H"),
    (4, "1DS25CY001", "AARYA N GOWDA"),
    (5, "1DS25CY002", "ADITI NAHATA"),
    (6, "1DS25CY003", "AJITH REDDY G"),
    (7, "1DS25CY005", "AKASH K V"),
    (8, "1DS25CY006", "AKSHAY V"),
    (9, "1DS25CY007", "ALANKRITH ANAND"),
    (10, "1DS25CY008", "AMRIT SHEKHAR"),
    (11, "1DS25CY009", "ANSH DHYANI"),
    (12, "1DS25CY010", "ARPITA B KERAKANAVAR"),
    (13, "1DS25CY011", "ARYAN RAI"),
    (14, "1DS25CY012", "ASTHA KESHRI"),
    (15, "1DS25CY013", "AYUSH ROY"),
    (16, "1DS25CY014", "BHAVYA BAID"),
    (17, "1DS25CY015", "BHUMI SINGH"),
    (18, "1DS25CY016", "C MONIKA"),
    (19, "1DS25CY017", "DEVANCHAL SANTOSH SHANBHAG"),
    (20, "1DS25CY018", "DHANUSH SOMASHEKAR D"),
    (21, "1DS25CY019", "DHRUV V BHONSLEY"),
    (22, "1DS25CY020", "DIVYA"),
    (23, "1DS25CY021", "DIVYA U"),
    (24, "1DS25CY022", "GAURAV KUMAR CHATTARJEE"),
    (25, "1DS25CY023", "GEETHA SOUJANYA G"),
    (26, "1DS25CY024", "HARSH ABHINANDAN"),
    (27, "1DS25CY025", "HARSH YADAV"),
    (28, "1DS25CY026", "HEMA T"),
    (29, "1DS25CY027", "ISHITHA MUTHAPPA K"),
    (30, "1DS25CY028", "JAANVI MEJETHIA"),
    (31, "1DS25CY029", "KARTHIK GOUDA BAIREDDY"),
    (32, "1DS25CY030", "KOUSHIK MADHUKAR NAIK"),
    (33, "1DS25CY031", "MAANAS MACHINENI"),
    (34, "1DS25CY032", "MAHESH VITTAL GALAVE"),
    (35, "1DS25CY033", "MANAS JHA"),
    (36, "1DS25CY034", "MANYA KUMAR"),
    (37, "1DS25CY035", "MOHIT ANJANA"),
    (38, "1DS25CY036", "NEEL DUTTA"),
    (39, "1DS25CY037", "NEHASHREE K"),
    (40, "1DS25CY038", "OM KUMAR"),
    (41, "1DS25CY039", "P SARIYA HUSNA FEROZ"),
    (42, "1DS25CY040", "P V S N KEERTHIVARDHAN"),
    (43, "1DS25CY041", "PARITOSH K"),
    (44, "1DS25CY042", "PRAJWAL B N"),
    (45, "1DS25CY043", "PRAJWAL PATIL"),
    (46, "1DS25CY044", "PRAYAS PARTHO PATI"),
    (47, "1DS25CY045", "RITIK KUMAR KURREY"),
    (48, "1DS25CY046", "S N VIDHATHRI"),
    (49, "1DS25CY047", "SAISPOORTHI SANTOSH REVANKAR"),
    (50, "1DS25CY048", "SAKSHAM N ATHREYA"),
    (51, "1DS25CY049", "SHASHANK N"),
    (52, "1DS25CY050", "SIDDHANT SAHU"),
    (53, "1DS25CY051", "SRIJAN S POOJARY"),
    (54, "1DS25CY052", "SRIVALLI CHEKURI"),
    (55, "1DS25CY053", "SUBRAMANYA S P"),
    (56, "1DS25CY054", "TEJAS KUMAR"),
    (57, "1DS25CY055", "TEJASWINI"),
    (58, "1DS25CY056", "TOUZIH ARMAR"),
    (59, "1DS25CY057", "VAIBHAVKUMAR V B"),
    (60, "1DS25CY058", "VAISHNAVI VATSALA"),
    (61, "1DS25CY059", "VANSIKA M"),
    (62, "1DS25CY060", "VENKATESH"),
    (63, "1DS25CY061", "VIKASH RAJ"),
    (64, "1DS25CY062", "YASH JOHN"),
    (65, "1DS25CY063", "YASHAS BABU NAIK"),
    (66, "26UGDS0717", "BHARANI AVIK"),
    (67, "26UGDS0715", "CHIDANANDA D G"),
    (68, "26UGDS0671", "MAYUR DATTATREYA SAMAK"),
    (69, "26UGDS2093", "P MANIKANTA"),
    (70, "26UGDS2553", "SUMANTHKUMAR C"),
    (71, "26UGDS2373", "TEJAS Y K"),
]


def run_seed():
    with engine.begin() as conn:
        print("=== 1. Enrolling 71 3rd-Semester CY Students ===")
        # Remove any pre-existing 3rd sem CY students to ensure clean idempotent insert
        conn.execute(text("DELETE FROM students WHERE semester_id = 'SEM-3' AND branch = 'CY'"))

        for sl_no, usn, name in STUDENTS_3RD_SEM:
            conn.execute(
                text("""
                    INSERT INTO students (usn, name, branch, dept_id, semester_id, roll_no)
                    VALUES (:usn, :name, 'CY', 'CSE-CY', 'SEM-3', :roll)
                    ON CONFLICT (usn) DO UPDATE SET
                        name = EXCLUDED.name,
                        branch = EXCLUDED.branch,
                        dept_id = EXCLUDED.dept_id,
                        semester_id = EXCLUDED.semester_id,
                        roll_no = EXCLUDED.roll_no
                """),
                {
                    "usn": usn,
                    "name": name,
                    "roll": str(sl_no),
                }
            )

        print(f"Successfully inserted {len(STUDENTS_3RD_SEM)} 3rd-semester students into SEM-3!")


if __name__ == "__main__":
    run_seed()
