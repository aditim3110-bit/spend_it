"""All /v1 routes are collected here."""

from fastapi import APIRouter

from app.api.v1 import health

router = APIRouter(prefix="/v1")
router.include_router(health.router)
