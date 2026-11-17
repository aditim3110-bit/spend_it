"""All /v1 routes are collected here."""

from fastapi import APIRouter

from app.api.v1 import auth, balances, expenses, friends, health, me, split

router = APIRouter(prefix="/v1")
router.include_router(health.router)
router.include_router(auth.router)
router.include_router(me.router)
router.include_router(split.router)
router.include_router(friends.router)
router.include_router(expenses.router)
router.include_router(balances.router)
