#!/usr/bin/env python3
"""
Manual check for chat question logging (#70). LOCAL DATABASES ONLY.

Adds a test API key, sends one question to a running backend and shows
whether exactly one row was added to chat_questions.

    python scripts/manual_check_chat_questions.py [--base-url URL] [--question TEXT]
"""

import argparse
import hashlib
import secrets
import sys

import requests

from core.database import db_connection

TEST_EMAIL = "manual_test@daiict.ac.in"
RAW_KEY = "dau_sk_" + secrets.token_urlsafe(24)


def count_rows(cursor) -> int:
    cursor.execute("SELECT COUNT(*) FROM chat_questions")
    return cursor.fetchone()[0]


def remove_test_key() -> None:
    """Delete the test key's row, so no usable credential outlives the run."""
    with db_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("DELETE FROM api_keys WHERE email = %s", (TEST_EMAIL,))


def main() -> int:
    parser = argparse.ArgumentParser(description="Check chat question logging.")
    parser.add_argument("--base-url", default="http://127.0.0.1:8000")
    parser.add_argument("--question", default="When is the next holiday?")
    args = parser.parse_args()

    hashed = hashlib.sha256(RAW_KEY.encode()).hexdigest()
    with db_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "INSERT INTO api_keys (email, key_prefix, hashed_key, role, status) "
                "VALUES (%s, %s, %s, 'Student', 'Active') "
                "ON CONFLICT (email) DO UPDATE SET hashed_key = EXCLUDED.hashed_key, status = 'Active'",
                (TEST_EMAIL, RAW_KEY[:11], hashed),
            )
            before = count_rows(cur)

    try:
        try:
            resp = requests.post(
                f"{args.base_url}/api/chat",
                json={"message": args.question, "history": []},
                headers={"Authorization": f"Bearer {RAW_KEY}"},
                timeout=120,
            )
        except requests.exceptions.ConnectionError:
            print(f"ERROR: cannot reach the backend at {args.base_url}.")
            return 1
        print(f"chat answered: HTTP {resp.status_code}")

        with db_connection() as conn:
            with conn.cursor() as cur:
                after = count_rows(cur)
                cur.execute("SELECT id, question, caller_role, created_at FROM chat_questions ORDER BY id DESC LIMIT 1")
                row = cur.fetchone()
        print(f"rows before/after: {before}/{after}")
        if row:
            print(f"newest row: id={row[0]} role={row[2]} created_at={row[3]} question={row[1]!r}")

        ok = resp.status_code == 200 and after - before == 1
        print("PASS: exactly one row added." if ok else "FAIL: expected HTTP 200 and exactly one new row.")
        return 0 if ok else 1
    finally:
        # Runs on every exit — PASS, FAIL, unreachable backend, Ctrl-C.
        remove_test_key()


if __name__ == "__main__":
    sys.exit(main())
