from pydantic import BaseModel, Field


class TokenPairResponse(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"
    expires_in: int


class RefreshRequestDTO(BaseModel):
    refresh_token: str = Field(min_length=10, max_length=4096)
