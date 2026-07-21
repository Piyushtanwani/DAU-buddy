import os
import yaml
import hashlib
import requests
import psycopg2
import pdfplumber
import logging
from typing import Dict, List, Any
import sys

# Add parent dir to path and load .env (same as other seed scripts)
_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _root)
try:
    from dotenv import load_dotenv
    load_dotenv(dotenv_path=os.path.join(_root, ".env"), override=True)
except ImportError:
    pass  # dotenv not installed; rely on environment variables


from connectors.apache_directory_connector import ApacheDirectoryConnector
from parsers.document_metadata_parser import DocumentMetadataParser

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

DB_USER = os.getenv("DB_USER", "postgres")
DB_PASS = os.getenv("DB_PASSWORD", "postgres")
DB_HOST = os.getenv("DB_HOST", "localhost")
DB_NAME = os.getenv("DB_NAME", "daiict_db")
DB_PORT = os.getenv("DB_PORT", "5432")

def get_db_connection():
    return psycopg2.connect(
        dbname=DB_NAME,
        user=DB_USER,
        password=DB_PASS,
        host=DB_HOST,
        port=DB_PORT
    )

def calculate_checksum(file_path: str) -> str:
    sha256 = hashlib.sha256()
    with open(file_path, 'rb') as f:
        while True:
            data = f.read(65536)
            if not data:
                break
            sha256.update(data)
    return sha256.hexdigest()

def ensure_directory(path: str):
    if not os.path.exists(path):
        os.makedirs(path)

def download_file(url: str, dest_path: str) -> bool:
    try:
        response = requests.get(url, stream=True, timeout=30)
        response.raise_for_status()
        with open(dest_path, 'wb') as f:
            for chunk in response.iter_content(chunk_size=8192):
                f.write(chunk)
        return True
    except Exception as e:
        logger.error(f"Failed to download {url}: {e}")
        return False

def extract_pdf_chunks(pdf_path: str) -> List[Dict]:
    chunks = []
    try:
        with pdfplumber.open(pdf_path) as pdf:
            for page_num, page in enumerate(pdf.pages, 1):
                text = page.extract_text()
                
                # Extract tables and flatten them
                tables = page.extract_tables()
                table_text = ""
                for table in tables:
                    for row in table:
                        clean_row = [str(cell).strip() if cell else "" for cell in row]
                        table_text += " | ".join(clean_row) + "\n"
                
                combined_text = text if text else ""
                if table_text:
                    combined_text += "\n\n[Tables]\n" + table_text

                # Paragraph chunking (simple split by double newline)
                paragraphs = [p.strip() for p in combined_text.split('\n\n') if p.strip()]
                
                for idx, para in enumerate(paragraphs):
                    chunks.append({
                        'page': page_num,
                        'chunk_index': idx,
                        'content': para,
                        'section_heading': None # Hard to robustly extract section headings without ML, leaving null for now
                    })
    except Exception as e:
        logger.error(f"Error extracting PDF {pdf_path}: {e}")
    return chunks

