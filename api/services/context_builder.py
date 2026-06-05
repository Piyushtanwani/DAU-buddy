"""
Context Builder Service
=======================
Transforms raw database rows/dictionaries into clean, token-efficient
structured text for the Gemini RAG prompt.
"""
from typing import List, Dict, Any

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
