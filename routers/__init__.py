"""Routers HTTP — montados em app.py."""
from routers.agent import router as agent_router
from routers.auth import router as auth_router
from routers.admin import router as admin_router
from routers.webhooks import router as webhooks_router


def register(app) -> None:
    app.include_router(auth_router)
    app.include_router(admin_router)
    app.include_router(agent_router)
    app.include_router(webhooks_router)
