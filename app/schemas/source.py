from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field, HttpUrl


class SourceCreate(BaseModel):
    name: str = Field(min_length=2, max_length=120)
    feed_url: HttpUrl
    language: str = Field(default="en", min_length=2, max_length=10)


class SourceRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    feed_url: str
    language: str
    is_active: bool
    created_at: datetime

