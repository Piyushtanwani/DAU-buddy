from fastapi import HTTPException
from google.oauth2 import id_token
from google.auth.transport import requests as google_requests
import google.auth.exceptions
import requests
from core import config
from core.database import db_connection

logger = config.get_logger("api.auth")

CLIENT_ID = config.get_google_client_id()
global_session = requests.Session()
cached_google_request = google_requests.Request(session=global_session)

def verify_google_token(credential: str) -> str:
    try:
        idinfo = id_token.verify_oauth2_token(credential, cached_google_request, CLIENT_ID, clock_skew_in_seconds=300)
        email = idinfo['email']
        if not (email.endswith("@dau.ac.in") or email.endswith("@daiict.ac.in")):
            raise HTTPException(status_code=403, detail="Invalid domain")
        return email
    except ValueError as e:
        logger.error(f"Google Token Verification Error (ValueError): {e}")
        raise HTTPException(status_code=401, detail="Invalid Google token")
    except google.auth.exceptions.TransportError as e:
        logger.error(f"Google Token Verification Error (TransportError): {e}")
        raise HTTPException(status_code=503, detail="Failed to connect to Google authentication servers. Please try again.")

def resolve_role(email: str) -> str:
    """
    Centralize the role resolution logic:
    maintainer list → numeric local-part → faculty table → staff table → default 'Student'
    """
    if email in config.get_feedback_recipient_emails():
        local_part = email.split('@')[0]
        return 'Student / Maintainer' if local_part.isdigit() else 'Maintainer'
    
    local_part = email.split('@')[0]
    if local_part.isdigit():
        return 'Student'
    
    try:
        with db_connection() as conn:
            with conn.cursor() as cursor:
                cursor.execute("SELECT 1 FROM faculty WHERE email = %s LIMIT 1", (email,))
                if cursor.fetchone():
                    return 'Faculty'
                
                cursor.execute("SELECT 1 FROM staff WHERE email = %s LIMIT 1", (email,))
                if cursor.fetchone():
                    return 'Staff'
    except Exception as e:
        logger.error(f"Error checking directories for role assignment: {e}")
        
    return 'Student'
