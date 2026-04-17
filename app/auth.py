from fastapi import APIRouter, Request, Depends, Form, HTTPException
from fastapi.responses import RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session
from passlib.context import CryptContext

from app.database import get_db
from app.models import User
from app.roles import is_administrator
from app.permissions_service import default_landing_path, module_allowed

router = APIRouter()
templates = Jinja2Templates(directory="app/templates")

# --------------------------------------------------
# Password hashing (PBKDF2 ONLY)
# --------------------------------------------------
pwd_context = CryptContext(
    schemes=["pbkdf2_sha256"],
    deprecated="auto"
)


def verify_password(plain_password: str, hashed_password: str) -> bool:
    return pwd_context.verify(plain_password, hashed_password)


def hash_password(password: str) -> str:
    return pwd_context.hash(password)


# --------------------------------------------------
# Auth dependencies
# --------------------------------------------------
def require_login(request: Request) -> int:
    """
    Returns logged-in user_id.
    Redirects to login if missing.
    """
    user_id = request.session.get("user_id")
    if not user_id:
        raise HTTPException(status_code=401, detail="Not authenticated")
    return user_id


def require_admin(
    request: Request,
    user_id: int = Depends(require_login),
    db: Session = Depends(get_db),
) -> User:
    user = db.query(User).filter(User.id == user_id).first()
    if not user or not is_administrator(user):
        raise HTTPException(status_code=403, detail="Administrator access required")
    return user


def require_module(module_key: str):
    """Require login and a ticked module for the user's role (administrators: all modules)."""

    def _dep(
        user_id: int = Depends(require_login),
        db: Session = Depends(get_db),
    ) -> User:
        user = db.query(User).filter(User.id == user_id).first()
        if not user:
            raise HTTPException(status_code=401, detail="Not authenticated")
        if not module_allowed(db, user, module_key):
            raise HTTPException(status_code=403, detail="Access denied")
        return user

    return _dep


# --------------------------------------------------
# Login page
# --------------------------------------------------
@router.get("/login")
def login_page(request: Request, db: Session = Depends(get_db)):
    uid = request.session.get("user_id")
    if uid:
        user = db.query(User).filter(User.id == uid).first()
        if user:
            return RedirectResponse(default_landing_path(db, user), status_code=302)

    return templates.TemplateResponse(
        "login.html",
        {"request": request},
    )


# --------------------------------------------------
# Login submit
# --------------------------------------------------
@router.post("/login")
def login(
    request: Request,
    username: str = Form(...),
    password: str = Form(...),
    db: Session = Depends(get_db),
):
    user = db.query(User).filter(User.username == username).first()

    if not user or not verify_password(password, user.password_hash):
        return templates.TemplateResponse(
            "login.html",
            {
                "request": request,
                "error": "Invalid username or password",
            },
        )

    # Store session
    request.session["user_id"] = user.id
    request.session["username"] = user.username

    return RedirectResponse(default_landing_path(db, user), status_code=302)


# --------------------------------------------------
# Logout
# --------------------------------------------------
@router.get("/logout")
def logout(request: Request):
    request.session.clear()
    return RedirectResponse("/login", status_code=302)