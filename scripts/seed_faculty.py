"""
Seed Faculty Script
===================
One-shot operational script to scrape DA-IICT faculty data and seed the database.

Usage:
    python scripts/seed_faculty.py
"""
import sys
import os

# Ensure project root is on the path when run from scripts/
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core import config
from scrapers.faculty_scraper import scrape_faculty_data, save_to_database

logger = config.get_logger("scripts.seed_faculty")

if __name__ == "__main__":
    logger.info("=== DA-IICT Faculty Seeder ===")
    logger.info("Scraping faculty data from the live website...")
    data = scrape_faculty_data()
    if not data:
        logger.error("No data scraped. Exiting.")
        sys.exit(1)
    logger.info(f"Scraped {len(data)} faculty records. Saving to database...")
    save_to_database(data)
    logger.info("Faculty data seeded successfully.")
