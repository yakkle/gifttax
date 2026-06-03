
from fastapi import APIRouter

from backend.api.backend import backend_router
from backend.api.frontend import frontend_router

router = APIRouter()

router.include_router(backend_router)
router.include_router(frontend_router)
