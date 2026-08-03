"""
Seed Timetable Script
=====================
Parses the active lecture timetable Excel file (Lecture_TT_Autumn2026-27_v9.xlsx)
and populates the timetables table with clean program batch mappings using curriculum.json.

Usage:
    python scripts/seed_timetable.py
"""
import os
import re
import sys
import json
import psycopg2
import psycopg2.extras

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from core import config
from core.database import db_connection

logger = config.get_logger("scripts.seed_timetable")

try:
    import openpyxl
except ImportError:
    logger.error("openpyxl not installed. Run: pip install openpyxl")
    sys.exit(1)

# ── Config ────────────────────────────────────────────────────────────────────
DATA_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data")
POSSIBLE_PATHS = [
    os.path.join(DATA_DIR, "Lecture Data.xlsx"),
    os.path.join(DATA_DIR, "Lecture_TT_Autumn2026-27_v9.xlsx"),
]
POSSIBLE_LAB_PATHS = [
    os.path.join(DATA_DIR, "Lab Data.xlsx"),
    os.path.join(DATA_DIR, "Lab_TT_Autumn2026-27.xlsx"),
]

DAYS = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday"]

def find_excel_file() -> str:
    for path in POSSIBLE_PATHS:
        if os.path.exists(path):
            return path
    # Dynamic search for any Lecture*.xlsx in data/
    if os.path.exists(DATA_DIR):
        for f in os.listdir(DATA_DIR):
            if f.endswith(".xlsx") and "lecture" in f.lower():
                return os.path.join(DATA_DIR, f)
    raise FileNotFoundError(f"No timetable Excel file found in data/ folder ({DATA_DIR}).")

def find_lab_excel_file() -> str | None:
    for path in POSSIBLE_LAB_PATHS:
        if os.path.exists(path):
            return path
    if os.path.exists(DATA_DIR):
        for f in os.listdir(DATA_DIR):
            if f.endswith(".xlsx") and "lab" in f.lower():
                return os.path.join(DATA_DIR, f)
    return None

def load_curriculum():
    path = os.path.join(DATA_DIR, "curriculum.json")
    if not os.path.exists(path):
        logger.warning("curriculum.json not found. Run parse_curriculum.py first.")
        return {}
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)

def _parse_time(t) -> str | None:
    if not t:
        return None
    m = re.match(r"(\d{1,2}):(\d{2})", str(t))
    if not m:
        return None
    hour = int(m.group(1))
    # Timetable labels are 12-hour without AM/PM; campus day runs 08:00-19:00,
    # so hours 1-7 are afternoon (13:00-19:00).
    if 1 <= hour <= 7:
        hour += 12
    return f"{hour:02d}:{m.group(2)}:00"

def _normalize_room(room: str) -> str:
    r = re.sub(r"\s+", " ", room.strip())
    # Canonical forms differ by building: CEP/LT are hyphenated (CEP-102, LT-2),
    # LAB is not (LAB004).
    m = re.match(r"^(CEP|LT)\s*-?\s*(\d+[A-Z]?)$", r, re.IGNORECASE)
    if m:
        return f"{m.group(1).upper()}-{m.group(2).upper()}"
    m = re.match(r"^LAB\s*-?\s*(\d+[A-Z]?)$", r, re.IGNORECASE)
    if m:
        return f"LAB{m.group(1).upper()}"
    return r

def split_rooms(room_str: str) -> list:
    """Split compound room strings ("CEP-102 & CEP-110", "LAB207, LAB112 & LAB009")
    into normalized individual rooms. Returns [""] when no room is given so callers
    still emit one record."""
    parts = [p for p in re.split(r"\s*[&,]\s*", room_str or "") if p.strip()]
    return [_normalize_room(p) for p in parts] or [""]

def _resolve_slot(slot) -> tuple:
    if not slot:
        return None, None
    m = re.match(r"(\d{1,2}:\d{2})\s*[-–]\s*(\d{1,2}:\d{2})", str(slot))
    if m:
        return _parse_time(m.group(1)), _parse_time(m.group(2))
    return None, None

def read_abbrev_map(wb) -> dict:
    """Short name → full display name, from the workbook's abbreviations sheet.

    e.g. {"AC": "Ankush Chander (AC)"}. Both parsers write this same display
    form into `timetables.faculty_name`, so lecture and lab rows for one person
    are matchable by the same name lookup.
    """
    abbrev_map = {}
    if "FacultyNameAbbreviations" in wb.sheetnames:
        for row in wb["FacultyNameAbbreviations"].iter_rows(min_row=2, values_only=True):
            if row[0] and row[1]:
                abbrev_map[str(row[1]).strip()] = str(row[0]).strip()
    return abbrev_map


