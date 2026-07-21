"""
setup_db.py — Master Database Setup Script
==========================================
Runs all seed scripts in the correct order for a fresh environment
OR to refresh data on the production server (mcp.dau.ac.in).

Usage:
    python setup_db.py                  # full setup
    python setup_db.py --skip-library   # skip the slow 28k-book seed
    python setup_db.py --only timetable # run just the timetable steps

Safe to re-run: each seed script is idempotent (upsert/truncate-then-insert).

⚠️  seed_timetable.py TRUNCATES the timetable table, so seed_timetable_autumn.py
    must ALWAYS run after it. This script enforces that order automatically.
"""
import subprocess
import sys
import os
import argparse
import time

ROOT = os.path.dirname(os.path.abspath(__file__))
SCRIPTS = os.path.join(ROOT, "scripts")
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
        print(FAIL(f"{label} — script not found: {path}"))
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
    """Run a .sql file via psql using env vars from .env / environment."""
    # Load .env for psql credentials
    db_host = os.getenv("DB_HOST", "localhost")
    db_port = os.getenv("DB_PORT", "5432")
    db_name = os.getenv("DB_NAME", "daiict_db")
    db_user = os.getenv("DB_USER", "postgres")
    db_pass = os.getenv("DB_PASSWORD", "root")

    path = os.path.join(SCRIPTS, sql_file)
    if not os.path.exists(path):
        print(FAIL(f"{label} — file not found: {path}"))
        return False

    print(INFO(f"{label} ..."))
    env = os.environ.copy()
    env["PGPASSWORD"] = db_pass

    result = subprocess.run(
        ["psql", "-h", db_host, "-p", db_port, "-U", db_user, "-d", db_name, "-f", path],
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
    parser = argparse.ArgumentParser(description="DAU Buddy — Database Setup")
    parser.add_argument("--skip-library",  action="store_true", help="Skip the slow 28k-book library seed")
    parser.add_argument("--skip-documents",action="store_true", help="Skip document PDF indexing")
    parser.add_argument("--only", choices=["schema","faculty","staff","library",
                                           "calendar","scholars","timetable","documents","all"],
                        default="all", help="Run only a specific step")
    args = parser.parse_args()

    load_dotenv_if_available()

    print(_c("34;1", "\n╔══════════════════════════════════════════╗"))
    print(_c("34;1",   "║   DAU Buddy — Database Setup             ║"))
    print(_c("34;1",   "╚══════════════════════════════════════════╝\n"))

    only = args.only
    failures = []

    def step(name, fn, *a, **kw):
        if only not in ("all", name):
            print(SKIP(f"{name} (not selected)"))
            return
        if not fn(*a, **kw):
            failures.append(name)

    # ── 1. Schema ──────────────────────────────────────────────────────────────
    step("schema", run_sql, "init_db.sql", "Schema — init_db.sql")

    # ── 2. People ──────────────────────────────────────────────────────────────
    step("faculty",  run, "seed_faculty.py",  "Faculty")
    step("staff",    run, "seed_staff.py",    "Staff")
    step("scholars", run, "seed_scholars.py", "Doctoral scholars")

    # ── 3. Library (slow) ──────────────────────────────────────────────────────
    if args.skip_library:
        print(SKIP("Library (--skip-library)"))
    else:
        step("library", run, "seed_library.py", "Library (28k books — may take ~60s)")

    # ── 4. Calendar ────────────────────────────────────────────────────────────
    step("calendar", run, "seed_calendar.py", "Academic & holiday calendar")

    # ── 5. Timetable — ORDER MATTERS: spring first, then autumn ───────────────
    if only in ("all", "timetable"):
        print(_c("33", "\n  [Timetable] Spring/base term first ..."))
        if not run("seed_timetable.py", "Timetable — Spring term (base)"):
            failures.append("timetable-spring")
        print(_c("33", "  [Timetable] Autumn 2026-27 on top ..."))
        if not run("seed_timetable_autumn.py", "Timetable — Autumn 2026-27"):
            failures.append("timetable-autumn")
    else:
        print(SKIP("Timetable (not selected)"))

    # ── 6. Documents (PDF indexing) ────────────────────────────────────────────
    if args.skip_documents:
        print(SKIP("Documents (--skip-documents)"))
    else:
        step("documents", run, "seed_documents.py", "Academic requirement PDFs")

    # ── Summary ────────────────────────────────────────────────────────────────
    print(_c("34;1", "\n╔══════════════════════════════════════════╗"))
    if failures:
        print(_c("31;1", f"║  Setup finished with {len(failures)} failure(s)          ║"))
        print(_c("34;1",  "╚══════════════════════════════════════════╝"))
        print(_c("31", f"   Failed steps: {', '.join(failures)}"))
        sys.exit(1)
    else:
        print(_c("32;1",  "║  Setup complete — all steps passed ✓     ║"))
        print(_c("34;1",  "╚══════════════════════════════════════════╝\n"))


if __name__ == "__main__":
    main()
