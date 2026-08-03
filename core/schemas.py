from pydantic import BaseModel, Field, field_validator
from typing import List, Optional

# Conversation history arrives from the browser's localStorage, so it is
# attacker-controlled: it is capped and role-validated before it ever reaches
# a model. See sanitize_history() in api/routes/chat.py.
MAX_MESSAGE_CHARS = 4000
MAX_HISTORY_TURNS = 12
MAX_HISTORY_CHARS = 12000


class ChatMessage(BaseModel):
    """Single turn of a chat message in a multi-turn conversation."""
    sender: str   # 'user' or 'ai'
    text: str

    @field_validator("sender")
    @classmethod
    def _known_sender(cls, v: str) -> str:
        """Only 'user' and 'ai' turns exist. Anything else — notably a forged
        'system' turn — is coerced to 'user' so it cannot be replayed to the
        model as an instruction."""
        return v if v in ("user", "ai") else "user"


class ChatRequest(BaseModel):
    """Validated payload for incoming /api/chat requests."""
    message: str = Field(..., min_length=1, max_length=MAX_MESSAGE_CHARS)
    history: Optional[List[ChatMessage]] = None
    user_email: Optional[str] = Field(default=None, max_length=254)


class ChatResponse(BaseModel):
    """Structured outgoing payload containing the assistant response."""
    response: str
