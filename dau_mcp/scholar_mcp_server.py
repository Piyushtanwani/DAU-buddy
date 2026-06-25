from mcp.server.fastmcp import FastMCP
from typing import List, Dict, Any
from api.services.scholar_service import get_all_scholars, search_scholars as db_search_scholars, get_scholar_by_id

def list_scholars(limit: int = 20, offset: int = 0) -> List[Dict[str, Any]]:
    """List doctoral scholars from the DA-IICT database.
    
    Args:
        limit: Maximum number of scholars to return (default 20).
        offset: Number of records to skip.
    """
    return get_all_scholars(limit, offset)

def search_scholars(query: str, limit: int = 10) -> List[Dict[str, Any]]:
    """Search for doctoral scholars by name, advisor, thesis topic, or research area.
    
    Args:
        query: The search term.
        limit: Maximum results to return.
    """
    return db_search_scholars(query, limit)

def get_scholar_details(scholar_id: int) -> Dict[str, Any]:
    """Get complete details of a specific doctoral scholar by their ID.
    
    Args:
        scholar_id: The ID of the scholar to retrieve.
    """
    res = get_scholar_by_id(scholar_id)
    if not res:
        return {"error": f"Scholar with ID {scholar_id} not found."}
    return res

def sync_scholar_data() -> str:
    """Trigger a re-scraping of the Doctoral Scholars directory to update the database."""
    import subprocess
    import os
    
    script_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), "scripts", "seed_scholars.py")
    try:
        # Run sync synchronously 
        result = subprocess.run(["python", script_path], capture_output=True, text=True, check=True)
        return f"Scholar data synced successfully. Output: {result.stdout}"
    except subprocess.CalledProcessError as e:
        return f"Failed to sync scholar data: {e.stderr}"
    except Exception as e:
        return f"Error executing sync script: {str(e)}"