def load_abbrev_map(excel_path: str) -> dict:
    """read_abbrev_map() for callers that only have a path (e.g. the lab parser,
    whose own workbook carries no abbreviations sheet)."""
    return read_abbrev_map(openpyxl.load_workbook(excel_path, data_only=True))


def expand_faculty_codes(value: str, abbrev_map: dict) -> str:
    """Resolve a lab sheet's faculty cell to the same display form lectures use.

    The lab workbook identifies staff by short name only ("AC"), while the
    lecture workbook writes "Ankush Chander (AC)". Left unresolved, every
    faculty-name query — schedules, locations, busy/free time — silently misses
    that person's labs.

        "AC"               -> "Ankush Chander (AC)"
        "AB1/NKS"          -> "A B (AB1) / N K S (NKS)"
        "TF/TA"            -> "TF/TA"        (nothing to resolve, left alone)

    Matching is exact per token, never substring: "AC" and "AC1" are different
    people (Ankush Chander vs Arunava Chakravarty).
    """
    if not value or not abbrev_map:
        return value

    tokens = [t.strip() for t in value.split("/")]
    if not any(t in abbrev_map for t in tokens):
        return value

    return " / ".join(abbrev_map.get(t, t) for t in tokens)


def parse_excel(excel_path: str, curriculum: dict) -> list:
    wb = openpyxl.load_workbook(excel_path, data_only=True)

    # Abbreviation map: initials → full name
    abbrev_map = read_abbrev_map(wb)

    sheet_name = "Lecture (Update)" if "Lecture (Update)" in wb.sheetnames else wb.sheetnames[0]
    all_rows = list(wb[sheet_name].iter_rows(values_only=True))

    header_idx = None
    day_cols = {}
    for i, row in enumerate(all_rows):
        if any(str(v).strip() in DAYS for v in row if v):
            header_idx = i
            break
    if header_idx is None:
        logger.error("Could not find day header row in Excel.")
        sys.exit(1)
    for ci, v in enumerate(all_rows[header_idx]):
        if v and str(v).strip() in DAYS:
            day_cols[str(v).strip()] = ci

    records = []
    cur_time = None
    
    for row in all_rows[header_idx + 1:]:
        t = row[0] if len(row) > 0 else None
        if t and str(t).strip():
            cur_time = str(t).strip()
        if not cur_time:
            continue

        start, end = _resolve_slot(cur_time)

        for day in DAYS:
            if day not in day_cols:
                continue
            dc = day_cols[day]
            course  = row[dc]     if len(row) > dc     else None
            faculty = row[dc + 1] if len(row) > dc + 1 else None
            room    = row[dc + 2] if len(row) > dc + 2 else None

            if not course:
                continue
            cs = str(course).strip()
            fs = str(faculty).strip() if faculty else ""
            rs = str(room).strip()    if room    else ""

            if not cs or cs in ("-", "—", "Course"):
                continue

            faculty_full = abbrev_map.get(fs, f"{fs} (unresolved)" if fs else "TBA")

            # Look up metadata from curriculum
            # The excel has course codes. Curriculum JSON has them as keys.
            meta_list = curriculum.get(cs, [])
            if not meta_list:
                meta_list = [{}]  # fallback for unknown courses
                
            for meta in meta_list:
                for room_name in split_rooms(rs):
                    rec = {
                        "session_type": "Lecture",
                        "day": day,
                        "start": start,
                        "end": end,
                        "course_code": cs,
                        "course_name": meta.get("course_name", cs),
                        "course_type": meta.get("course_type", "Unknown"),
                        "program": meta.get("program", "Unknown Program"),
                        "semester": str(meta.get("semester", "")),
                        "faculty": faculty_full,
                        "room": room_name,
                    }
                    records.append(rec)

    return records

