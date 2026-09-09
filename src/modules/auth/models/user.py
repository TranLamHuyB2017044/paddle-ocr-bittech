from pydantic import BaseModel, EmailStr, Field, BeforeValidator
from typing import Optional, Literal, Annotated, Any
from datetime import datetime

# Helper to handle ObjectId as string
PyObjectId = Annotated[str, BeforeValidator(str)]

# Helper to handle group_key (string or list)
def validate_group_key(v: Any) -> Any:
    """Automatically convert string to list for backward compatibility"""
    if isinstance(v, str):
        return [v]
    return v

GroupKey = Annotated[Optional[list[str]], BeforeValidator(validate_group_key)]

class DocTypeStats(BaseModel):
    """Statistics for each document type"""
    idCard: int = 0
    driverLicense: int = 0
    invoice: int = 0
    document: int = 0
    vehicleDocuments: int = 0
    vehicle: int = 0
    menu: int = 0
    administrativeDocument: int = 0

class UserStats(BaseModel):
    total_extractions: int = 0
    last_extraction_at: Optional[datetime] = None
    doc_type_stats: DocTypeStats = Field(default_factory=DocTypeStats)

class UserApiKey(BaseModel):
    access_key: str
    hashed_secret: str
    plain_secret: Optional[str] = Field(default=None, description="TEMPORARY: Plaintext secret for FE convenience")
    created_at: datetime = Field(default_factory=datetime.now)

class User(BaseModel):
    id: Optional[PyObjectId] = Field(alias="_id", default=None)
    user_id: Optional[int] = Field(default=None, description="Auto-incrementing user ID")
    username: Optional[str] = Field(default=None)
    fullname: Optional[str] = Field(default=None)
    email: EmailStr
    avatar_url: Optional[str] = Field(default=None)
    phone: Optional[str] = Field(default=None)
    auth_provider: Literal["local", "google"] = Field(default="local")
    password: Optional[str] = Field(default=None, description="Hashed password, null if auth_provider is google")
    
    api_key: Optional[UserApiKey] = Field(default=None, description="API Key Details")
    
    stats: UserStats = Field(default_factory=UserStats)
    
    created_at: datetime = Field(default_factory=datetime.now)
    updated_at: datetime = Field(default_factory=datetime.now)
    
    active: bool = True
    deviceId: Optional[str] = Field(default=None)
    role: Literal[0, 4] = Field(default=4, description="0: admin, 4: user")
    account_id: Optional[PyObjectId] = Field(default=None)
    group_key: GroupKey = Field(default=None)


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
