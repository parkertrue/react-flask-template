from pydantic import BaseModel


class HealthResponse(BaseModel):
    """GET /api/health: "ok" whenever the backend answers"""
    status: str
