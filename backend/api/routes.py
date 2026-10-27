
from fastapi import APIRouter

from backend.api.admin import admin_router
from backend.api.admin_feedback import admin_feedback_router
from backend.api.backend import backend_router
from backend.api.feedback import feedback_router
from backend.api.frontend import frontend_router
from backend.api.usage import usage_router

router = APIRouter()

router.include_router(admin_router)
router.include_router(admin_feedback_router)
router.include_router(backend_router)
router.include_router(feedback_router)
router.include_router(usage_router)
router.include_router(frontend_router)
