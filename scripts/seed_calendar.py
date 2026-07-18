import os
import sys
import logging
import requests
import pdfplumber
import pandas as pd
from bs4 import BeautifulSoup
import re
from datetime import datetime
import psycopg2.extras

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from core import config
from core.database import db_connection

logger = config.get_logger("scripts.seed_calendar")

HOLIDAY_PDF_URL = "https://www.daiict.ac.in/sites/default/files/other-files/DAU_Holiday-List-2026.pdf"
ACADEMIC_CAL_URL = "https://www.daiict.ac.in/academic-calendar"

def parse_date(date_str: str, year: int = 2026):
    """Attempts to parse a date string like 'August 15', '15-Aug', '20-07-2026' into a DATE object."""
    date_str = date_str.strip()
    try:
        if str(year) not in date_str and not re.search(r'\d{4}', date_str):
            date_str = f"{date_str} {year}"
        
        for fmt in ["%d %B %Y", "%d %b %Y", "%B %d %Y", "%b %d %Y", "%d-%b-%Y", "%d-%m-%Y"]:
            try:
                dt = datetime.strptime(date_str, fmt)
                return dt.date()
            except ValueError:
                pass
    except Exception:
        pass
    return None

def extract_dates_from_range(date_str: str, year: int = 2026):
    """Extract start and end date from strings like '15 - 20 August' or '06-07-2026 to 17-07-2026'"""
    date_str = date_str.replace("to", " to ").strip()
    # Normalize spaces
    date_str = ' '.join(date_str.split())
    
    parts = []
    if " to " in date_str:
        parts = date_str.split(" to ")
    else:
        parts = [date_str]
        
    if len(parts) == 1:
        dt = parse_date(parts[0], year)
        return dt, dt
    elif len(parts) == 2:
        d1, d2 = parts[0].strip(), parts[1].strip()
        dt1 = parse_date(d1, year)
        dt2 = parse_date(d2, year)
        # If dt1 failed because it didn't have year/month, we can try to extract from d2 if needed,
        # but for DD-MM-YYYY it's fully qualified.
        return dt1, dt2
    return None, None

def seed_holidays(conn):
    logger.info("Seeding 2026 DA-IICT Holidays...")
    
    holidays = [
        ("2026-01-01", "Christian New Year Day", "Thursday", "01 January 2026"),
        ("2026-01-14", "Makar Sankranti", "Wednesday", "14 January 2026"),
        ("2026-01-26", "Republic Day", "Monday", "26 January 2026"),
        ("2026-03-04", "Holi/Dhuleti", "Wednesday", "04 March 2026"),
        ("2026-03-26", "Shree Ram Navmi", "Thursday", "26 March 2026"),
        ("2026-03-31", "Mahavir Jayanti", "Tuesday", "31 March 2026"),
        ("2026-04-03", "Good Friday", "Friday", "03 April 2026"),
        ("2026-04-14", "Dr. Baba Saheb Ambedkar's Birthday", "Tuesday", "14 April 2026"),
        ("2026-05-01", "Buddha Purnima", "Friday", "01 May 2026"),
        ("2026-05-27", "Eid-UI-Adha (Bakri-Eid)", "Wednesday", "27 May 2026"),
        ("2026-06-26", "Muharram", "Friday", "26 June 2026"),
        ("2026-08-28", "Raksha Bandhan", "Friday", "28 August 2026"),
        ("2026-09-04", "Janmashtami", "Friday", "04 September 2026"),
        ("2026-10-02", "Mahatma Gandhi's Birthday", "Friday", "02 October 2026"),
        ("2026-10-20", "Dusshera (Vijaya Dashmi)", "Tuesday", "20 October 2026"),
        ("2026-11-10", "Vikram Samvant New Year Day", "Tuesday", "10 November 2026"),
        ("2026-11-11", "Bhai Bij", "Wednesday", "11 November 2026"),
        ("2026-11-24", "Guru Nanak's Birthday", "Tuesday", "24 November 2026"),
        ("2026-12-25", "Christmas", "Friday", "25 December 2026"),
        # Weekend Holidays
        ("2026-02-15", "Maha Shivratri", "Sunday", "15 February 2026"),
        ("2026-03-21", "Ramjan-Eid", "Saturday", "21 March 2026"),
        ("2026-08-15", "Independence Day & Parsi New Year", "Saturday", "15 August 2026"),
        ("2026-11-08", "Diwali", "Sunday", "08 November 2026")
    ]
    
    try:
        insert_query = """
            INSERT INTO holiday_calendar (
                holiday_date, holiday_name, day_of_week, raw_date_text
            ) VALUES %s
        """
        with conn.cursor() as cur:
            cur.execute("TRUNCATE TABLE holiday_calendar;")
            psycopg2.extras.execute_values(cur, insert_query, holidays, page_size=100)
        logger.info(f"Inserted {len(holidays)} holiday records.")
    except Exception as e:
        logger.error(f"Error seeding holidays: {e}")

def seed_academic_calendar(conn):
    logger.info("Downloading Academic Calendar HTML...")
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'
    }
    try:
        response = requests.get(ACADEMIC_CAL_URL, headers=headers, verify=False)
        response.raise_for_status()
        soup = BeautifulSoup(response.text, "html.parser")
        
        # Often academic calendar tables are present
        tables = soup.find_all("table")
        records = []
        
        semester_type = "Current Semester" # Fallback
        
        for table in tables:
            # Check if there is a caption or previous heading
            prev_h = table.find_previous(['h2', 'h3', 'h4'])
            if prev_h:
                semester_type = prev_h.get_text(strip=True)
                
            rows = table.find_all("tr")
            for row in rows:
                cols = row.find_all(["td", "th"])
                cols = [c.get_text(strip=True) for c in cols]
                if len(cols) >= 3:
                    if "Sr." in cols[0] or "Year" in cols[0] or "Event" in cols[1]:
                        continue
                        
                    event_str = cols[1]
                    date_str = cols[2]
                    
                    start_date, end_date = extract_dates_from_range(date_str, 2026)
                    
                    records.append((
                        event_str,
                        start_date,
                        end_date,
                        date_str,
                        semester_type,
                        "", # description
                        ACADEMIC_CAL_URL
                    ))
                    
        if records:
            insert_query = """
                INSERT INTO academic_calendar (
                    event_name, start_date, end_date, raw_date_text, semester_type, description, source_url
                ) VALUES %s
            """
            with conn.cursor() as cur:
                cur.execute("TRUNCATE TABLE academic_calendar;")
                psycopg2.extras.execute_values(cur, insert_query, records, page_size=100)
            logger.info(f"Inserted {len(records)} academic calendar records.")
        else:
            logger.warning("No academic calendar records found.")
            
    except Exception as e:
        logger.error(f"Error seeding academic calendar: {e}")

def main():
    try:
        with db_connection() as conn:
            seed_holidays(conn)
            seed_academic_calendar(conn)
            conn.commit()
            
        logger.info("Successfully seeded all calendar data.")
    except Exception as e:
        logger.error(f"Failed to seed calendar data: {e}")

if __name__ == "__main__":
    import urllib3
    urllib3.disable_warnings()
    main()
