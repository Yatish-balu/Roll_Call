"""Natural-language session dates must resolve to the requested day."""

from datetime import date

from app.agent.legacy_agent import AttendanceAgent

# Tuesday 2026-11-24, matching the reported failure.
TODAY = date(2026, 11, 24)


def test_bare_weekday_means_upcoming_day():
    assert AttendanceAgent._parse_session_date("Add a session on friday", TODAY) == "2026-11-27"
    assert AttendanceAgent._parse_session_date("schedule class on Monday", TODAY) == "2026-11-30"
    assert AttendanceAgent._parse_session_date("create lecture on wednesday", TODAY) == "2026-11-25"


def test_this_and_next_weekday():
    assert AttendanceAgent._parse_session_date("this friday session", TODAY) == "2026-11-27"
    assert AttendanceAgent._parse_session_date("next friday session", TODAY) == "2026-12-04"


def test_today_tomorrow_and_iso_still_work():
    assert AttendanceAgent._parse_session_date("session today at 10:00", TODAY) == "2026-11-24"
    assert AttendanceAgent._parse_session_date("session tomorrow", TODAY) == "2026-11-25"
    assert AttendanceAgent._parse_session_date("session on 2026-12-10", TODAY) == "2026-12-10"


def test_weekday_on_the_current_day_stays_today():
    friday = date(2026, 11, 27)
    assert AttendanceAgent._parse_session_date("session on friday", friday) == "2026-11-27"
    assert AttendanceAgent._parse_session_date("next friday", friday) == "2026-12-04"


def test_subject_room_and_instructor_from_natural_prompt():
    prompt = (
        "create a seesion on friday from 1:20 pm to 2:00 pm where class is RMI "
        "subject by nida afreen ,room no:105"
    )
    assert AttendanceAgent._extract_session_subject(prompt) == "RMI"
    assert AttendanceAgent._extract_session_room(prompt) == "105"
    assert AttendanceAgent._extract_session_instructor(prompt) == "Nida Afreen"


def test_subject_patterns_do_not_pick_up_by_or_room():
    assert AttendanceAgent._extract_session_subject("subject is RMI by nida") == "RMI"
    assert AttendanceAgent._extract_session_subject("create MDEV session tomorrow") == "MDEV"
    assert AttendanceAgent._extract_session_room("session in room LH-101") == "LH-101"
    assert AttendanceAgent._extract_session_instructor("instructor: Nida Afreen") == "Nida Afreen"
