from pydantic import BaseModel
from typing import List, Optional


class ChatMessage(BaseModel):
    """Single turn of a chat message in a multi-turn conversation."""
    sender: str   # 'user' or 'ai'
    text: str


class ChatRequest(BaseModel):
    """Validated payload for incoming /api/chat requests."""
    message: str
    history: Optional[List[ChatMessage]] = None
    user_email: Optional[str] = None


class ChatResponse(BaseModel):
    """Structured outgoing payload containing the assistant response."""
    response: str
