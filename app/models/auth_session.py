from pydantic import BaseModel, Field, BeforeValidator
from typing import Optional, Annotated
from datetime import datetime

PyObjectId = Annotated[str, BeforeValidator(str)]

class AuthSession(BaseModel):
    id: Optional[PyObjectId] = Field(alias="_id", default=None)
    user_id: PyObjectId = Field(description="Reference to User ID")
    
    refresh_token_hash: str = Field(description="SHA256 hash of the refresh token")
    
    user_agent: str = Field(default="Unknown", description="Client User Agent")
    device_id: Optional[str] = Field(default=None, description="Unique Device ID from Client")
    ip: str = Field(default="0.0.0.0", description="Client IP Address")
    
    created_at: datetime = Field(default_factory=datetime.now)
    expires_at: datetime = Field(description="Expiration time of the refresh token")
    
    revoked: bool = Field(default=False, description="Whether this session has been revoked")

    class Config:
        populate_by_name = True
        json_schema_extra = {
            "example": {
                "user_id": "6530...",
                "refresh_token_hash": "a1b2c3...",
                "user_agent": "Mozilla/5.0...",
                "ip": "192.168.1.1",
                "expires_at": "2024-01-01T00:00:00",
                "revoked": False
            }
        }
