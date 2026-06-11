"""
Fallback NLP Engine
===================
Rule-based local routing engine that runs when Gemini is offline or unavailable.
Handles named-entity detection, intent routing, greetings, and general search.
"""
import re
from core import config
from core.database import db_connection
from api.services.faculty_service import (
    get_faculty_details_db,
    search_faculty_db,
    search_faculty_by_expertise_db,
    list_all_faculty_db,
)
from api.services.staff_service import (
    get_staff_details_db,
    search_staff_db,
    list_all_staff_db,
)

logger = config.get_logger("api.services.fallback")

# ==============================================================================
# Support Category Intent Router
# ==============================================================================
_SUPPORT_CATEGORIES = {
    "electrical": {
        "keywords": ["light", "fan", "ac", "air conditioner", "electricity", "electrical", "power", "switch", "plug", "socket", "wiring"],
        "title": "Electrical & Maintenance Staff",
        "description": (
            "For issues regarding lights, fans, ACs, power supply, or electrical maintenance in classes or rooms, please contact:"
        ),
        "conditions": [
            "designation ILIKE '%electrician%'", "designation ILIKE '%electrical%'",
            "designation ILIKE '%maintenance%'", "designation ILIKE '%wireman%'"
        ],
    },
    "it": {
        "keywords": ["wifi", "wi-fi", "internet", "network", "it", "computer", "system",
                     "systems", "portal", "login", "email account", "online", "server",
                     "lan", "cyber"],
        "title": "IT & Systems Support Staff",
        "description": (
            "For technical assistance regarding WiFi, email accounts, portals, internet "
            "connectivity, or campus computer systems, please contact the IT & Systems department:"
        ),
        "conditions": [
            "designation ILIKE '%it & system%'", "designation ILIKE '%it & systems%'", 
            "designation ILIKE '%network%'", "designation ILIKE '%computer%'",
        ],
    },
    "finance": {
        "keywords": ["finance", "account", "accounts", "salary", "fee", "fees",
                     "payment", "bill", "money", "transaction", "scholarship", "auditor"],
        "title": "Finance & Accounts Department",
        "description": (
            "For inquiries regarding student fees, payments, salaries, scholarships, "
            "or billing, please contact the Finance & Accounts office:"
        ),
        "conditions": [
            "designation ILIKE '%finance%'", "designation ILIKE '%account%'",
            "designation ILIKE '%audit%'",
        ],
    },
    "library": {
        "keywords": ["library", "book", "books", "journal", "resource center",
                     "resource centre", "reading room", "librarian"],
        "title": "Library & Resource Centre Staff",
        "description": (
            "For book lending, journals, library cards, digital resources, or reading "
            "room access, please contact the Library & Resource Centre:"
        ),
        "conditions": [
            "designation ILIKE '%library%'", "designation ILIKE '%resource%'",
            "designation ILIKE '%librarian%'",
        ],
    },
    "placement": {
        "keywords": ["placement", "job", "jobs", "internship", "career",
                     "placements", "recruit", "recruitment", "interview"],
        "title": "Placement & Career Cell Staff",
        "description": (
            "For placements, job interviews, campus recruitment, or internship "
            "coordination, please contact the Placement Cell:"
        ),
        "conditions": [
            "designation ILIKE '%placement%'", "designation ILIKE '%career%'",
            "designation ILIKE '%recruit%'",
        ],
    },
    "hostel": {
        "keywords": ["hostel", "mess", "housing", "room", "warden",
                     "residential", "accommodation"],
        "title": "Hostel & Residential Campus Staff",
        "description": (
            "For hostel rooms, accommodation assignments, mess facilities, or "
            "residence issues, please contact:"
        ),
        "conditions": [
            "designation ILIKE '%hostel%'", "designation ILIKE '%mess%'",
            "designation ILIKE '%warden%'", "designation ILIKE '%residential%'",
        ],
    },
    "lab": {
        "keywords": ["lab", "labs", "practical", "equipment", "laboratory", "workshop"],
        "title": "Laboratory & Workshops Technical Staff",
        "description": (
            "For lab equipment issues, practical sessions, laboratory access, "
            "or workshop maintenance, please contact:"
        ),
        "conditions": [
            "designation ILIKE '%lab%'", "designation ILIKE '%laboratory%'",
            "designation ILIKE '%workshop%'", "designation ILIKE '%technical%'",
        ],
    },
    "administration": {
        "keywords": ["admin", "administration", "admission", "admissions", "registrar",
                     "office", "clerk", "certificate", "transcript", "bonafide",
                     "exams", "examination", "schedule"],
        "title": "Administration & Academic Section",
        "description": (
            "For academic records, certificates, bonafide letters, transcripts, "
            "admissions, exam schedules, or general administrative support, please contact:"
        ),
        "conditions": [
            "designation ILIKE '%admin%'", "designation ILIKE '%registrar%'",
            "designation ILIKE '%admission%'", "designation ILIKE '%academic%'",
            "designation ILIKE '%exam%'", "designation ILIKE '%office%'",
            "designation ILIKE '%secretary%'",
        ],
    },
}


