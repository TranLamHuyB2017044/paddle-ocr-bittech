from pydantic import BaseModel, Field
from typing import Optional, Annotated
from datetime import datetime
from pydantic.functional_validators import BeforeValidator

PyObjectId = Annotated[str, BeforeValidator(str)]

class AuthService(BaseModel):
    id: Optional[PyObjectId] = Field(alias="_id", default=None)

    uuid: str
    endpoint: Optional[str] = None
    connection_type: Optional[str] = "hkb"

    key: Optional[str] = None # API Key
    values: Optional[str] = None

    user_id: int # external_id from response

    app_name: Optional[str] = None # name from system_connection
    app_info: Optional[str] = None # system_connection JSON

    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)

    class Config:
        populate_by_name = True
