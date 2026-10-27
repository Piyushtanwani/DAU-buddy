#!/usr/bin/env python3
"""
Export chat_questions rows to CSV for labelling.

Usage:
    python scripts/export_questions.py                  # writes to stdout
    python scripts/export_questions.py -o questions.csv # writes to file
    python scripts/export_questions.py --role student   # filter by caller_role
"""

import argparse
import csv
import sys

from core.database import db_connection


def safe_cell(value):
    """Prefix cells that spreadsheets would run as formulas."""
    if isinstance(value, str) and value[:1] in ("=", "+", "-", "@", "\t", "\r"):
        return "'" + value
    return value


def export_questions(*, out_path: str | None = None, role: str | None = None) -> None:
    """Fetch all chat_questions rows and write them as CSV."""
    query = "SELECT id, question, caller_role, created_at FROM chat_questions"
    params: list[str] = []

    if role:
        query += " WHERE caller_role = %s"
        params.append(role)

    query += " ORDER BY created_at, id"

    with db_connection() as conn:
        with conn.cursor() as cursor:
            cursor.execute(query, params or None)
            rows = cursor.fetchall()
            col_names = [desc[0] for desc in cursor.description]

    dest = open(out_path, "w", newline="", encoding="utf-8") if out_path else sys.stdout

    try:
        writer = csv.writer(dest)
        writer.writerow(col_names)
        writer.writerows([[safe_cell(v) for v in row] for row in rows])
    finally:
        if dest is not sys.stdout:
            dest.close()

    count = len(rows)
    target = out_path or "stdout"
    print(f"Exported {count} question(s) to {target}", file=sys.stderr)


def main() -> None:
    parser = argparse.ArgumentParser(description="Export chat_questions to CSV")
    parser.add_argument("-o", "--output", default=None, help="Output CSV file path (default: stdout)")
    parser.add_argument("--role", default=None, choices=["student", "faculty", "staff"],
                        help="Filter by caller_role")
    args = parser.parse_args()
    export_questions(out_path=args.output, role=args.role)


if __name__ == "__main__":
    main()
