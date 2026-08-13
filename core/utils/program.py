import re
from typing import List
from core.database import db_connection

# SQL logic must match normalize_program_name exactly
SQL_NORMALIZE_EXPR = "REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(LOWER(program), '.', ''), '-', ''), ' ', ''), '(', ''), ')', '')"

def normalize_program_name(name: str) -> str:
    """
    Normalizes a program name for canonical matching.
    Removes spaces, dots, hyphens, and parentheses, and lowercases the string.
    B.Tech ICT -> btechict
    B Tech (ICT-CS) -> btechictcs
    """
    if not name:
        return ""
    return name.lower().replace(" ", "").replace(".", "").replace("-", "").replace("(", "").replace(")", "")

def get_sql_exact_program_match(column_name: str = "program") -> str:
    """Returns an EXISTS clause that splits the column by commas and exact-matches against the normalized parts."""
    norm = SQL_NORMALIZE_EXPR.replace("program", "prt")
    return f"EXISTS (SELECT 1 FROM unnest(string_to_array({column_name}, ',')) AS prt WHERE {norm} = %s)"

def get_sql_prefix_program_match(column_name: str = "program") -> str:
    """Returns an EXISTS clause that splits the column by commas and prefix-matches against the normalized parts."""
    norm = SQL_NORMALIZE_EXPR.replace("program", "prt")
    return f"EXISTS (SELECT 1 FROM unnest(string_to_array({column_name}, ',')) AS prt WHERE {norm} LIKE %s || '%%')"

def resolve_program(program_name: str) -> List[str]:
    """
    Resolves a requested program name to its canonical name(s) in the database.
    Returns:
      [] if no match
      ["Exact Program"] if exactly one match
      ["Match 1", "Match 2"] if ambiguous
    """
    if not program_name:
        return []
        
    normalized = normalize_program_name(program_name)
    
    with db_connection() as conn:
        with conn.cursor() as cur:
            # Check all distinct programs in the timetables table
            # We filter out electives in the program column (e.g., if a program column has multiple comma-separated,
            # wait, the DB schema has unnest(string_to_array) or we can just fetch all unique strings)
            # For simplicity, let's just fetch all distinct program values and split them if they contain commas
            cur.execute("SELECT DISTINCT program FROM timetables WHERE program IS NOT NULL;")
            rows = cur.fetchall()
            
            unique_db_programs = set()
            for r in rows:
                p_val = r[0]
                # Some elective rows have 'B Tech (ICT and CS), B Tech (ICT and ICT-CS)'
                if "," in p_val:
                    for p_part in p_val.split(","):
                        unique_db_programs.add(p_part.strip())
                else:
                    unique_db_programs.add(p_val.strip())
                    
            matches = []
            for db_prog in unique_db_programs:
                if normalize_program_name(db_prog) == normalized:
                    matches.append(db_prog)
                    
            return sorted(list(set(matches)))
