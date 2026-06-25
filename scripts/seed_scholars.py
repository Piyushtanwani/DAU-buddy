import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from core.database import db_connection
from scrapers.scholars_scraper import scrape_scholars

def seed_scholars():
    scholars = scrape_scholars()
    
    if not scholars:
        print("No scholars found to seed.")
        return

    print("Inserting into database...")
    with db_connection() as conn:
        with conn.cursor() as cur:
            # Clear existing data first
            cur.execute("TRUNCATE TABLE doctoral_scholars RESTART IDENTITY CASCADE;")
            
            for s in scholars:
                cur.execute("""
                    INSERT INTO doctoral_scholars (
                        name, image_url, year_of_joining, year_of_graduation, 
                        advisor, thesis_topic, areas_of_research, publications, 
                        awards, post_phd_employment, personal_webpage
                    ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                """, (
                    s['name'], s['image_url'], s['year_of_joining'], s['year_of_graduation'],
                    s['advisor'], s['thesis_topic'], s['areas_of_research'], s['publications'],
                    s['awards'], s['post_phd_employment'], s['personal_webpage']
                ))
            
            conn.commit()
            print(f"Successfully seeded {len(scholars)} scholars into the database.")

if __name__ == "__main__":
    seed_scholars()
