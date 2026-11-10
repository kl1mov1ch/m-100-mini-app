from datetime import date

from pydantic import BaseModel, Field


class ParseBody(BaseModel):
    text: str = Field(min_length=1, max_length=8000)
    local_only: bool = False


class Line(BaseModel):
    item_id: str
    quantity: float = Field(gt=0, le=1e8, allow_inf_nan=False)


class SaveBody(BaseModel):
    date: date
    revision: int = Field(ge=0)
    text: str = Field(default="", max_length=8000)
    lines: list[Line] = Field(min_length=1, max_length=10000)
    crew_count: int = Field(default=1, ge=1, le=1000, strict=True)
    allow_exceed: bool = False


class Connection(BaseModel):
    public_url: str = ""
    webhook: str = ""
    file_id: int | None = Field(default=None, gt=0)


class AiConnection(BaseModel):
    api_key: str = Field(min_length=8, max_length=1000)
    base_url: str = Field(max_length=500)
    model: str = Field(min_length=1, max_length=150)


class UserBody(BaseModel):
    telegram_id: str = Field(pattern=r"^[1-9]\d{0,19}$")
    name: str = Field(min_length=1, max_length=100)
    role: str = Field(default="master", pattern=r"^(master|admin)$")
    enabled: bool = True


class ProjectBody(BaseModel):
    name: str = Field(min_length=1, max_length=150)
    owner_id: str | None = None
    public_url: str = ""
    file_id: int | None = Field(default=None, gt=0)
    webhook: str = ""
    sample: bool = False
