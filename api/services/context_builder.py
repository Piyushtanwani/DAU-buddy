"""
Context Builder Service
=======================
Transforms raw database rows/dictionaries into clean, token-efficient
structured text for the Gemini RAG prompt.
"""
from typing import List, Dict, Any

from api.services.caller_identity import CallerIdentity


def build_caller_context(identity: CallerIdentity) -> str:
    out = [
        "**CALLER CONTEXT**",
        "You are speaking with a signed-in user whose identity was verified from "
        "their login credential. Resolve \"I\", \"me\" and \"my\" to this person, and "
        "use these details instead of asking for them.",
        f"Role: {identity.role}",
    ]

    if identity.display_name:
        out.append(f"Name: {identity.display_name}")

    # Only name a timetable identity that was actually confirmed against the
    # timetable. The directory spelling is not usable as a timetable query for
    # 29 of 121 faculty, and naming an unconfirmed one would send the model to
    # fetch a schedule under a name that returns nothing — or, with any fuzzy
    # bridge, a colleague's. When it is absent the model still has rules A3/A4,
    # which tell it these are two name spaces and to fall back to searching.
    if identity.timetable_name:
        out.append(
            f"For their own schedule, location or free time, call the timetable "
            f"tools with \"{identity.timetable_name}\"."
        )
        try:
            from api.services import timetable_service
            my_sched = timetable_service.get_personalized_faculty_schedule(identity, None)
            sched_items = my_sched.get('schedule', [])
            if sched_items:
                sched_str = " | ".join([f"{str(s.get('day_of_week'))[:3]} {str(s.get('start_time'))[:5]}-{str(s.get('end_time'))[:5]} {s.get('course_code')} {s.get('room')}" for s in sched_items])
                out.append(f"Their PERSONALIZED schedule (including overrides): {sched_str}")
                out.append("Use this personalized schedule if they ask about their own timetable, instead of calling get_faculty_schedule.")
        except Exception as e:
            pass

    out.append(f"Email: {identity.email}")

    if not identity.is_student:
        return "\n".join(out)

    # 'Student' is also what resolve_role returns for an address it cannot place
    # and when the directory lookup raises, so it is not evidence of studenthood
    # on its own. A roll number is. Six faculty rows hold two comma-separated
    # addresses, which resolve_role's `WHERE email = %s` misses, so they arrive
    # here labelled Student today.
    if not identity.roll_number:
        out.append(
            "Their programme and semester are not known — the sign-in address is "
            "not a roll number, so they may be faculty or staff missing from the "
            "directory. Do not assert they are a student; ask what they need."
        )
        return "\n".join(out)

    out.append(f"Roll number: {identity.roll_number}")
    out.append(f"Admitted: {identity.admission_year}")

    if identity.is_probably_alumnus:
        out.append(
            "Programme status: their programme's nominal length has already passed, "
            "so they have most likely graduated. Do not state a current semester or "
            "fetch a timetable for them — say the timetable covers current students "
            "and ask what they need."
        )
        return "\n".join(out)

    if identity.program:
        out.append(f"Programme: {identity.program} (derived from the roll number)")
    elif identity.program_is_ambiguous:
        out.append(
            "Programme: UNKNOWN — the roll number narrows it to "
            + " or ".join(identity.program_candidates)
            + ". Ask which one before answering anything programme-specific."
        )
    elif identity.program_is_unmapped:
        out.append(
            f"Programme: UNKNOWN — roll number code {identity.program_code} is not "
            "mapped to a programme. Ask which programme they are in; never guess."
        )
    else:
        out.append("Programme: UNKNOWN — ask which programme they are in.")

    if identity.semester_estimate is not None:
        out.append(
            f"Likely semester: {identity.semester_estimate} — an estimate from the "
            "admission year, not a record. Use it as a default and let them correct it."
        )

    try:
        from api.services import timetable_service
        my_sched = timetable_service.get_personalized_student_schedule(identity, None)
        sched_items = my_sched.get('schedule', [])
        if sched_items:
            sched_str = " | ".join([f"{str(s.get('day_of_week'))[:3]} {str(s.get('start_time'))[:5]}-{str(s.get('end_time'))[:5]} {s.get('course_code')} {s.get('room')}" for s in sched_items])
            out.append(f"Their PERSONALIZED schedule (including electives and overrides): {sched_str}")
            out.append("Use this personalized schedule if they ask about their own timetable, instead of calling get_program_timetable.")
        else:
            out.append("Their personalized schedule is currently empty.")
    except Exception as e:
        out.append(f"Could not load personalized schedule. {e}")
        
    return "\n".join(out)


def build_faculty_context(records: List[Dict[str, Any]]) -> str:
    """Format a list of faculty dicts into a structured string."""
    if not records:
        return "No relevant faculty records found for the query."

    out = ["FACULTY RESULTS\n"]
    for i, rec in enumerate(records, 1):
        out.append(f"{i}.")
        out.append(f"Name: {rec.get('name', 'N/A')}")
        if rec.get('faculty_type'):
            out.append(f"Type: {rec.get('faculty_type')}")
        if rec.get('specialization'):
            out.append(f"Specialization: {rec.get('specialization')}")
        if rec.get('education'):
            out.append(f"Education: {rec.get('education')}")
        if rec.get('email'):
            out.append(f"Email: {rec.get('email')}")
        if rec.get('phone'):
            out.append(f"Phone: {rec.get('phone')}")
        if rec.get('address'):
            out.append(f"Office: {rec.get('address')}")
        if rec.get('profile_url'):
            out.append(f"Profile: {rec.get('profile_url')}")
        out.append("") # Empty line between records
        
    return "\n".join(out)


def build_staff_context(records: List[Dict[str, Any]]) -> str:
    """Format a list of staff dicts into a structured string."""
    if not records:
        return "No relevant staff records found for the query."

    out = ["STAFF RESULTS\n"]
    for i, rec in enumerate(records, 1):
        out.append(f"{i}.")
        out.append(f"Name: {rec.get('name', 'N/A')}")
        if rec.get('designation'):
            out.append(f"Designation: {rec.get('designation')}")
        if rec.get('qualification'):
            out.append(f"Qualification: {rec.get('qualification')}")
        if rec.get('email'):
            out.append(f"Email: {rec.get('email')}")
        if rec.get('phone'):
            out.append(f"Phone: {rec.get('phone')}")
        if rec.get('address'):
            out.append(f"Office: {rec.get('address')}")
        if rec.get('profile_url'):
            out.append(f"Profile: {rec.get('profile_url')}")
        out.append("") # Empty line between records
        
    return "\n".join(out)