def parse_lab_excel(excel_path: str, curriculum: dict, abbrev_map: dict = None) -> list:
    wb = openpyxl.load_workbook(excel_path, data_only=True)
    sheet_name = wb.sheetnames[0]
    all_rows = list(wb[sheet_name].iter_rows(values_only=True))

    records = []
    
    header_idx = None
    for i, row in enumerate(all_rows):
        if any(str(v).strip() == "Time Slot" for v in row if v):
            header_idx = i
            break
            
    if header_idx is None:
        logger.warning(f"Could not find 'Time Slot' header in {excel_path}")
        return []

    day_cols = {}
    for ci, v in enumerate(all_rows[header_idx]):
        if v and str(v).strip() in DAYS:
            day_cols[str(v).strip()] = ci

    if not day_cols:
        day_cols = {"Monday": 1, "Tuesday": 2, "Wednesday": 3, "Thursday": 4, "Friday": 5}
        
    time_col, room_col, course_col, faculty_col = 0, 6, 7, 8
    current_program_header = "Unknown Program"
    
    # Tutorial continuation rows: some rows have group data in day columns
    # but leave course/faculty blank, expecting them to carry forward.
    last_course = None
    last_faculty = None
    
    for row in all_rows[header_idx + 1:]:
        t = row[time_col] if len(row) > time_col else None
        
        if t and not re.search(r"\d{1,2}:\d{2}", str(t)):
            current_program_header = str(t).strip()
            # Reset carry-forward on new program section
            last_course = None
            last_faculty = None
            continue
            
        if not t or not str(t).strip():
            continue
            
        start, end = _resolve_slot(t)
        if not start or not end:
            continue
            
        room_raw = str(row[room_col]).strip() if len(row) > room_col and row[room_col] else ""
        course_raw = str(row[course_col]).strip() if len(row) > course_col and row[course_col] else ""
        faculty_raw = str(row[faculty_col]).strip() if len(row) > faculty_col and row[faculty_col] else ""
        
        # Carry-forward: update trackers when present, inherit when blank
        if course_raw and course_raw not in ("-", "—"):
            last_course = course_raw
        if faculty_raw:
            last_faculty = faculty_raw
        
        course = course_raw or last_course or ""
        faculty = faculty_raw or last_faculty or ""
        # Lab sheets carry short names only — resolve to the same display form
        # the lecture sheet writes, so both are reachable by one name lookup.
        faculty = expand_faculty_codes(faculty, abbrev_map)
        
        if not course or course in ("-", "—"):
            continue

        meta_list = curriculum.get(course, [])
        if not meta_list:
            meta_list = [{"program": current_program_header}]
            
        for day in DAYS:
            if day not in day_cols:
                continue
            dc = day_cols[day]
            group_val = row[dc] if len(row) > dc else None
            if group_val and str(group_val).strip():
                gv = str(group_val).strip()
                session_type = f"Tutorial ({gv})" if "tut" in gv.lower() else f"Lab ({gv})"
                
                for meta in meta_list:
                    for room_name in split_rooms(room_raw):
                        records.append({
                            "session_type": session_type,
                            "day": day,
                            "start": start,
                            "end": end,
                            "course_code": course,
                            "course_name": meta.get("course_name", course),
                            "course_type": meta.get("course_type", "Unknown"),
                            "program": meta.get("program", current_program_header),
                            "semester": str(meta.get("semester", "")),
                            "faculty": faculty,
                            "room": room_name,
                        })
                    
    return records


def main():
    try:
        excel_path = find_excel_file()
        logger.info(f"Parsing active timetable from: {excel_path}")
        
        curriculum = load_curriculum()
        logger.info(f"Loaded {len(curriculum)} courses from curriculum.json")
        
        records = parse_excel(excel_path, curriculum)
        
        lab_excel_path = find_lab_excel_file()
        if lab_excel_path:
            logger.info(f"Parsing lab timetable from: {lab_excel_path}")
            # The abbreviations sheet lives in the lecture workbook, so the lab
            # parser has to be handed it explicitly.
            abbrev_map = load_abbrev_map(excel_path)
            logger.info(f"Loaded {len(abbrev_map)} faculty short names for lab resolution.")
            lab_records = parse_lab_excel(lab_excel_path, curriculum, abbrev_map)
            records.extend(lab_records)
        else:
            logger.info("No lab timetable file found. Skipping labs.")

        logger.info(f"Parsed {len(records)} timetable records.")

        with db_connection() as conn:
            with conn.cursor() as cur:
                # TRUNCATE existing timetables to keep only active timetable dataset
                cur.execute("TRUNCATE TABLE timetables;")
                logger.info("Cleared existing timetables table.")

                INSERT_SQL = """
                    INSERT INTO timetables
                        (session_type, course_code, course_name, course_type, program, semester, faculty_name,
                         day_of_week, start_time, end_time, room)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                """
                counts = {}
                for rec in records:
                    prog = rec["program"]
                    cur.execute(INSERT_SQL, (
                        rec["session_type"],
                        rec["course_code"],
                        rec["course_name"],
                        rec["course_type"],
                        rec["program"],
                        rec["semester"] if rec["semester"] else None,
                        rec["faculty"],
                        rec["day"],
                        rec["start"],
                        rec["end"],
                        rec["room"]
                    ))
                    counts[prog] = counts.get(prog, 0) + 1

            conn.commit()

        logger.info("=== Timetable Seeded Successfully ===")
        for prog, n in sorted(counts.items()):
            logger.info(f"  {prog}: {n} rows")
        logger.info(f"Total inserted: {sum(counts.values())} records.")

    except Exception as e:
        logger.error(f"Failed to seed timetable data: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()
