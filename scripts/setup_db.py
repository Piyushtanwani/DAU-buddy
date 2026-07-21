"""
setup_db.py — Master Database Setup Script
==========================================
Runs all seed scripts in the correct order for a fresh environment
OR to refresh data on the production server (mcp.dau.ac.in).

Usage:
    python scripts/setup_db.py                  # full setup
    python scripts/setup_db.py --skip-library   # skip the slow 28k-book seed
    python scripts/setup_db.py --only timetable # run just the timetable steps

Safe to re-run: each seed script is idempotent.
"""
import subprocess
import sys
import os
import argparse
import time

SCRIPTS = os.path.dirname(os.path.abspath(__file__))
ROOT    = os.path.dirname(SCRIPTS)
PYTHON  = sys.executable

# Colour helpers (degrade gracefully on Windows without ANSI)
def _c(code, text):
    try:
        return f"\033[{code}m{text}\033[0m"
    except Exception:
        return text

OK   = lambda t: _c("32;1", f"[OK]   {t}")
FAIL = lambda t: _c("31;1", f"[FAIL] {t}")
INFO = lambda t: _c("34",   f"[....] {t}")
SKIP = lambda t: _c("33",   f"[SKIP] {t}")


def run(script_name: str, label: str) -> bool:
    path = os.path.join(SCRIPTS, script_name)
    if not os.path.exists(path):
        print(FAIL(f"{label} - script not found: {path}"))
        return False

    print(INFO(f"{label} ..."))
    t0 = time.time()
    result = subprocess.run(
        [PYTHON, path],
        cwd=ROOT,
        capture_output=False,
    )
    elapsed = round(time.time() - t0, 1)

    if result.returncode == 0:
        print(OK(f"{label} completed in {elapsed}s"))
        return True
    else:
        print(FAIL(f"{label} failed (exit {result.returncode}) after {elapsed}s"))
        return False


def run_sql(sql_file: str, label: str) -> bool:
    """Run a .sql file via psycopg2 (or psql fallback) using env vars."""
    db_host = os.getenv("DB_HOST", "localhost")
    db_port = os.getenv("DB_PORT", "5432")
    db_name = os.getenv("DB_NAME", "daiict_db")
    db_user = os.getenv("DB_USER", "postgres")
    db_pass = os.getenv("DB_PASSWORD", "root")

    path = os.path.join(SCRIPTS, sql_file)
    if not os.path.exists(path):
        print(FAIL(f"{label} - file not found: {path}"))
        return False

    print(INFO(f"{label} ..."))

    # 1. Try psycopg2 directly (works anywhere without requiring psql in PATH)
    try:
        import psycopg2
        with open(path, "r", encoding="utf-8") as f:
            sql_script = f.read()

        conn = psycopg2.connect(
            dbname=db_name, user=db_user, password=db_pass, host=db_host, port=db_port
        )
        conn.autocommit = True
        with conn.cursor() as cur:
            cur.execute(sql_script)
        conn.close()
        print(OK(f"{label} completed"))
        return True
    except Exception:
        pass

    # 2. Fallback to psql CLI command
    import shutil
    psql_cmd = shutil.which("psql")
    if not psql_cmd and sys.platform == "win32":
        for version in ["17", "16", "15", "14", "13", "12"]:
            candidate = f"C:\\Program Files\\PostgreSQL\\{version}\\bin\\psql.exe"
            if os.path.exists(candidate):
                psql_cmd = candidate
                break

    if psql_cmd:
        env = os.environ.copy()
        env["PGPASSWORD"] = db_pass
        result = subprocess.run(
            [psql_cmd, "-h", db_host, "-p", db_port, "-U", db_user, "-d", db_name, "-f", path],
            cwd=ROOT,
            env=env,
            capture_output=False,
        )
        if result.returncode == 0:
            print(OK(f"{label} completed"))
            return True
        else:
            print(FAIL(f"{label} failed (exit {result.returncode})"))
            return False

    print(FAIL(f"{label} failed: could not execute SQL via psycopg2 or psql CLI."))
    return False


def load_dotenv_if_available():
    try:
        from dotenv import load_dotenv
        env_path = os.path.join(ROOT, ".env")
        if os.path.exists(env_path):
            load_dotenv(dotenv_path=env_path, override=True)
            print(INFO("Loaded .env"))
    except ImportError:
        pass


def main():
    parser = argparse.ArgumentParser(description="DAU Buddy - Database Setup")
    parser.add_argument("--skip-library",  action="store_true", help="Skip the slow 28k-book library seed")
    parser.add_argument("--skip-documents",action="store_true", help="Skip document PDF indexing")
    parser.add_argument("--only", choices=["schema","faculty","staff","library",
                                           "calendar","scholars","timetable","documents","all"],
                        default="all", help="Run only a specific step")
    args = parser.parse_args()

    load_dotenv_if_available()

    print(_c("34;1", "\n+------------------------------------------+"))
    print(_c("34;1",   "|   DAU Buddy - Database Setup             |"))
    print(_c("34;1",   "+------------------------------------------+\n"))

    only = args.only
    failures = []

    def step(name, fn, *a, **kw):
        if only not in ("all", name):
            print(SKIP(f"{name} (not selected)"))
            return
        if not fn(*a, **kw):
            failures.append(name)

    # ── 1. Schema ──────────────────────────────────────────────────────────────
    step("schema", run_sql, "init_db.sql", "Schema - init_db.sql")

    # ── 2. People ──────────────────────────────────────────────────────────────
    step("faculty",  run, "seed_faculty.py",  "Faculty")
    step("staff",    run, "seed_staff.py",    "Staff")
    step("scholars", run, "seed_scholars.py", "Doctoral scholars")

    # ── 3. Library (slow) ──────────────────────────────────────────────────────
    if args.skip_library:
        print(SKIP("Library (--skip-library)"))
    else:
        step("library", run, "seed_library.py", "Library (28k books - may take ~60s)")

    # ── 4. Calendar ────────────────────────────────────────────────────────────
    step("calendar", run, "seed_calendar.py", "Academic & holiday calendar")

    # ── 5. Timetable ───────────────────────────────────────────────────────────
    step("timetable", run, "seed_timetable.py", "Timetable (Active Excel dataset)")

    # ── 6. Documents (PDF indexing) ────────────────────────────────────────────
    if args.skip_documents:
        print(SKIP("Documents (--skip-documents)"))
    else:
        step("documents", run, "seed_documents.py", "Academic requirement PDFs")

    # ── Summary ────────────────────────────────────────────────────────────────
    print(_c("34;1", "\n+------------------------------------------+"))
    if failures:
        print(_c("31;1", f"|  Setup finished with {len(failures)} failure(s)          |"))
        print(_c("34;1",  "+------------------------------------------+"))
        print(_c("31", f"   Failed steps: {', '.join(failures)}"))
        sys.exit(1)
    else:
        print(_c("32;1",  "|  Setup complete - all steps passed       |"))
        print(_c("34;1",  "+------------------------------------------+\n"))


if __name__ == "__main__":
    main()
