from fastapi import APIRouter

from app.api.v1.routes import ai_providers, auth, projects, system, tasks

api_router = APIRouter(prefix="/api/v1")
api_router.include_router(system.health_router)
api_router.include_router(auth.router)
api_router.include_router(projects.router)
api_router.include_router(tasks.router)
api_router.include_router(ai_providers.router)
api_router.include_router(system.settings_router)