def sync_collection(collection_config: dict):
    collection_id = collection_config['id']
    base_url = collection_config['url']
    prefix = collection_config.get('filename_prefix')
    
    logger.info(f"Syncing collection: {collection_id}")
    
    data_dir = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'data', 'documents', collection_id)
    ensure_directory(data_dir)
    
    connector = ApacheDirectoryConnector(url=base_url, filename_prefix=prefix)
    parser = DocumentMetadataParser(collection_id=collection_id)
    
    conn = get_db_connection()
    cursor = conn.cursor()
    
    # Track documents to update versioning later
    synced_programs = set()
    
    try:
        for file_info in connector.crawl():
            url = file_info['url']
            filename = file_info['filename']
            
            # Check DB for existing file
            cursor.execute("SELECT id, checksum, last_modified FROM documents WHERE collection = %s AND filename = %s", (collection_id, filename))
            existing_doc = cursor.fetchone()
            
            # Metadata
            meta = parser.parse(filename)
            
            # Download to local
            local_path = os.path.join(data_dir, filename)
            
            # We always download if it doesn't exist locally, or if we suspect it changed.
            temp_path = local_path + ".tmp"
            if not download_file(url, temp_path):
                continue
                
            new_checksum = calculate_checksum(temp_path)
            
            needs_indexing = True
            if existing_doc and os.path.exists(local_path):
                old_checksum = existing_doc[1]
                if new_checksum == old_checksum:
                    needs_indexing = False
                    logger.info(f"Skipping {filename}, checksum matches.")
            
            if needs_indexing:
                os.replace(temp_path, local_path)
                logger.info(f"Indexing {filename}...")
                
                chunks = extract_pdf_chunks(local_path)
                page_count = max([c['page'] for c in chunks]) if chunks else 0
                
                if existing_doc:
                    doc_id = existing_doc[0]
                    # Update doc
                    cursor.execute("""
                        UPDATE documents SET 
                            title = %s, url = %s, degree = %s, program = %s, 
                            effective_year = %s, version = %s, last_modified = %s, 
                            synced_at = CURRENT_TIMESTAMP, page_count = %s, checksum = %s
                        WHERE id = %s
                    """, (
                        meta['title'], url, meta['degree'], meta['program'],
                        meta['effective_year'], meta['version'], file_info.get('last_modified_hint'),
                        page_count, new_checksum, doc_id
                    ))
                    # Delete old chunks
                    cursor.execute("DELETE FROM document_chunks WHERE document_id = %s", (doc_id,))
                else:
                    # Insert new doc
                    cursor.execute("""
                        INSERT INTO documents (collection, filename, title, url, degree, program, effective_year, version, last_modified, page_count, checksum)
                        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                        RETURNING id
                    """, (
                        collection_id, filename, meta['title'], url, meta['degree'], meta['program'],
                        meta['effective_year'], meta['version'], file_info.get('last_modified_hint'),
                        page_count, new_checksum
                    ))
                    doc_id = cursor.fetchone()[0]
                
                # Insert new chunks
                for chunk in chunks:
                    cursor.execute("""
                        INSERT INTO document_chunks (document_id, page, section_heading, chunk_index, content)
                        VALUES (%s, %s, %s, %s, %s)
                    """, (
                        doc_id, chunk['page'], chunk['section_heading'], chunk['chunk_index'], chunk['content']
                    ))
                
                conn.commit()
                if meta['program']:
                    synced_programs.add(meta['program'])
            else:
                if os.path.exists(temp_path):
                    os.remove(temp_path)
        
        # Post-process: Automatic Version Detection
        # For each program we touched, find all documents, sort by effective_year, set is_latest
        if synced_programs:
            logger.info("Updating is_latest flags based on effective_year...")
            for prog in synced_programs:
                cursor.execute("""
                    SELECT id, effective_year FROM documents 
                    WHERE collection = %s AND program = %s AND status = 'active'
                """, (collection_id, prog))
                docs = cursor.fetchall()
                if not docs:
                    continue
                
                # Sort by effective year descending
                sorted_docs = sorted(docs, key=lambda x: str(x[1] or ""), reverse=True)
                latest_id = sorted_docs[0][0]
                
                # Reset all to false
                cursor.execute("UPDATE documents SET is_latest = false WHERE collection = %s AND program = %s", (collection_id, prog))
                # Set latest to true
                cursor.execute("UPDATE documents SET is_latest = true WHERE id = %s", (latest_id,))
            
            conn.commit()
            
    except Exception as e:
        logger.error(f"Sync failed for {collection_id}: {e}")
        conn.rollback()
    finally:
        cursor.close()
        conn.close()

def main():
    config_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'config', 'document_collections.yaml')
    if not os.path.exists(config_path):
        logger.error(f"Config file not found: {config_path}")
        return
        
    with open(config_path, 'r') as f:
        config = yaml.safe_load(f)
        
    for collection in config.get('collections', []):
        sync_collection(collection)

if __name__ == "__main__":
    main()
