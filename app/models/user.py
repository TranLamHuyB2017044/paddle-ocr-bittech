from pydantic import BaseModel, EmailStr, Field, BeforeValidator
from typing import Optional, Literal, Annotated
from datetime import datetime

# Helper to handle ObjectId as string
PyObjectId = Annotated[str, BeforeValidator(str)]

class UserStats(BaseModel):
    total_extractions: int = 0
    last_extraction_at: Optional[datetime] = None

class User(BaseModel):
    id: Optional[PyObjectId] = Field(alias="_id", default=None)
    username: Optional[str] = Field(default=None)
    fullname: Optional[str] = Field(default=None)
    email: EmailStr
    phone: Optional[str] = Field(default=None)
    auth_provider: Literal["local", "google"] = Field(default="local")
    password: Optional[str] = Field(default=None, description="Hashed password, null if auth_provider is google")
    
    stats: UserStats = Field(default_factory=UserStats)
    
    created_at: datetime = Field(default_factory=datetime.now)
    updated_at: datetime = Field(default_factory=datetime.now)
    
    active: bool = True

    class Config:
        populate_by_name = True
        json_schema_extra = {
            "example": {
                "username": "johndoe",
                "fullname": "John Doe",
                "email": "user@example.com",
                "phone": "0123456789",
                "auth_provider": "google",
                "stats": {
                    "total_extractions": 128,
                    "last_extraction_at": "2023-10-27T10:00:00"
                }
            }
        }
