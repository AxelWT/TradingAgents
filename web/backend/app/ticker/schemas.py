from typing import Optional

from pydantic import BaseModel, Field


class TickerLookupRequest(BaseModel):
    company_name: str = Field(..., min_length=1, max_length=80)
    asset_type: str = Field("stock")  # hint only, not enforced


class TickerCandidate(BaseModel):
    ticker: str
    name: str
    exchange: Optional[str] = None
    validated: bool = False


class TickerLookupResponse(BaseModel):
    candidates: list[TickerCandidate]
