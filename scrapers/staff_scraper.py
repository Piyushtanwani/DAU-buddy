"""
Staff Scraper
=============
Scrapes all DA-IICT staff from the official website and persists the data
into the PostgreSQL `staff` table.
"""
import re
import requests
from bs4 import BeautifulSoup
from psycopg2.extras import execute_values
from requests.adapters import HTTPAdapter
from urllib3.util import Retry
from typing import List, Dict, Any, Optional

from core import config
from core.database import db_connection

logger = config.get_logger("scrapers.staff_scraper")

_STAFF_URL = "https://www.daiict.ac.in/staff"
_BASE_URL  = "https://www.daiict.ac.in"
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
def scrape_staff_data() -> List[Dict[str, Any]]:
    """Scrape DA-IICT staff directory page and return the parsed list."""
    logger.info(f"Fetching staff list from {_STAFF_URL} ...")
    session = _get_session()
    try:
        resp = session.get(_STAFF_URL, headers={"User-Agent": _USER_AGENT}, timeout=15)
        resp.raise_for_status()
    except Exception as e:
        logger.error(f"Failed to fetch staff page: {e}")
        return []

    soup = BeautifulSoup(resp.text, "html.parser")
    container = soup.find(class_="facultyInformation")
    if not container:
        logger.error("'facultyInformation' element not found in staff page HTML.")
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

        desig_tag = details.find(class_="facultyEducation")   # designation stored here for staff
        qual_tag  = details.find(class_="facultyQualification")
        phone_tag = details.find(class_="facultyNumber")
        addr_tag  = details.find(class_="facultyAddress")
        email_tag = details.find(class_="facultyemail")
        photo_tag = item.find(class_="facultyPhoto")

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
            "designation": desig_tag.get_text(strip=True) if desig_tag else None,
            "qualification": qual_tag.get_text(strip=True) if qual_tag else None,
            "phone": phone_tag.get_text(strip=True) if phone_tag else None,
            "address": _clean_address(addr_tag.get_text(strip=True) if addr_tag else None),
            "email": _clean_email(email_tag.get_text(strip=True) if email_tag else None),
        })

    logger.info(f"Parsed {len(results)} staff members.")
    return results


# ==============================================================================
# Database Persistence
# ==============================================================================
def save_to_database(staff_list: List[Dict[str, Any]]) -> None:
    """Truncate the `staff` table and bulk-insert fresh records."""
    if not staff_list:
        logger.warning("No staff data to save.")
        return

    try:
        with db_connection() as conn:
            with conn.cursor() as cursor:
                cursor.execute("""
                    CREATE TABLE IF NOT EXISTS staff (
                        id            SERIAL PRIMARY KEY,
                        name          VARCHAR(255) NOT NULL,
                        profile_url   TEXT,
                        image_url     TEXT,
                        qualification TEXT,
                        phone         VARCHAR(100),
                        address       TEXT,
                        email         VARCHAR(255),
                        designation   VARCHAR(255),
                        scraped_at    TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                    );
                """)
                cursor.execute("TRUNCATE TABLE staff;")

                execute_values(
                    cursor,
                    """
                    INSERT INTO staff
                        (name, profile_url, image_url, qualification,
                         phone, address, email, designation)
                    VALUES %s;
                    """,
                    [
                        (r["name"], r["profile_url"], r["image_url"], r["qualification"],
                         r["phone"], r["address"], r["email"], r["designation"])
                        for r in staff_list
                    ],
                )
                cursor.execute("SELECT COUNT(*) FROM staff;")
                logger.info(f"Staff table now has {cursor.fetchone()[0]} records.")
    except Exception as e:
        logger.critical(f"Staff DB save failed: {e}")
        raise


if __name__ == "__main__":
    logger.info("Running staff scraper standalone...")
    data = scrape_staff_data()
    save_to_database(data)
    logger.info("Done.")
