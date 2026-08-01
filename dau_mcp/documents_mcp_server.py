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
    If searching for a semester curriculum, use roman numerals for the semester (e.g., 'Semester-II' instead of 'Semester 2'). DO NOT include the program name inside the `query` string (put it ONLY in the `program` argument). If passing a program name, you MUST use official spacing (e.g. 'MSc IT' instead of 'mscit').
    
    IMPORTANT FOR AI (CITATION): 
    When answering from these results you MUST cite the source as: Document title, page N (URL).
    Answers without a citation are considered wrong. Note: URLs open only on the DAU campus network.
    """
    query_lower = query.lower()
    program_lower = program.lower() if program else ""
    
    # Combined string to search for program keywords
    search_str = query_lower + " " + program_lower
    
    if "msc it" in search_str or "mscit" in search_str or "msc (it)" in search_str:
        program = "MSc IT"
    elif "msc ds" in search_str or "mscds" in search_str or "msc (ds)" in search_str:
        program = "MSc DS"
    elif "msc aa" in search_str or "mscaa" in search_str:
        program = "MSc AA"
    elif "mtech" in search_str:
        if "cs" in search_str or "ml" in search_str: program = "MTech CS ML"
        elif "ec" in search_str: program = "MTech EC"
        else: program = "MTech ICT"
    elif "btech" in search_str or "b tech" in search_str:
        if "mnc" in search_str: program = "BTech MnC"
        elif "cs" in search_str: program = "BTech ICT CS"
        elif "evd" in search_str: program = "BTech EVD"
        else: program = "BTech ICT"
    elif "mdes" in search_str:
        if "cd" in search_str: program = "MDes CD"
        else: program = "MDes IUxD"
            
    # Auto-correct semester numbers to support both Roman and Arabic numerals (programs use different formats)
    if "sem 2" in query_lower or "semester 2" in query_lower or "2nd sem" in query_lower or "semester ii" in query_lower or "semester-ii" in query_lower:
        query = "(Semester-II OR \"Semester II\" OR Semester-2 OR \"Semester 2\") curriculum"
    elif "sem 1" in query_lower or "semester 1" in query_lower or "1st sem" in query_lower or "semester i" in query_lower or "semester-i" in query_lower:
        query = "(Semester-I OR \"Semester I\" OR Semester-1 OR \"Semester 1\") curriculum"
    elif "sem 3" in query_lower or "semester 3" in query_lower or "3rd sem" in query_lower or "semester iii" in query_lower or "semester-iii" in query_lower:
        query = "(Semester-III OR \"Semester III\" OR Semester-3 OR \"Semester 3\") curriculum"
    elif "sem 4" in query_lower or "semester 4" in query_lower or "4th sem" in query_lower or "semester iv" in query_lower or "semester-iv" in query_lower:
        query = "(Semester-IV OR \"Semester IV\" OR Semester-4 OR \"Semester 4\") curriculum"
    elif "sem 5" in query_lower or "semester 5" in query_lower or "5th sem" in query_lower or "semester v" in query_lower or "semester-v" in query_lower:
        query = "(Semester-V OR \"Semester V\" OR Semester-5 OR \"Semester 5\") curriculum"
    elif "sem 6" in query_lower or "semester 6" in query_lower or "6th sem" in query_lower or "semester vi" in query_lower or "semester-vi" in query_lower:
        query = "(Semester-VI OR \"Semester VI\" OR Semester-6 OR \"Semester 6\") curriculum"
    elif "sem 7" in query_lower or "semester 7" in query_lower or "7th sem" in query_lower or "semester vii" in query_lower or "semester-vii" in query_lower:
        query = "(Semester-VII OR \"Semester VII\" OR Semester-7 OR \"Semester 7\") curriculum"
    elif "sem 8" in query_lower or "semester 8" in query_lower or "8th sem" in query_lower or "semester viii" in query_lower or "semester-viii" in query_lower:
        query = "(Semester-VIII OR \"Semester VIII\" OR Semester-8 OR \"Semester 8\") curriculum"
        
    if program and "(" in program:
        program = program.replace('(', '').replace(')', '')
        
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
        
    if program and "BTech" in program:
        output += "\n\nIMPORTANT HINT FOR AI: In BTech curriculum documents, the tables for odd and even semesters (e.g. Sem 1 and Sem 2) are printed side-by-side on the exact same lines! The left half of the line belongs to the odd semester, and the right half belongs to the even semester. You MUST read the lines horizontally and split them in half to find the courses for your requested semester."
        
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
