from pydantic import BaseModel
from typing import Optional


class ProvinceOut(BaseModel):
    name: str


class MunicipalityOut(BaseModel):
    id: int
    name: str
    province: str
    region: str
    lat: Optional[float] = None
    lon: Optional[float] = None
    geo_score: Optional[float] = None
    solar_norm: Optional[float] = None
    income_score: Optional[float] = None
    pop_density_norm: Optional[float] = None


class RunCreateIn(BaseModel):
    location: str  # "Laguna" | "San Pablo, Laguna" | "San Pablo|Calamba, Laguna"


class RunOut(BaseModel):
    id: str
    location: str
    province: Optional[str] = None
    status: str
    created_at: str
    completed_at: Optional[str] = None
    error: Optional[str] = None


class RunDetailOut(RunOut):
    results: list[dict] = []
    report: Optional[dict] = None


class ChatIn(BaseModel):
    run_id: Optional[str] = None   # None = global KB search
    message: str


class ChatOut(BaseModel):
    reply: str
    run_id: Optional[str] = None


class ChatMessageOut(BaseModel):
    role: str
    content: str
    created_at: str


class AdminStatsOut(BaseModel):
    municipalities: int
    geo_scores: int
    runs: int
    run_results: int
    chat_messages: int
    reports: int
    web_intel_cache: int
    last_precompute: Optional[str] = None
