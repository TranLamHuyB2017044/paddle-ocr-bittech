from pydantic import BaseModel, Field, BeforeValidator
from typing import Optional, Annotated
from datetime import datetime
from src.config import PLANS_CONFIG

# Helper to handle ObjectId as string
PyObjectId = Annotated[str, BeforeValidator(str)]

class Account(BaseModel):
    id: Optional[PyObjectId] = Field(alias="_id", default=None)
    plan: int = Field(default=0, description="Plan type: 0: free, 1: basic, 2: pro, 3: business, 4: chatbot")
    used_requests: int = Field(default=0)
    reset_at: datetime = Field(default_factory=datetime.utcnow)
    created_at: datetime = Field(default_factory=datetime.utcnow)
    
    class Config:
        populate_by_name = True
        json_schema_extra = {
            "example": {
                "plan": "basic",
                "used_requests": 150,
                "reset_at": "2024-02-20T00:00:00"
            }
        }
