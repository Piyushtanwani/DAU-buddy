from mcp.server.fastmcp import FastMCP
import os
import sys

# Add the parent directory to the Python path
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from api.services.document_service import DocumentService
import subprocess

mcp = FastMCP("DocumentsServer")

@mcp.tool()
def search_academic_requirements(query: str, program: str = None, cohort_year: str = None, limit: int = 8) -> str:
    """
    Search academic requirement documents based on a query.
    
    IMPORTANT FOR AI (QUERY FORMAT): 
    This uses strict Database Full-Text Search, NOT semantic search. 
    Do NOT pass full sentences or questions (e.g., "what is the minimum CPI for BTech"). 
    You MUST extract 2-4 core keywords (e.g., "minimum CPI graduation BTech") otherwise it will fail to find matches.
    
    IMPORTANT FOR AI (CITATION): 
    When answering from these results you MUST cite the source as: Document title, page N (URL).
    Answers without a citation are considered wrong. Note: URLs open only on the DAU campus network.
    """
    results = DocumentService.search_documents("academic_requirements", query, program, cohort_year, limit)
    
    if not results:
        return "No results found matching your query."
        
    output = ""
    for idx, r in enumerate(results, 1):
        output += f"--- Result {idx} ---\n"
        output += f"Citation: {r['citation']}\n"
        output += f"Program: {r['program']}\n"
        output += f"Effective Year: {r['effective_year']}\n"
        output += f"Content:\n{r['content']}\n\n"
        
    return output

@mcp.tool()
def list_academic_documents(program: str = None) -> str:
    """
    List all available academic requirement documents, optionally filtered by program.
    """
    docs = DocumentService.list_documents("academic_requirements", program)
    if not docs:
        return "No academic documents found."
        
    output = "Available Academic Documents:\n\n"
    for d in docs:
        output += f"- {d['title']} ({d['effective_year']}) - Latest: {d['is_latest']}\n"
        
    return output

@mcp.tool()
def get_academic_document_pages(filename_or_url: str, start_page: int, end_page: int = None) -> str:
    """
    Return the full text of specific pages from an academic document.
    """
    return DocumentService.get_document_pages("academic_requirements", filename_or_url, start_page, end_page)

@mcp.tool()
def sync_academic_documents() -> str:
    """
    Trigger the synchronization of academic requirement documents from the intranet.
    """
    script_path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "scripts", "seed_documents.py")
    try:
        # Run the seed script as a subprocess
        result = subprocess.run([sys.executable, script_path], capture_output=True, text=True, check=True)
        return "Sync completed successfully.\n" + result.stdout
    except subprocess.CalledProcessError as e:
        return f"Sync failed with error:\n{e.stderr}"

if __name__ == "__main__":
    mcp.run(transport='stdio')
