"""
Faculty Scraper
===============
Scrapes all DA-IICT faculty categories from the official website and
persists the data into the PostgreSQL `faculty` table.
"""
import re
import datetime
import requests
from bs4 import BeautifulSoup
from psycopg2.extras import execute_values
from requests.adapters import HTTPAdapter
from urllib3.util import Retry
from typing import List, Dict, Any, Optional

from core import config
from core.database import db_connection

logger = config.get_logger("scrapers.faculty_scraper")

# Faculty category pages to scrape
_FACULTY_CATEGORIES = [
    ("https://www.daiict.ac.in/faculty", "Regular"),
    ("https://www.daiict.ac.in/adjunct-faculty", "Adjunct"),
    ("https://www.daiict.ac.in/adjunct-faculty-international", "Adjunct International"),
    ("https://www.daiict.ac.in/distinguished-professor", "Distinguished Professor"),
    ("https://www.daiict.ac.in/professor-practice", "Professor of Practice"),
]

_BASE_URL = "https://www.daiict.ac.in"
_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/91.0.4472.124 Safari/537.36"
)


# ==============================================================================
# Utilities
# ==============================================================================
def _get_session() -> requests.Session:
    """Return a requests session with exponential backoff retry logic."""
    session = requests.Session()
    retry = Retry(
        total=5,
        backoff_factor=1,
        status_forcelist=[429, 500, 502, 503, 504],
        allowed_methods=["HEAD", "GET", "OPTIONS"],
    )
    adapter = HTTPAdapter(max_retries=retry)
    session.mount("https://", adapter)
    session.mount("http://", adapter)
    return session


def _clean_email(raw: Optional[str]) -> Optional[str]:
    if not raw or raw == "N/A":
        return None
    s = raw.strip()
    s = re.sub(r"\[\s*at\s*\]", "@", s, flags=re.IGNORECASE)
    s = re.sub(r"\(\s*at\s*\)", "@", s, flags=re.IGNORECASE)
    s = s.replace("{at}", "@")
    s = re.sub(r"\[\s*dot\s*\]", ".", s, flags=re.IGNORECASE)
    s = re.sub(r"\(\s*dot\s*\)", ".", s, flags=re.IGNORECASE)
    s = s.replace("{dot}", ".")
    s = re.sub(r"\s*@\s*", "@", s)
    s = re.sub(r"\s*\.\s*", ".", s)
    return s


def _clean_address(raw: Optional[str]) -> Optional[str]:
    if not raw or raw == "N/A":
        return None
    s = raw.replace("\ufffd", "-")
    return re.sub(r"\s+", " ", s).strip()


# ==============================================================================
# Scraping Logic
# ==============================================================================
def _scrape_faculty_page(url: str, faculty_type: str) -> List[Dict[str, Any]]:
    """Scrape a single DA-IICT faculty listing page."""
    logger.info(f"Fetching {faculty_type} faculty from {url} ...")
    session = _get_session()
    try:
        resp = session.get(url, headers={"User-Agent": _USER_AGENT}, timeout=15)
        resp.raise_for_status()
    except Exception as e:
        logger.error(f"Failed to fetch {url}: {e}")
        return []

    soup = BeautifulSoup(resp.text, "html.parser")
    container = soup.find(class_="facultyInformation")
    if not container:
        logger.error(f"'facultyInformation' not found in HTML for {url}")
        return []

    results = []
    for item in container.find_all("li"):
        details = item.find(class_="facultyDetails")
        if not details:
            continue

        name_tag = details.find("h3")
        if not name_tag:
            continue
        name = name_tag.get_text(strip=True)

        link = name_tag.find("a")
        profile_url = None
        if link:
            href = link.get("href", "")
            profile_url = (_BASE_URL + href) if href.startswith("/") else (href or None)

        # Resolve actual type (some Adjunct appear on the Regular page)
        resolved_type = faculty_type
        if faculty_type == "Regular" and profile_url and "adjunct-faculty" in profile_url:
            resolved_type = "Adjunct"

        edu_tag  = details.find(class_="facultyEducation")
        phone_tag = details.find(class_="facultyNumber")
        addr_tag = details.find(class_="facultyAddress")
        email_tag = details.find(class_="facultyemail")
        spec_tag  = details.find(class_="areaSpecialization")
        photo_tag = details.find(class_="facultyPhoto")

        img_url = None
        if photo_tag:
            img = photo_tag.find("img")
            if img:
                src = img.get("src", "")
                img_url = (_BASE_URL + src) if src.startswith("/") else (src or None)

        results.append({
            "name": name,
            "profile_url": profile_url,
            "image_url": img_url,
            "education": edu_tag.get_text(strip=True) if edu_tag else None,
            "phone": phone_tag.get_text(strip=True) if phone_tag else None,
            "address": _clean_address(addr_tag.get_text(strip=True) if addr_tag else None),
            "email": _clean_email(email_tag.get_text(strip=True) if email_tag else None),
            "specialization": spec_tag.get_text(strip=True) if spec_tag else None,
            "faculty_type": resolved_type,
        })

    logger.info(f"Parsed {len(results)} {faculty_type} faculty members.")
    return results


def scrape_faculty_data() -> List[Dict[str, Any]]:
    """Scrape all DA-IICT faculty categories and return the combined list."""
    all_faculty: List[Dict[str, Any]] = []
    for url, ftype in _FACULTY_CATEGORIES:
        all_faculty.extend(_scrape_faculty_page(url, ftype))
    logger.info(f"Total faculty scraped: {len(all_faculty)}")
    return all_faculty


# ==============================================================================
# Database Persistence
# ==============================================================================
def save_to_database(faculty_list: List[Dict[str, Any]]) -> None:
    """Truncate the `faculty` table and bulk-insert fresh records."""
    if not faculty_list:
        logger.warning("No faculty data to save.")
        return

    try:
        with db_connection() as conn:
            with conn.cursor() as cursor:
                cursor.execute("""
                    CREATE TABLE IF NOT EXISTS faculty (
                        id            SERIAL PRIMARY KEY,
                        name          VARCHAR(255) NOT NULL,
                        profile_url   TEXT,
                        image_url     TEXT,
                        education     TEXT,
                        phone         VARCHAR(100),
                        address       TEXT,
                        email         VARCHAR(255),
                        specialization TEXT,
                        faculty_type  VARCHAR(50) DEFAULT 'Regular',
                        scraped_at    TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                    );
                """)
                cursor.execute(
                    "ALTER TABLE faculty ADD COLUMN IF NOT EXISTS faculty_type VARCHAR(50) DEFAULT 'Regular';"
                )
                cursor.execute("TRUNCATE TABLE faculty;")

                execute_values(
                    cursor,
                    """
                    INSERT INTO faculty
                        (name, profile_url, image_url, education, phone,
                         address, email, specialization, faculty_type)
                    VALUES %s;
                    """,
                    [
                        (r["name"], r["profile_url"], r["image_url"], r["education"],
                         r["phone"], r["address"], r["email"], r["specialization"],
                         r.get("faculty_type", "Regular"))
                        for r in faculty_list
                    ],
                )
                cursor.execute("SELECT COUNT(*) FROM faculty;")
                logger.info(f"Faculty table now has {cursor.fetchone()[0]} records.")
    except Exception as e:
        logger.critical(f"Faculty DB save failed: {e}")
        raise


if __name__ == "__main__":
    logger.info("Running faculty scraper standalone...")
    data = scrape_faculty_data()
    save_to_database(data)
    logger.info("Done.")
