from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request

from app.database import SessionLocal
from app.models import User
from app.permissions_service import resolve_allowed_modules


class PermissionLoaderMiddleware(BaseHTTPMiddleware):
    """Attach current_user and allowed_modules to request.state for templates and helpers."""

    async def dispatch(self, request: Request, call_next):
        request.state.current_user = None
        request.state.allowed_modules = frozenset()

        uid = request.session.get("user_id")
        if uid:
            db = SessionLocal()
            try:
                user = db.query(User).filter(User.id == uid).first()
                if user:
                    request.state.current_user = user
                    request.state.allowed_modules = resolve_allowed_modules(db, user)
            finally:
                db.close()

        return await call_next(request)
