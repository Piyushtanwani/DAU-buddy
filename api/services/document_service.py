from typing import List, Dict, Any

# Connections come from the shared pool in core.database — this module used to
# open (and leak) its own psycopg2 connections with a duplicate copy of the
# credential handling, which exhausted the server's connection limit.
from core.database import db_connection


class DocumentService:
    @staticmethod
    def search_documents(collection: str, query: str, program: str = None, effective_year: str = None, limit: int = 8) -> List[Dict[str, Any]]:
        with db_connection() as conn, conn.cursor() as cursor:
            # Build query
            sql = """
                SELECT 
                    c.content, d.title, d.program, d.effective_year, c.page, d.url,
                    ts_rank(c.search_vector, websearch_to_tsquery('english', %s)) AS rank
                FROM document_chunks c
                JOIN documents d ON c.document_id = d.id
                WHERE d.collection = %s
                  AND d.status = 'active'
                  AND c.search_vector @@ websearch_to_tsquery('english', %s)
            """
            
            params = [query, collection, query]
            
            if program:
                sql += " AND d.program ILIKE %s"
                params.append(f"%{program}%")
                
            if effective_year:
                sql += " AND d.effective_year = %s"
                params.append(effective_year)
            else:
                sql += " AND d.is_latest = true"
                
            sql += " ORDER BY rank DESC LIMIT %s"
            params.append(limit)
            
            cursor.execute(sql, params)
            results = cursor.fetchall()
            
            formatted_results = []
            for row in results:
                formatted_results.append({
                    'content': row[0],
                    'document_title': row[1],
                    'program': row[2],
                    'effective_year': row[3],
                    'page': row[4],
                    'url': row[5],
                    'citation': f"{row[1]}, page {row[4]} ({row[5]})"
                })
                
            return formatted_results

    @staticmethod
    def list_documents(collection: str, program: str = None) -> List[Dict[str, Any]]:
        with db_connection() as conn, conn.cursor() as cursor:
            sql = """
                SELECT title, program, effective_year, version, is_latest, url, synced_at
                FROM documents
                WHERE collection = %s AND status = 'active'
            """
            params = [collection]
            
            if program:
                sql += " AND program ILIKE %s"
                params.append(f"%{program}%")
                
            sql += " ORDER BY program, effective_year DESC"
            
            cursor.execute(sql, params)
            results = cursor.fetchall()
            
            docs = []
            for row in results:
                docs.append({
                    'title': row[0],
                    'program': row[1],
                    'effective_year': row[2],
                    'version': row[3],
                    'is_latest': row[4],
                    'url': row[5],
                    'synced_at': row[6].isoformat() if row[6] else None
                })
            return docs

    @staticmethod
    def get_document_pages(collection: str, filename_or_url: str, start_page: int, end_page: int = None) -> str:
        if end_page is None:
            end_page = start_page

        # Hard limit to 5 pages max to avoid huge responses
        if end_page - start_page > 4:
            end_page = start_page + 4

        with db_connection() as conn, conn.cursor() as cursor:
            sql = """
                SELECT c.page, c.content
                FROM document_chunks c
                JOIN documents d ON c.document_id = d.id
                WHERE d.collection = %s 
                  AND (d.filename = %s OR d.url = %s)
                  AND c.page >= %s AND c.page <= %s
                ORDER BY c.page, c.chunk_index
            """
            
            cursor.execute(sql, (collection, filename_or_url, filename_or_url, start_page, end_page))
            results = cursor.fetchall()
            
            if not results:
                return "No content found for the specified pages."
                
            page_contents = {}
            for row in results:
                page_num = row[0]
                content = row[1]
                if page_num not in page_contents:
                    page_contents[page_num] = []
                page_contents[page_num].append(content)
                
            output = ""
            for p in sorted(page_contents.keys()):
                output += f"\n--- Page {p} ---\n"
                output += "\n\n".join(page_contents[p])
                output += "\n"
                
            return output.strip()