# ==============================================================================
# Topic Extraction Helper
# ==============================================================================
def _extract_topic(query: str) -> str:
    cleaned = query.strip().lower()
    cleaned = re.sub(r"[\?\.\!]+$", "", cleaned).strip()

    profile_match = re.search(
        r"(?:profile of|details of|tell me about|who is|about)\s+([a-zA-Z\s\.\-_]+)",
        cleaned,
    )
    if profile_match:
        return profile_match.group(1).strip()

    prefixes = [
        r"^i\s+am\s+working\s+on\s+a\s+project\s+on\s+",
        r"^i\s+am\s+working\s+on\s+",
        r"^i\s+am\s+interested\s+in\s+",
        r"^i\s+am\s+looking\s+for\s+",
        r"^can\s+you\s+suggest\s+(?:me\s+)?some\s+(?:faculty|faculties|faculty\s+members?|professors?)\s+(?:for|in|working\s+on)?\s+",
        r"^suggest\s+(?:me\s+)?some\s+(?:faculty|faculties|faculty\s+members?|professors?)\s+(?:for|in|working\s+on)?\s+",
        r"^find\s+(?:me\s+)?(?:faculty|faculties|faculty\s+members?|professors?)\s+(?:for|in|working\s+on)?\s+",
        r"^are\s+there\s+any\s+(?:faculty|faculties|faculty\s+members?|professors?)\s+(?:working\s+on|in|for)?\s+",
        r"^who\s+teaches\s+",
        r"^who\s+is\s+specialized\s+in\s+",
        r"^who\s+is\s+an\s+expert\s+in\s+",
        r"^who\s+does\s+research\s+in\s+",
        r"^faculty\s+for\s+",
        r"^faculties\s+for\s+",
        r"^professor\s+for\s+",
        r"^professors\s+for\s+",
    ]
    for prefix in prefixes:
        cleaned = re.sub(prefix, "", cleaned)

    suffixes = [
        r"\s+can\s+you\s+suggest\s+(?:me\s+)?some\s+(?:faculty|faculties|faculty\s+members?|professors?)?$",
        r"\s+suggest\s+(?:me\s+)?some\s+(?:faculty|faculties|faculty\s+members?|professors?)?$",
        r"\s+faculties\s+(?:for|in|working\s+on)?\s*$",
        r"\s+faculty\s+(?:for|in|working\s+on)?\s*$",
        r"\s+faculty\s+members?\s+(?:for|in|working\s+on)?\s*$",
        r"\s+professors?\s+(?:for|in|working\s+on)?\s*$",
        r"\s+please\s*$",
    ]
    for suffix in suffixes:
        cleaned = re.sub(suffix, "", cleaned)

    return cleaned.strip()


