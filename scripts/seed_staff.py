"""
Seed Staff Script
=================
One-shot operational script to scrape DA-IICT staff data and seed the database.

Usage:
    python scripts/seed_staff.py
"""
import sys
import os

# Ensure project root is on the path when run from scripts/
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core import config
from scrapers.staff_scraper import scrape_staff_data, save_to_database

logger = config.get_logger("scripts.seed_staff")

if __name__ == "__main__":
    logger.info("=== DA-IICT Staff Seeder ===")
    logger.info("Scraping staff data from the live website...")
    data = scrape_staff_data()
    if not data:
        logger.error("No data scraped. Exiting.")
        sys.exit(1)
    logger.info(f"Scraped {len(data)} staff records. Saving to database...")
    save_to_database(data)
    logger.info("Staff data seeded successfully.")
