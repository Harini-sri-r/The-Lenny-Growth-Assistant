"""Liveness endpoints; these do not require external services."""
from fastapi import APIRouter

router = APIRouter()


@router.get("/health", tags=["health"])
def health() -> dict[str, str]:
    return {"status": "ok"}