# ==============================================================================
# Main Fallback Routing Engine
# ==============================================================================
def process_fallback_message(prompt: str) -> str:
    """
    Multi-pass rule-based NLP routing engine.

    Pass order:
      0. Named Entity Overlap Matching (person-specific queries)
      1. Intent-Based Category Routing (IT, finance, library, etc.)
      2. Count queries
      3. Greeting / help / appreciation / farewell intercepts
      4. Directory listing shortcuts
      5. Profile-phrase extraction
      6. Topic extraction + DB search
      7. Specialization regex search
      8. Raw full-text search (faculty, then staff)
    """
    cleaned = prompt.strip().lower()

    # ── Pass 0: Named Entity Overlap Matching ─────────────────────────────────
    query_tokens = set(re.findall(r"[a-z]{3,}", cleaned))
    if query_tokens:
        best_staff: str = ""
        best_staff_score = 0.0
        best_faculty: str = ""
        best_faculty_score = 0.0

        try:
            with db_connection() as conn:
                with conn.cursor() as cursor:
                    cursor.execute("SELECT name FROM staff;")
                    for (name,) in cursor.fetchall():
                        name_tokens = set(re.findall(r"[a-z]{3,}", name.lower()))
                        if name_tokens:
                            score = len(name_tokens & query_tokens) / len(name_tokens)
                            if score >= 0.5 and score > best_staff_score:
                                best_staff_score = score
                                best_staff = name

                    cursor.execute("SELECT name FROM faculty;")
                    for (name,) in cursor.fetchall():
                        name_tokens = set(re.findall(r"[a-z]{3,}", name.lower()))
                        if name_tokens:
                            score = len(name_tokens & query_tokens) / len(name_tokens)
                            if score >= 0.5 and score > best_faculty_score:
                                best_faculty_score = score
                                best_faculty = name

            if best_staff_score >= 0.5 or best_faculty_score >= 0.5:
                detail_keywords = [
                    "detail", "detailed", "more", "everything", "contact", "email",
                    "phone", "address", "full", "information", "info"
                ]
                is_detail_query = any(dk in cleaned for dk in detail_keywords)

                if best_staff_score >= best_faculty_score and best_staff:
                    if is_detail_query:
                        result = get_staff_details_db(best_staff, error_on_empty=False)
                        if result:
                            return result
                    
                    with db_connection() as conn:
                        with conn.cursor() as cursor:
                            cursor.execute(
                                "SELECT name, designation, qualification FROM staff WHERE name = %s;",
                                (best_staff,),
                            )
                            res = cursor.fetchone()
                    if res:
                        s_name, s_desig, s_qual = res
                        qual_str = f" (holding credentials in {s_qual})" if s_qual else ""
                        dl = (s_desig or "").lower()
                        if "it" in dl or "system" in dl or "network" in dl:
                            desc = "managing, maintaining, and supporting the campus IT infrastructure, networks, and computer systems."
                        elif "account" in dl or "finance" in dl or "audit" in dl:
                            desc = "managing financial audits, accounts, salaries, fee collections, and billing operations."
                        elif "library" in dl or "resource" in dl or "librarian" in dl:
                            desc = "managing library books, journals, resource center logs, and academic database cataloguing."
                        elif "placement" in dl or "career" in dl:
                            desc = "coordinating corporate recruitment, placement drives, internships, and student career counseling."
                        elif "hostel" in dl or "warden" in dl or "residential" in dl:
                            desc = "managing campus student housing, hostels, mess facilities, and residential campus guidelines."
                        elif "lab" in dl or "laboratory" in dl or "workshop" in dl:
                            desc = "managing practical lab equipment, maintaining lab schedules, and supporting student workshops."
                        else:
                            desc = f"providing vital {s_desig or 'administrative'} services to support the operations of the institute."
                        return (
                            f"**{s_name}** works at DA-IICT as **{s_desig}**{qual_str}.\n\n"
                            f"Their primary role involves **{desc}**\n\n"
                            f"*(If you need their contact info or full details, just ask for \"details of {s_name.split()[0]}\"!)*"
                        )

                elif best_faculty:
                    if is_detail_query:
                        result = get_faculty_details_db(best_faculty, error_on_empty=False)
                        if result:
                            return result
                            
                    with db_connection() as conn:
                        with conn.cursor() as cursor:
                            cursor.execute(
                                "SELECT name, faculty_type, specialization, education FROM faculty WHERE name = %s;",
                                (best_faculty,),
                            )
                            res = cursor.fetchone()
                    if res:
                        f_name, f_type, f_spec, f_edu = res
                        spec_str = f" specializing in **{f_spec}**" if f_spec else ""
                        edu_str = f" They hold academic qualifications from {f_edu}." if f_edu else ""
                        return (
                            f"**{f_name}** is a **{f_type}** Faculty at DA-IICT{spec_str}.{edu_str}\n\n"
                            f"Their work primarily involves teaching academic courses and conducting "
                            f"advanced research in their fields of specialization.\n\n"
                            f"*(If you need their contact info or full details, just ask for \"details of {f_name.split()[0]}\"!)*"
                        )

        except Exception as e:
            logger.error(f"Named entity matching failed: {e}")

    # ── Pass 1: Intent-Based Category Routing ─────────────────────────────────
    for cat_name, cat in _SUPPORT_CATEGORIES.items():
        if any(re.search(r'\b' + re.escape(kw) + r'\b', cleaned) for kw in cat["keywords"]):
            try:
                with db_connection() as conn:
                    with conn.cursor() as cursor:
                        where = " OR ".join(cat["conditions"])
                        cursor.execute(
                            f"SELECT name, email, phone, address, qualification, "
                            f"designation, profile_url FROM staff WHERE {where} ORDER BY name;"
                        )
                        rows = cursor.fetchall()
                if rows:
                    out = [f"### {cat['title']}", cat["description"], ""]
                    for i, (name, email, phone, addr, qual, desig, url) in enumerate(rows, 1):
                        out.append(f"#### {i}. {name}")
                        if desig: out.append(f"- **Designation/Role:** {desig}")
                        if email: out.append(f"- **Email:** {email}")
                        if phone: out.append(f"- **Phone:** {phone}")
                        if addr:  out.append(f"- **Office Address:** {addr}")
                        if qual:  out.append(f"- **Qualification:** {qual}")
                        if url:   out.append(f"- **Profile:** [{url}]({url})")
                        out.append("")
                    return "\n".join(out)
            except Exception as e:
                logger.error(f"Intent routing failed for '{cat_name}': {e}")

    # ── Pass 2: Count Queries ─────────────────────────────────────────────────
    count_kw = ["how many", "total count", "total number", "count of", "number of"]
    entity_kw = ["faculty", "faculties", "member", "members", "professor", "professors", "staff"]
    if any(k in cleaned for k in count_kw) and any(k in cleaned for k in entity_kw):
        try:
            is_staff = "staff" in cleaned and not any(k in cleaned for k in ["faculty", "faculties", "professor"])
            with db_connection() as conn:
                with conn.cursor() as cursor:
                    if is_staff:
                        cursor.execute("SELECT COUNT(*) FROM staff;")
                        return f"There are currently **{cursor.fetchone()[0]} staff members** in the DA-IICT database."
                    cursor.execute("SELECT COUNT(*) FROM faculty;")
                    total = cursor.fetchone()[0]
                    cursor.execute("SELECT faculty_type, COUNT(*) FROM faculty GROUP BY faculty_type ORDER BY COUNT(*) DESC;")
                    breakdown = "\n".join(f"- **{ft}**: {cnt}" for ft, cnt in cursor.fetchall())
                    return (
                        f"There are currently **{total} faculty members** in the DA-IICT database.\n\n"
                        f"Breakdown by designation:\n{breakdown}"
                    )
        except Exception as e:
            logger.error(f"Count query failed: {e}")

    # ── Pass 3: Greetings, Help, Appreciation, Farewells ─────────────────────
    if cleaned in ("hi", "hello", "hey", "greetings", "yo"):
        return (
            "Hello! I am your **DA-IICT Faculty & Staff AI Assistant**.\n\n"
            "I can help you search the university directory, locate specialized experts, "
            "find administrative staff, and explore credentials.\n\n"
            "Try asking:\n"
            "- *'Who teaches machine learning?'*\n"
            "- *'Who is the registrar's executive?'*\n"
            "- *'Give me details of Abhilash Kumar Bhaskaran'*"
        )

    if cleaned in ("help", "what can you do", "commands"):
        return (
            "Here is what I can do for you:\n\n"
            "1. **Discover Experts**: *'Who teaches machine learning?'* or *'Who is specialized in VLSI?'*\n"
            "2. **Detailed Profiles**: *'Tell me about Prof. Vishvajit Pandya'*\n"
            "3. **General Search**: Any term like *'PhD from IIT Bombay'* or *'Finance'*\n"
            "4. **Directories**: *'list all faculty'* or *'list all staff'*"
        )

    appreciation_phrases = [
        "great work", "good job", "doing great", "very helpful", "so helpful",
         "awesome", "perfect", "superb",
        "wonderful", "excellent", "brilliant", "amazing", "cool", "nice", "ty",
        "you are best", "you are the best", "you're the best", "you're best",
        "best bot", "good bot", "smart bot", "love you"
    ]
    if any(re.search(r'\b' + re.escape(p) + r'\b', cleaned) for p in appreciation_phrases):
        return (
            "Thank you so much! I'm glad I could be of assistance. "
            "Feel free to ask if you need any other information about DA-IICT faculty or staff!"
        )

    acknowledgment_phrases = [
        "ok", "okay", "okkay", "done", "got it", "understood", "thank you", "thanks", "thankyou", "alright", "sure", "fine", "kk"
    ]
    # Check exact match or if the entire cleaned string only consists of an acknowledgment
    if cleaned in acknowledgment_phrases or any(re.search(r'^' + re.escape(p) + r'$', cleaned) for p in acknowledgment_phrases):
        return "You're welcome! Let me know if you need anything else."

    if any(k in cleaned for k in ["who are you", "what are you", "about you"]):
        return (
            "I am the **DA-IICT Faculty & Staff AI Assistant**! My job is to help you search "
            "and find people across the Dhirubhai Ambani Institute of Information and Communication Technology."
        )
        
    if any(k in cleaned for k in ["how are you", "how are you doing", "what's up", "whats up"]):
        return (
            "I'm functioning perfectly, thank you for asking! How can I assist you in finding "
            "DA-IICT faculty or staff today?"
        )
        
    if any(k in cleaned for k in ["who am i", "what is my name", "whats my name"]):
        return (
            "I don't actually know your name! I am a privacy-first assistant designed solely "
            "to help you search the DA-IICT university directory."
        )

    closing_phrases = ["bye", "goodbye", "see you", "see ya", "exit", "quit"]
    if any(re.search(r'\b' + re.escape(p) + r'\b', cleaned) for p in closing_phrases):
        return "Goodbye! Have a wonderful day, and don't hesitate to reach out anytime!"

    # ── Pass 4: Directory Shortcuts ───────────────────────────────────────────
    if any(k in cleaned for k in ["list all staff", "show all staff", "staff directory", "all staff"]):
        return list_all_staff_db()

    if any(k in cleaned for k in ["list all", "show all", "directory", "all faculty", "all faculties"]) and \
       not any(k in cleaned for k in ["specializ", "expert", "teach", "research", "subject"]):
        return list_all_faculty_db()

    # ── Pass 5: Profile-Phrase Extraction ────────────────────────────────────
    profile_match = re.search(
        r"(?:profile of|details of|tell me about|who is|about)\s+([a-zA-Z\s\.\-_]+)", cleaned
    )
    if profile_match:
        name = re.sub(r"^(?:prof(?:essor)?|dr)\.?\s+", "", profile_match.group(1).strip())
        r = get_faculty_details_db(name, error_on_empty=False)
        if r: return r
        r = get_staff_details_db(name, error_on_empty=False)
        if r: return r

    # ── Pass 5b: Exact Designation Match ─────────────────────────────────────
    extracted = _extract_topic(prompt)
    if extracted:
        role_clean = re.sub(r"^(?:the|a|an)\s+", "", extracted.lower())
        if len(role_clean) > 3:
            try:
                with db_connection() as conn:
                    with conn.cursor() as cursor:
                        cursor.execute(
                            "SELECT name, designation, email, phone FROM staff WHERE designation ILIKE %s ORDER BY name;",
                            (f"%{role_clean}%",)
                        )
                        rows = cursor.fetchall()
                        if rows:
                            out = [f"### Staff matching role: '{role_clean}'", f"Found {len(rows)} record(s):", ""]
                            for i, (s_name, s_desig, s_email, s_phone) in enumerate(rows, 1):
                                out.append(f"#### {i}. {s_name}")
                                if s_desig: out.append(f"- **Designation/Role:** {s_desig}")
                                if s_email: out.append(f"- **Email:** {s_email}")
                                if s_phone: out.append(f"- **Phone:** {s_phone}")
                                out.append("")
                            return "\n".join(out)
            except Exception as e:
                logger.error(f"Pass 5b Exact Designation Match failed: {e}")

    # ── Pass 6: Topic Extraction + DB Search ─────────────────────────────────
    extracted = _extract_topic(prompt)
    if extracted and extracted != cleaned:
        name_clean = re.sub(r"^(?:prof(?:essor)?|dr)\.?\s+", "", extracted)
        r = get_faculty_details_db(name_clean, error_on_empty=False)
        if r: return r
        
        r = get_staff_details_db(name_clean, error_on_empty=False)
        if r: return r
        
        r = search_faculty_by_expertise_db(extracted, error_on_empty=False)
        if r: return r
        
        fac_r = search_faculty_db(extracted, error_on_empty=False)
        staff_r = search_staff_db(extracted, error_on_empty=False)
        if fac_r and staff_r:
            return fac_r + "\n\n---\n\n" + staff_r
        if fac_r: return fac_r
        if staff_r: return staff_r

    # ── Pass 7: Specialization Regex ─────────────────────────────────────────
    spec_match = re.search(
        r"(?:specializ[a-zA-Z]*|expert|teaches|faculty for|know about|study|learn|research in)"
        r"\s+(?:in|for|of|is)?\s*([a-zA-Z\s\-]+)",
        cleaned,
    )
    if spec_match:
        topic = spec_match.group(1).strip()
        if topic and topic not in ("faculty", "expertise", "specialization", "teaching", "research"):
            return search_faculty_by_expertise_db(topic, error_on_empty=True)

    # ── Pass 8: Raw Full-Text Fallback ────────────────────────────────────────
    fac_r = search_faculty_db(prompt, error_on_empty=False)
    staff_r = search_staff_db(prompt, error_on_empty=False)
    
    if fac_r and staff_r:
        return fac_r + "\n\n---\n\n" + staff_r
    if fac_r: return fac_r
    if staff_r: return staff_r

    return search_faculty_db(prompt, error_on_empty=True)
