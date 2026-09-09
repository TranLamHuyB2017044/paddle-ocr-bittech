from enum import Enum
from pydantic import BaseModel, Field, BeforeValidator
from typing import Optional, Annotated
from datetime import datetime

PyObjectId = Annotated[str, BeforeValidator(str)]

class ChatbotDomain(str, Enum):
    ECOMMERCE = "ecommerce"
    OCOP = "ocop"
    CUSTOMER_SUPPORT = "customer_support"
    GENERAL = "general"
    ADMINISTRATIVE_DOC = "administrative_doc"

class Chatbot(BaseModel):
    id: Optional[PyObjectId] = Field(alias="_id", default=None)
    name: str
    description: Optional[str] = None
    avatar_url: Optional[str] = None
    color: int = 0  # ChatbotColor.DEFAULT
    domain: ChatbotDomain = Field(default=ChatbotDomain.ECOMMERCE)
    greeting: Optional[str] = None
    workspace_id: Optional[PyObjectId] = None
    public_token: str
    account_id: PyObjectId
    is_active: bool = True
    created_at: datetime = Field(default_factory=datetime.now)
    updated_at: datetime = Field(default_factory=datetime.now)
    telegram_bot_token: Optional[str] = None
    telegram_chat_id: Optional[str] = None
    workflow_webhook_url: Optional[str] = None
    collect_contact_info: bool = True
    
    class Config:
        populate_by_name = True
        use_enum_values = True

