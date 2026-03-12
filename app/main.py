from fastapi import FastAPI, Request, Depends, Form, HTTPException
from fastapi.responses import RedirectResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session
from datetime import date

from starlette.middleware.sessions import SessionMiddleware

from app.database import engine, get_db
from app.models import Base, OTRegister, IOLMaster
from app.auth import router as auth_router, require_login
from app.constants import SURGERY_TYPES, PATIENT_CATEGORIES
from app.skp import fetch_patient
from app.database import engine
from app.models import Base  # 🔑 THIS IMPORT IS CRITICAL
from datetime import datetime
from fastapi.responses import StreamingResponse
import io
import csv
from collections import defaultdict
from datetime import date, datetime
from collections import defaultdict
from fastapi import APIRouter
from app.models import Base, OTRegister, IOLMaster, IntravitrealDrugMaster

Base.metadata.create_all(bind=engine)



# --------------------------------------------------
# App init
# --------------------------------------------------
app = FastAPI(title="OT Register")

app.add_middleware(
    SessionMiddleware,
    secret_key="CHANGE_THIS_TO_A_RANDOM_SECRET"
)

Base.metadata.create_all(bind=engine)



# --------------------------------------------------
# Static & templates
# --------------------------------------------------
app.mount("/static", StaticFiles(directory="app/static"), name="static")
templates = Jinja2Templates(directory="app/templates")
# -----------------------------
# Global date format filter
# -----------------------------
def format_date(value):
    if not value:
        return ""
    if isinstance(value, (date, datetime)):
        return value.strftime("%d/%m/%Y")
    return value

templates.env.filters["datefmt"] = format_date
# --------------------------------------------------
# Auth routes
# --------------------------------------------------
app.include_router(auth_router)
def get_current_user(db: Session, user_id: int):
    return db.query(User).filter(User.id == user_id).first()
# --------------------------------------------------
# Dashboard
# --------------------------------------------------
from datetime import date, datetime
from fastapi import Request, Depends
from sqlalchemy.orm import Session

from app.models import OTRegister, User
from app.database import get_db
from app.auth import require_login


@app.get("/dashboard")
def dashboard(
    request: Request,
    selected_date: str | None = None,
    db: Session = Depends(get_db),
    user_id: int = Depends(require_login),
):
    # 🔑 fetch logged-in user
    current_user = db.query(User).filter(User.id == user_id).first()

    # date handling
    if selected_date:
        day = datetime.strptime(selected_date, "%Y-%m-%d").date()
    else:
        day = date.today()
        selected_date = day.strftime("%Y-%m-%d")

    records = (
        db.query(OTRegister)
        .filter(OTRegister.date_of_surgery == day)
        .order_by(OTRegister.id.asc())
        .all()
    )

    return templates.TemplateResponse(
        "dashboard.html",
        {
            "request": request,
            "records": records,
            "selected_date": selected_date,
            "current_user": current_user,  # ✅ THIS IS STEP 3
        },
    )

@app.post("/ot/{ot_id}/update")
async def update_ot(
    ot_id: int,
    request: Request,
    db: Session = Depends(get_db),
    user_id: int = Depends(require_login),
):
    record = db.query(OTRegister).filter(OTRegister.id == ot_id).first()
    if not record:
        raise HTTPException(status_code=404, detail="OT record not found")

    form = await request.form()

    record.patient_uhid = form.get("patient_uhid")
    record.patient_name = form.get("patient_name")
    record.eye = form.get("eye")
    record.surgery = form.get("surgery")
    record.category = form.get("category")
    record.surgeon_name = form.get("surgeon_name")
    record.iol_id = int(form.get("iol_id")) if form.get("iol_id") else None
    record.date_of_surgery = datetime.strptime(
        form.get("date_of_surgery"), "%Y-%m-%d"
    ).date()
    record.is_vue = bool(form.get("is_vue")) 
    db.commit()

    return RedirectResponse("/dashboard", status_code=303)

@app.post("/ot/{ot_id}/delete")
async def delete_ot(
    ot_id: int,
    request: Request,
    db: Session = Depends(get_db),
    user_id: int = Depends(require_login),
):
    form = await request.form()
    selected_date = form.get("selected_date")

    record = db.query(OTRegister).filter(OTRegister.id == ot_id).first()
    if not record:
        raise HTTPException(status_code=404, detail="OT record not found")

    db.delete(record)
    db.commit()

    if selected_date:
        return RedirectResponse(
            f"/dashboard?selected_date={selected_date}",
            status_code=303,
        )

    return RedirectResponse("/dashboard", status_code=303)
@app.get("/ot/{ot_id}/edit")
def edit_ot(
    ot_id: int,
    request: Request,
    db: Session = Depends(get_db),
    user_id: int = Depends(require_login),
):
    record = db.query(OTRegister).filter(OTRegister.id == ot_id).first()
    if not record:
        raise HTTPException(status_code=404, detail="OT record not found")

    current_user = db.query(User).filter(User.id == user_id).first()
    iols = db.query(IOLMaster).all()

    return templates.TemplateResponse(
        "ot_edit.html",
        {
            "request": request,
            "record": record,
            "iols": iols,
            "current_user": current_user,
        },
    )
# --------------------------------------------------
# New OT Entry form
# --------------------------------------------------
@app.get("/ot/new")
def new_ot(
    request: Request,
    db: Session = Depends(get_db),
    user_id: int = Depends(require_login),
):
    current_user = db.query(User).filter(User.id == user_id).first()

    iols = db.query(IOLMaster).all()
    drugs = db.query(IntravitrealDrugMaster).order_by(
        IntravitrealDrugMaster.drug_name
    ).all()

    return templates.TemplateResponse(
        "ot_new.html",
        {
            "request": request,
            "iols": iols,
            "drugs": drugs,              # ✅ now defined
            "current_user": current_user,
        },
    )
# --------------------------------------------------
# Save OT Entry
# --------------------------------------------------

from fastapi import Request, Depends
from fastapi.responses import RedirectResponse
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import OTRegister
from app.auth import require_login

from datetime import datetime

@app.post("/ot/save")


@app.post("/ot/save")
async def save_ot(
    request: Request,
    user_id: int = Depends(require_login),
    db: Session = Depends(get_db),
):
    form = await request.form()

    # ✅ DEFINE date_str first
    date_str = form.get("date_of_surgery")
    intravitreal_drug_id = (
    int(form.get("intravitreal_drug_id"))
    if form.get("intravitreal_drug_id")
    else None
)
    record = OTRegister(
        patient_uhid=form.get("patient_uhid"),
        patient_name=form.get("patient_name"),
        surgery=form.get("surgery"),
        category=form.get("category"),
        surgeon_name=form.get("surgeon_name"),
        eye=form.get("eye"),
        iol_id=int(form.get("iol_id")) if form.get("iol_id") else None,
        is_vue=bool(form.get("is_vue")),
        intravitreal_drug_id=intravitreal_drug_id,
        date_of_surgery=datetime.strptime(date_str, "%Y-%m-%d").date(),  # ✅ FIX
    )

    db.add(record)
    db.commit()

    return RedirectResponse("/dashboard", status_code=303)
# --------------------------------------------------
# Root & favicon
# --------------------------------------------------
@app.get("/")
def root():
    return RedirectResponse("/dashboard")


@app.get("/favicon.ico")
def favicon():
    # Minimal 1x1 transparent PNG so browser does not 404
    return Response(
        content=b'\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01\x08\x06\x00\x00\x00\x1f\x15\xc4\x89\x00\x00\x00\nIDATx\x9cc\x00\x01\x00\x00\x05\x00\x01\r\n-\xb4\x00\x00\x00\x00IEND\xaeB`\x82',
        media_type="image/png",
    )

# main.py

from app.skp import search_global_patient

@app.get("/api/patient/search")
def api_patient_search(
    q: str,
    user_id: int | None = Depends(require_login)
):
    if not user_id:
        return []

    return search_global_patient(q)
# -----------------------------
# API: distinct patient categories (for sort-order setup)
# -----------------------------
@app.get("/api/categories")
def api_distinct_categories(db: Session = Depends(get_db)):
    """Return all distinct patient category values in the database (sorted)."""
    rows = db.query(OTRegister.category).distinct().all()
    categories = sorted({r[0].strip() for r in rows if r[0] and r[0].strip()})
    return {"categories": categories}


# -----------------------------
# IOL Master
# -----------------------------
@app.get("/iol")
def iol_master(
    request: Request,
    db: Session = Depends(get_db),
    user_id: int = Depends(require_login),
):
    current_user = db.query(User).filter(User.id == user_id).first()

    iols = db.query(IOLMaster).order_by(IOLMaster.iol_name.asc()).all()

    return templates.TemplateResponse(
        "iol.html",
        {
            "request": request,
            "iols": iols,
            "current_user": current_user,  # ✅ REQUIRED
        },
    )


@app.post("/iol/add")
def add_iol(
    request: Request,
    name: str = Form(...),
    package: str = Form(...),
    user_id: int | None = Depends(require_login),
    db: Session = Depends(get_db)
):
    if not user_id:
        return RedirectResponse("/login", status_code=302)

    iol = IOLMaster(
    iol_name=name.strip(),
    package=package.strip()
)

    db.add(iol)
    db.commit()

    return RedirectResponse("/iol", status_code=302)
# ----------------------------
# EDIT IOL
# ----------------------------
@app.post("/iol/{iol_id}/edit")
def edit_iol(
    iol_id: int,
    name: str = Form(...),
    package: str = Form(...),
    db: Session = Depends(get_db),
    user_id: int = Depends(require_login),
):
    user = db.query(User).filter(User.id == user_id).first()
    if user.role != "admin":
        raise HTTPException(status_code=403, detail="Access denied")

    iol = db.query(IOLMaster).filter(IOLMaster.id == iol_id).first()
    if not iol:
        raise HTTPException(status_code=404, detail="IOL not found")

    iol.iol_name = name
    iol.package = package
    db.commit()

    return RedirectResponse("/iol", status_code=303)


# ----------------------------
# DELETE IOL
# ----------------------------
@app.post("/iol/{iol_id}/delete")
def delete_iol(
    iol_id: int,
    db: Session = Depends(get_db),
    user_id: int = Depends(require_login),
):
    user = db.query(User).filter(User.id == user_id).first()
    if user.role != "admin":
        raise HTTPException(status_code=403, detail="Access denied")

    iol = db.query(IOLMaster).filter(IOLMaster.id == iol_id).first()
    if not iol:
        raise HTTPException(status_code=404, detail="IOL not found")

    db.delete(iol)
    db.commit()

    return RedirectResponse("/iol", status_code=303)

from app.models import User
from app.auth import require_admin
from app.auth import hash_password, verify_password
from sqlalchemy.exc import IntegrityError

@app.get("/admin/users")
def user_management(
    request: Request,
    db: Session = Depends(get_db),
    admin: User = Depends(require_admin),
):
    users = db.query(User).all()
    error = request.query_params.get("error")
    created = request.query_params.get("created")
    return templates.TemplateResponse(
        "admin_users.html",
        {
            "request": request,
            "users": users,
            "current_user": admin,
            "error": error,
            "created": created,
        },
    )


@app.post("/admin/users/create")
async def create_user(
    request: Request,
    db: Session = Depends(get_db),
    admin: User = Depends(require_admin),
):
    from sqlalchemy import func
    form = await request.form()
    username = (form.get("username") or "").strip()
    password = form.get("password") or ""
    role = (form.get("role") or "staff").strip()

    if not username or not password:
        return RedirectResponse(
            "/admin/users?error=missing",
            status_code=303,
        )

    # Case-insensitive duplicate check (so "Admin" vs "admin" is treated as same)
    existing = db.query(User).filter(
        func.lower(User.username) == username.lower()
    ).first()
    if existing:
        return RedirectResponse(
            "/admin/users?error=duplicate",
            status_code=303,
        )

    user = User(
        username=username,
        password_hash=hash_password(password),
        role=role if role in ("staff", "admin") else "staff",
    )
    db.add(user)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        return RedirectResponse(
            "/admin/users?error=duplicate",
            status_code=303,
        )

    return RedirectResponse("/admin/users?created=1", status_code=303)

@app.post("/admin/users/{user_id}/delete")
def delete_user(
    user_id: int,
    db: Session = Depends(get_db),
    admin: User = Depends(require_admin),
):
    user = db.query(User).filter(User.id == user_id).first()
    if user:
        db.delete(user)
        db.commit()

    return RedirectResponse("/admin/users", status_code=303)

@app.get("/change-password")
def change_password_page(
    request: Request,
    user_id: int = Depends(require_login),
):
    return templates.TemplateResponse(
        "change_password.html",
        {"request": request},
        
    )
@app.post("/admin/users/{user_id}/reset-password")
def reset_user_password(
    user_id: int,
    new_password: str = Form(...),
    db: Session = Depends(get_db),
    admin: User = Depends(require_admin),  # 🔐 admin only
):
    user = db.query(User).filter(User.id == user_id).first()

    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    user.password_hash = hash_password(new_password)
    db.commit()

    return RedirectResponse(
        url="/admin/users",
        status_code=303
    )

@app.post("/change-password")
async def change_password(
    request: Request,
    user_id: int = Depends(require_login),
    db: Session = Depends(get_db),
):
    form = await request.form()
    new_password = form.get("password")

    if not new_password:
        raise HTTPException(status_code=400, detail="Password required")

    user = db.query(User).filter(User.id == user_id).first()
    user.password_hash = hash_password(new_password)
    db.commit()

    return RedirectResponse("/dashboard", status_code=303)
from fastapi import Form
from sqlalchemy.exc import IntegrityError

from fastapi import Form
from sqlalchemy.exc import IntegrityError

@app.get("/admin/drugs")
def drug_master(
    request: Request,
    db: Session = Depends(get_db),
    admin: User = Depends(require_admin),
):
    drugs = db.query(IntravitrealDrugMaster).order_by(
        IntravitrealDrugMaster.drug_name
    ).all()

    return templates.TemplateResponse(
        "drug_master.html",   # ✅ flat template
        {
            "request": request,
            "drugs": drugs,
            "current_user": admin,
        },
    )


@app.post("/admin/drugs/add")
def add_drug(
    drug_name: str = Form(...),
    db: Session = Depends(get_db),
    admin: User = Depends(require_admin),
):
    drug = IntravitrealDrugMaster(
        drug_name=drug_name.strip()
    )

    db.add(drug)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()

    return RedirectResponse(
        "/admin/drugs",
        status_code=303
    )


@app.post("/admin/drugs/{drug_id}/delete")
def delete_drug(
    drug_id: int,
    db: Session = Depends(get_db),
    admin: User = Depends(require_admin),
):
    drug = db.query(IntravitrealDrugMaster).filter(
        IntravitrealDrugMaster.id == drug_id
    ).first()

    if drug:
        db.delete(drug)
        db.commit()

    return RedirectResponse(
        "/admin/drugs",
        status_code=303
    )


@app.post("/admin/drugs/{drug_id}/delete")
def delete_drug(
    drug_id: int,
    db: Session = Depends(get_db),
    admin: User = Depends(require_admin),
):
    drug = db.query(IntravitrealDrugMaster).filter(
        IntravitrealDrugMaster.id == drug_id
    ).first()

    if drug:
        db.delete(drug)
        db.commit()

    return RedirectResponse(
        "/admin/drugs",
        status_code=303
    )


# --------------------------------------------------
# Admin Dashboard (stats with date range)
# --------------------------------------------------
def _admin_dashboard_dates(range_type: str, from_str: str | None, to_str: str | None):
    """Return (date_from, date_to) for dashboard. Default: month to date."""
    today = date.today()
    if range_type == "last_month":
        first_this = today.replace(day=1)
        last_prev = first_this - timedelta(days=1)
        first_prev = last_prev.replace(day=1)
        return first_prev, last_prev
    if range_type == "last_6months":
        first = (today.replace(day=1) - timedelta(days=1)).replace(day=1)
        for _ in range(5):
            first = (first.replace(day=1) - timedelta(days=1)).replace(day=1)
        return first, today
    if range_type == "custom" and from_str and to_str:
        try:
            f = datetime.strptime(from_str, "%Y-%m-%d").date()
            t = datetime.strptime(to_str, "%Y-%m-%d").date()
            if f <= t:
                return f, t
        except ValueError:
            pass
    first_mtd = today.replace(day=1)
    return first_mtd, today


def _compare_period_dates(compare: str):
    """Return (date_from_a, date_to_a, date_from_b, date_to_b, label_a, label_b)."""
    today = date.today()
    if compare == "month":
        # This month (1st to today) vs Last month
        first_this = today.replace(day=1)
        last_prev = first_this - timedelta(days=1)
        first_prev = last_prev.replace(day=1)
        return first_this, today, first_prev, last_prev, "This month", "Last month"
    if compare == "quarter":
        # This quarter vs Last quarter (calendar Q: 1-3, 4-6, 7-9, 10-12)
        q = (today.month - 1) // 3 + 1
        start_this_q = date(today.year, (q - 1) * 3 + 1, 1)
        if q == 1:
            start_prev_q = date(today.year - 1, 10, 1)
            end_prev_q = date(today.year - 1, 12, 31)
        else:
            start_prev_q = date(today.year, (q - 2) * 3 + 1, 1)
            end_prev_q = start_this_q - timedelta(days=1)
        return start_this_q, today, start_prev_q, end_prev_q, "This quarter", "Last quarter"
    if compare == "6months":
        # Last 6 months vs 6 months before that
        end_a = today
        start_a = today.replace(day=1)
        for _ in range(5):
            start_a = (start_a - timedelta(days=1)).replace(day=1)
        end_b = start_a - timedelta(days=1)
        start_b = end_b.replace(day=1)
        for _ in range(5):
            start_b = (start_b - timedelta(days=1)).replace(day=1)
        return start_a, end_a, start_b, end_b, "Last 6 months", "Previous 6 months"
    if compare == "year":
        # This year (Jan 1 to today) vs Last year (Jan 1 to Dec 31)
        start_this = date(today.year, 1, 1)
        start_prev = date(today.year - 1, 1, 1)
        end_prev = date(today.year - 1, 12, 31)
        return start_this, today, start_prev, end_prev, "This year", "Last year"
    return None


def _dashboard_stats_for_period(db, date_from, date_to):
    """Return dict of stats for one period (for reuse in single and compare)."""
    base = db.query(OTRegister).filter(
        OTRegister.date_of_surgery >= date_from,
        OTRegister.date_of_surgery <= date_to,
    )
    total_cataracts = base.filter(OTRegister.surgery == "Cataract").count()
    total_intravitreal = base.filter(OTRegister.surgery == "Intravitreal Injection").count()
    vue_cataract = base.filter(
        OTRegister.surgery == "Cataract",
        OTRegister.is_vue == True,
    ).count()
    vue_intravitreal = base.filter(
        OTRegister.surgery == "Intravitreal Injection",
        OTRegister.is_vue == True,
    ).count()
    top_iols = (
        db.query(IOLMaster.iol_name, func.count(OTRegister.id).label("cnt"))
        .join(OTRegister, OTRegister.iol_id == IOLMaster.id)
        .filter(
            OTRegister.date_of_surgery >= date_from,
            OTRegister.date_of_surgery <= date_to,
        )
        .group_by(IOLMaster.iol_name)
        .order_by(func.count(OTRegister.id).desc())
        .limit(10)
        .all()
    )
    category_rows = (
        db.query(OTRegister.category, func.count(OTRegister.id).label("cnt"))
        .filter(
            OTRegister.date_of_surgery >= date_from,
            OTRegister.date_of_surgery <= date_to,
            OTRegister.category.isnot(None),
            OTRegister.category != "",
        )
        .group_by(OTRegister.category)
        .order_by(func.count(OTRegister.id).desc())
        .all()
    )
    return {
        "date_from": date_from.isoformat(),
        "date_to": date_to.isoformat(),
        "total_cataracts": total_cataracts,
        "total_intravitreal": total_intravitreal,
        "vue_cataract": vue_cataract,
        "vue_intravitreal": vue_intravitreal,
        "top_iols": [{"iol_name": n, "count": c} for n, c in top_iols],
        "category_counts": [{"category": c or "Other", "count": n} for c, n in category_rows],
    }


@app.get("/admin/dashboard")
def admin_dashboard_page(
    request: Request,
    db: Session = Depends(get_db),
    admin: User = Depends(require_admin),
):
    return templates.TemplateResponse(
        "admin_dashboard.html",
        {"request": request, "current_user": admin},
    )


@app.get("/admin/dashboard/api/stats")
def admin_dashboard_api(
    db: Session = Depends(get_db),
    admin: User = Depends(require_admin),
    range_type: str = "mtd",
    from_date: str | None = None,
    to_date: str | None = None,
    compare: str | None = None,
):
    # Compare mode: two periods (this month vs last month, etc.)
    if compare and compare in ("month", "quarter", "6months", "year"):
        res = _compare_period_dates(compare)
        if res:
            (date_from_a, date_to_a, date_from_b, date_to_b, label_a, label_b) = res
            stats_a = _dashboard_stats_for_period(db, date_from_a, date_to_a)
            stats_b = _dashboard_stats_for_period(db, date_from_b, date_to_b)
            return JSONResponse({
                "compare": True,
                "label_a": label_a,
                "label_b": label_b,
                "period_a": stats_a,
                "period_b": stats_b,
            })
    # Single period
    date_from, date_to = _admin_dashboard_dates(range_type, from_date, to_date)
    stats = _dashboard_stats_for_period(db, date_from, date_to)
    return JSONResponse({
        "compare": False,
        "date_from": stats["date_from"],
        "date_to": stats["date_to"],
        "total_cataracts": stats["total_cataracts"],
        "total_intravitreal": stats["total_intravitreal"],
        "vue_cataract": stats["vue_cataract"],
        "vue_intravitreal": stats["vue_intravitreal"],
        "top_iols": stats["top_iols"],
        "category_counts": stats["category_counts"],
    })


from collections import defaultdict
from datetime import datetime
from fastapi import Request, Depends
from sqlalchemy.orm import Session

from collections import defaultdict
from datetime import datetime
from fastapi import Depends, Request
from sqlalchemy.orm import Session
import threading
import time
import requests
import re

from datetime import datetime, date, timedelta
from collections import defaultdict
from sqlalchemy import func
from sqlalchemy.orm import joinedload

from app.database import SessionLocal
from app.models import OTRegister


@app.get("/reports/surgery")
@app.get("/reports/surgery")
def surgery_report(
    request: Request,
    from_date: str | None = None,
    to_date: str | None = None,
    db: Session = Depends(get_db),
    admin: User = Depends(require_admin),  # 🔐 already a User object
):
    current_user = admin   # ✅ just reuse it

    records = []
    category_totals = {}
    iol_totals = {}

    if from_date and to_date:
        f_date = datetime.strptime(from_date, "%Y-%m-%d").date()
        t_date = datetime.strptime(to_date, "%Y-%m-%d").date()

        records = (
            db.query(OTRegister)
            .join(IOLMaster, isouter=True)
            .filter(
                OTRegister.date_of_surgery >= f_date,
                OTRegister.date_of_surgery <= t_date,
            )
            .order_by(OTRegister.date_of_surgery.asc())
            .all()
        )

        # ---- Totals ----
        cat = defaultdict(int)
        iol = defaultdict(int)

        for r in records:
            cat[r.category] += 1
            iol[r.iol.iol_name if r.iol else "No IOL"] += 1

        category_totals = dict(cat)
        iol_totals = dict(iol)

    return templates.TemplateResponse(
        "reports/surgery_report.html",
        {
            "request": request,
            "records": records,
            "from_date": from_date,
            "to_date": to_date,
            "category_totals": category_totals,
            "iol_totals": iol_totals,
            "current_user": current_user,
        },
    )
@app.get("/reports/surgery/excel")
def surgery_report_excel(
    from_date: str,
    to_date: str,
    db: Session = Depends(get_db),
    admin: User = Depends(require_admin),  # 🔐 already a User object
):
    current_user = admin   # ✅ just reuse it

    f_date = datetime.strptime(from_date, "%Y-%m-%d").date()
    t_date = datetime.strptime(to_date, "%Y-%m-%d").date()

    records = (
        db.query(OTRegister)
        .join(IOLMaster, isouter=True)
        .filter(
            OTRegister.date_of_surgery >= f_date,
            OTRegister.date_of_surgery <= t_date,
        )
        .all()
    )

    output = io.StringIO()
    writer = csv.writer(output)

    writer.writerow([
        "Sl No", "Date", "UHID", "Patient Name",
        "Eye", "Category", "IOL"
    ])

    for i, r in enumerate(records, start=1):
        writer.writerow([
            i,
            r.date_of_surgery,
            r.patient_uhid,
            r.patient_name,
            r.eye,
            r.category,
            r.iol.iol_name if r.iol else "",
        ])

    output.seek(0)

    return StreamingResponse(
        output,
        media_type="text/csv",
        headers={
            "Content-Disposition": "attachment; filename=surgery_report.csv"
        },
    )
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import getSampleStyleSheet
from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph
from reportlab.lib import colors

from fastapi import Depends
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session
from datetime import datetime
import io

from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import getSampleStyleSheet
from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph
from reportlab.lib import colors

from app.database import get_db
from app.models import OTRegister, IOLMaster
from app.auth import require_login


@app.get("/reports/surgery/pdf")
def surgery_report_pdf(
    from_date: str,
    to_date: str,
    db: Session = Depends(get_db),
     admin: User = Depends(require_admin),  # 🔐 already a User object
):
    current_user = admin   # ✅ just reuse it

    # -----------------------------
    # Parse input dates (ISO)
    # -----------------------------
    f_date = datetime.strptime(from_date, "%Y-%m-%d").date()
    t_date = datetime.strptime(to_date, "%Y-%m-%d").date()

    # Display format (dd/mm/yyyy)
    f_disp = f_date.strftime("%d/%m/%Y")
    t_disp = t_date.strftime("%d/%m/%Y")

    # -----------------------------
    # Fetch records (earliest first)
    # -----------------------------
    records = (
        db.query(OTRegister)
        .join(IOLMaster, isouter=True)
        .filter(
            OTRegister.date_of_surgery >= f_date,
            OTRegister.date_of_surgery <= t_date,
        )
        .order_by(OTRegister.date_of_surgery.asc())
        .all()
    )

    # -----------------------------
    # PDF setup
    # -----------------------------
    buffer = io.BytesIO()
    doc = SimpleDocTemplate(
        buffer,
        pagesize=A4,
        rightMargin=30,
        leftMargin=30,
        topMargin=30,
        bottomMargin=30,
    )

    styles = getSampleStyleSheet()
    elements = []

    # -----------------------------
    # Title & date range
    # -----------------------------
    elements.append(Paragraph("<b>Surgery List Report</b>", styles["Title"]))
    elements.append(
        Paragraph(f"From <b>{f_disp}</b> To <b>{t_disp}</b>", styles["Normal"])
    )
    elements.append(Paragraph("<br/>", styles["Normal"]))

    # -----------------------------
    # Table data
    # -----------------------------
    table_data = [
        ["Sl No", "Date", "UHID", "Patient Name", "Eye", "Category", "IOL"]
    ]

    for i, r in enumerate(records, start=1):
        table_data.append([
            i,
            r.date_of_surgery.strftime("%d/%m/%Y"),
            r.patient_uhid,
            r.patient_name,
            r.eye,
            r.category,
            r.iol.iol_name if r.iol else "",
        ])

    # -----------------------------
    # Table styling
    # -----------------------------
    table = Table(
        table_data,
        repeatRows=1,
        colWidths=[35, 65, 85, 120, 45, 70, 80],
    )

    table.setStyle(TableStyle([
        ("GRID", (0, 0), (-1, -1), 0.5, colors.grey),
        ("BACKGROUND", (0, 0), (-1, 0), colors.lightgrey),
        ("FONT", (0, 0), (-1, 0), "Helvetica-Bold"),
        ("ALIGN", (0, 0), (0, -1), "CENTER"),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("FONTSIZE", (0, 0), (-1, -1), 9),
        ("BOTTOMPADDING", (0, 0), (-1, 0), 8),
        ("TOPPADDING", (0, 0), (-1, 0), 8),
    ]))

    elements.append(table)

    # -----------------------------
    # Build PDF
    # -----------------------------
    doc.build(elements)
    buffer.seek(0)

    return StreamingResponse(
        buffer,
        media_type="application/pdf",
        headers={
            "Content-Disposition": "attachment; filename=surgery_report.pdf"
        },
    )
from collections import defaultdict
from datetime import datetime
from fastapi import Depends, Request
from sqlalchemy.orm import Session

@app.get("/reports/vue")
def vue_report(
    request: Request,
    from_date: str | None = None,
    to_date: str | None = None,
    db: Session = Depends(get_db),
    admin: User = Depends(require_admin),
):
    current_user = admin

    records = []
    category_totals = {}
    iol_totals = {}

    if from_date and to_date:
        f_date = datetime.strptime(from_date, "%Y-%m-%d").date()
        t_date = datetime.strptime(to_date, "%Y-%m-%d").date()

        records = (
            db.query(OTRegister)
            .join(IOLMaster, isouter=True)
            .filter(
                OTRegister.is_vue == True,
                OTRegister.date_of_surgery >= f_date,
                OTRegister.date_of_surgery <= t_date,
            )
            .order_by(OTRegister.date_of_surgery.asc())
            .all()
        )

        # Totals
        cat = defaultdict(int)
        iol = defaultdict(int)

        for r in records:
            cat[r.category] += 1
            iol[r.iol.iol_name if r.iol else "No IOL"] += 1

        category_totals = dict(cat)
        iol_totals = dict(iol)

    return templates.TemplateResponse(
        "reports/vue_report.html",
        {
            "request": request,
            "records": records,
            "from_date": from_date,
            "to_date": to_date,
            "category_totals": category_totals,
            "iol_totals": iol_totals,
            "current_user": current_user,
        },
    )


from collections import defaultdict
from datetime import datetime
from fastapi import Request, Depends
from sqlalchemy.orm import Session

from collections import defaultdict
from datetime import datetime

@app.get("/reports/category-iol")
def category_iol_report(
    request: Request,
    from_date: str | None = None,
    to_date: str | None = None,
    db: Session = Depends(get_db),
    admin: User = Depends(require_admin),
):
    current_user = admin

    category_iol_data = {}
    category_totals = {}
    vue_totals = {}   # ✅ IMPORTANT

    if from_date and to_date:
        f_date = datetime.strptime(from_date, "%Y-%m-%d").date()
        t_date = datetime.strptime(to_date, "%Y-%m-%d").date()

        records = (
            db.query(OTRegister)
            .join(IOLMaster, isouter=True)
            .filter(
                OTRegister.date_of_surgery >= f_date,
                OTRegister.date_of_surgery <= t_date,
            )
            .all()
        )

        data = defaultdict(lambda: defaultdict(int))
        totals = defaultdict(int)
        vue = defaultdict(int)

        for r in records:
            category = r.category or "Unknown"
            iol_name = r.iol.iol_name if r.iol else "No IOL"

            data[category][iol_name] += 1
            totals[category] += 1

            if r.is_vue:
                vue[category] += 1

        category_iol_data = dict(data)
        category_totals = dict(totals)
        vue_totals = dict(vue)

    return templates.TemplateResponse(
        "reports/category_iol_report.html",
        {
            "request": request,
            "from_date": from_date,
            "to_date": to_date,
            "category_iol_data": category_iol_data,
            "category_totals": category_totals,
            "vue_totals": vue_totals,   # ✅ now always exists
            "current_user": current_user,
        },
    )
from collections import defaultdict
from datetime import datetime

from datetime import datetime
from collections import defaultdict
from fastapi import Request, Depends
from sqlalchemy.orm import Session
from app.database import get_db
from app.models import OTRegister
from app.auth import require_login


@app.get("/reports/intravitreal")
def intravitreal_report(
    request: Request,
    from_date: str | None = None,
    to_date: str | None = None,
    db: Session = Depends(get_db),
    user_id: int = Depends(require_login),
):
    records = []
    category_totals = defaultdict(int)
    drug_totals = defaultdict(int)
    vue_total = 0

    if from_date and to_date:
        f_date = datetime.strptime(from_date, "%Y-%m-%d").date()
        t_date = datetime.strptime(to_date, "%Y-%m-%d").date()

        records = (
            db.query(OTRegister)
            .filter(
                OTRegister.surgery == "Intravitreal Injection",
                OTRegister.date_of_surgery >= f_date,
                OTRegister.date_of_surgery <= t_date,
            )
            .order_by(OTRegister.date_of_surgery)
            .all()
        )

        for r in records:
            category_totals[r.category] += 1

            if r.intravitreal_drug:
                drug_totals[r.intravitreal_drug.drug_name] += 1

            if r.is_vue:
                vue_total += 1

    return templates.TemplateResponse(
        "reports/intravitreal_report.html",
        {
            "request": request,
            "records": records,
            "from_date": from_date,
            "to_date": to_date,
            "category_totals": dict(category_totals),
            "drug_totals": dict(drug_totals),
            "vue_total": vue_total,
        },
    )




# ============================================================
# TELEGRAM BOT – LONG POLLING (NO WEBHOOK, NO NGROK)
# ============================================================

import os
import requests
import threading
import time
from datetime import date, timedelta
from sqlalchemy import func
from app.database import SessionLocal

# ----------------------------
# CONFIGURATION (from .env – loaded in app.database)
# ----------------------------
TELEGRAM_BOT_TOKEN = (os.getenv("TELEGRAM_BOT_TOKEN") or "").strip()
SURGEON_CHAT_ID = None
_tid = (os.getenv("TELEGRAM_CHAT_ID") or "").strip()
if _tid:
    try:
        SURGEON_CHAT_ID = int(_tid)
    except ValueError:
        pass
TELEGRAM_API = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}" if TELEGRAM_BOT_TOKEN else ""
# ------------------------------------------------------------
# SEND MESSAGE
# ------------------------------------------------------------
def send_telegram_message(text: str, parse_mode: str = "Markdown"):
    if not TELEGRAM_API or SURGEON_CHAT_ID is None:
        return
    try:
        requests.post(
            f"{TELEGRAM_API}/sendMessage",
            json={
                "chat_id": SURGEON_CHAT_ID,
                "text": text,
                "parse_mode": parse_mode,
            },
            timeout=10,
        )
    except Exception as e:
        print("Telegram send error:", e)


def send_telegram_photo(photo_bytes: bytes, filename: str = "sortsend.png"):
    """Send a photo (PNG/JPEG bytes) to the surgeon chat."""
    if not TELEGRAM_API or SURGEON_CHAT_ID is None:
        return
    try:
        requests.post(
            f"{TELEGRAM_API}/sendPhoto",
            data={"chat_id": SURGEON_CHAT_ID},
            files={"photo": (filename, photo_bytes, "image/png")},
            timeout=15,
        )
    except Exception as e:
        print("Telegram sendPhoto error:", e)


# ------------------------------------------------------------
# CASE COUNT — NEXT 14 DAYS
# ------------------------------------------------------------
def get_case_counts_next_14_days(db):

    today = date.today()
    end_date = today + timedelta(days=14)

    results = (
        db.query(
            OTRegister.date_of_surgery,
            func.count(OTRegister.id),
        )
        .filter(
            OTRegister.date_of_surgery >= today,
            OTRegister.date_of_surgery <= end_date,
        )
        .group_by(OTRegister.date_of_surgery)
        .order_by(OTRegister.date_of_surgery)
        .all()
    )

    if not results:
        return "📭 No cases next 14 days"

    lines = ["📅 *Upcoming Cases*\n"]
    total = 0

    for d, c in results:
        total += c
        lines.append(f"{d.strftime('%d/%m/%Y')} — *{c}*")

    lines.append(f"\n_Total: {total}_")
    return "\n".join(lines)


# ------------------------------------------------------------
# DAILY CASE LIST
# ------------------------------------------------------------
def get_cases_for_date(db, target_date):

    records = (
        db.query(OTRegister)
        .options(joinedload(OTRegister.iol))
        .filter(OTRegister.date_of_surgery == target_date)
        .order_by(OTRegister.id.asc())
        .all()
    )

    if not records:
        return f"📭 No cases for {target_date.strftime('%d/%m/%Y')}"

    lines = [
        f"📅 Cases — {target_date.strftime('%d/%m/%Y')}\n",
        "Sl | UHID | Patient | Eye | IOL | Cat",
        "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
    ]

    for i, r in enumerate(records, 1):

        name = r.patient_name + (" 🟢V" if r.is_vue else "")

        iol = f"{r.iol.iol_name}({r.iol.package})" if r.iol else "-"
        eye = r.eye[0] if r.eye else "-"

        lines.append(
            f"{i} | {r.patient_uhid} | {name[:14]} | "
            f"{eye} | {iol} | {r.category}"
        )

    lines.append("\n━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")
    lines.append(f"Total: {len(records)}")

    return "\n".join(lines)


# ------------------------------------------------------------
# SORT HELPERS
# ------------------------------------------------------------
# Category order for secondary sort (lower index = earlier in list)
_CATEGORY_ORDER = ("General", "Insurance", "MEDISEP", "ECHS", "VSSC", "FCI", "PMJAY")


def _display_uhid(uhid):
    """Keep only patient id part (e.g. 26/xxxxx); remove initial SKP..... prefix."""
    if not uhid:
        return "-"
    uhid = (uhid or "").strip()
    match = re.search(r"(\d+/\S+)", uhid)
    return match.group(1) if match else uhid



def _category_sort_key(category):
    """Return sort rank; lower = higher priority. Unknown/blank categories rank last."""
    if not category:
        return len(_CATEGORY_ORDER)
    c = (category or "").strip()
    try:
        return _CATEGORY_ORDER.index(c)
    except ValueError:
        return len(_CATEGORY_ORDER)  # others (any other category name)


def safe_cost(r):
    try:
        return float(re.findall(r"\d+", r.iol.package)[0])
    except:
        return 0


def get_sorted_ot_list(db, date_obj):

    records = (
        db.query(OTRegister)
        .options(joinedload(OTRegister.iol))
        .filter(OTRegister.date_of_surgery == date_obj)
        .all()
    )

    cataracts = []
    others = []

    for r in records:
        if (r.surgery or "").lower().startswith("cataract"):
            cataracts.append(r)
        else:
            others.append(r)

    left = [r for r in cataracts if (r.eye or "").lower() == "left"]
    right = [r for r in cataracts if (r.eye or "").lower() == "right"]

    # Primary: IOL (by cost desc); secondary: category (General > Insurance > ECHS > VSSC > others > PMJAY)
    def sort_key(r):
        return (-safe_cost(r), _category_sort_key(r.category))

    left.sort(key=sort_key)
    right.sort(key=sort_key)

    return left, right, others


def format_ot_message(left, right, others):

    msg = "📋 *Sorted OT*\n\n"

    if left or right:
        msg += "*Cataract*\n"

        if left:
            msg += "\nLEFT\n"
            for i, r in enumerate(left, 1):
                iol = r.iol.iol_name if r.iol else "-"
                cat = r.category or "-"
                msg += f"{i}|{_display_uhid(r.patient_uhid)}|{r.patient_name}|{cat}|{iol}\n"

        if right:
            msg += "\nRIGHT\n"
            for i, r in enumerate(right, 1):
                iol = r.iol.iol_name if r.iol else "-"
                cat = r.category or "-"
                msg += f"{i}|{_display_uhid(r.patient_uhid)}|{r.patient_name}|{cat}|{iol}\n"

    if others:
        msg += "\nOther\n"
        for i, r in enumerate(others, 1):
            cat = r.category or "-"
            msg += f"{i}|{_display_uhid(r.patient_uhid)}|{r.patient_name}|{cat}|{r.surgery}\n"

    return msg


def _cataract_slot_time(index):
    """Reporting time for cataract: index 0,1 -> 07:00am; 2 -> 07:30am; 3 -> 08:00am; ..."""
    if index <= 1:
        return "07:00am"
    total_mins = 7 * 60 + (index - 1) * 30
    h = total_mins // 60
    m = total_mins % 60
    if h < 12:
        return f"{h:02d}:{m:02d}am"
    elif h == 12:
        return f"12:{m:02d}pm"
    else:
        return f"{h - 12:02d}:{m:02d}pm"


def _minutes_to_slot_str(total_mins):
    """Convert minutes-from-midnight to slot string e.g. 07:00am, 12:30pm."""
    h = total_mins // 60
    m = total_mins % 60
    if h == 0:
        return f"12:{m:02d}am"
    if h < 12:
        return f"{h:02d}:{m:02d}am"
    if h == 12:
        return f"12:{m:02d}pm"
    return f"{h - 12:02d}:{m:02d}pm"


def get_sortsend_slots(db, date_obj):
    """
    Same sort as get_sorted_ot_list. Returns slot-assigned lists for sortsend:
    - left_slots, right_slots: list of (slot_str, record) for cataract (first 2 at 07:00am, then one per 30 min).
    - intravitreal_slots: (slot_str, list of records) for all intravitreal at one slot after last cataract.
    - pterygium_minor_slots: (slot_str, list of records) for all pterygium+minor at next slot.
    """
    left, right, others = get_sorted_ot_list(db, date_obj)
    n_cataract = len(left) + len(right)

    # Cataract slot sequence: 07:00, 07:00, 07:30, 08:00, ...
    cataract_slot_strs = [_cataract_slot_time(i) for i in range(n_cataract)]
    left_slots = [(cataract_slot_strs[i], left[i]) for i in range(len(left))]
    right_slots = [(cataract_slot_strs[len(left) + j], right[j]) for j in range(len(right))]

    # Last cataract slot -> next slot = intravitreal; next = pterygium/minor
    if n_cataract > 0:
        last_idx = n_cataract - 1
        last_minutes = 7 * 60 + (last_idx - 1) * 30 if last_idx > 1 else 7 * 60
        intravitreal_slot = _minutes_to_slot_str(last_minutes + 30)
        pterygium_slot = _minutes_to_slot_str(last_minutes + 60)
    else:
        intravitreal_slot = "07:00am"
        pterygium_slot = "07:30am"

    intravitreal = [r for r in others if (r.surgery or "").lower().find("intravitreal") >= 0]
    pterygium_minor = [r for r in others if r not in intravitreal]

    # If no intravitreal, pterygium/minor get the next slot after last cataract (not +60)
    if not intravitreal and n_cataract > 0:
        pterygium_slot = intravitreal_slot  # next available = last_cataract + 30
    elif not intravitreal and n_cataract == 0:
        pterygium_slot = "07:00am"

    return left_slots, right_slots, (intravitreal_slot, intravitreal), (pterygium_slot, pterygium_minor)


def format_ot_message_sortsend(left_slots, right_slots, intravitreal_pair, pterygium_minor_pair):
    """Format sortsend reply: slot|Sl.No|UHID|Patient name (no IOL/category). Same layout as before."""
    msg = "📋 *Sorted OT*\n\n"

    if left_slots or right_slots:
        msg += "*Cataract*\n"

        if left_slots:
            msg += "\nLEFT\n"
            for i, (slot, r) in enumerate(left_slots, 1):
                msg += f"{i}|{slot}|{_display_uhid(r.patient_uhid)}|{r.patient_name}\n"

        if right_slots:
            msg += "\nRIGHT\n"
            for i, (slot, r) in enumerate(right_slots, 1):
                msg += f"{i}|{slot}|{_display_uhid(r.patient_uhid)}|{r.patient_name}\n"

    intravitreal_slot, intravitreal_list = intravitreal_pair
    if intravitreal_list:
        msg += "\n*Intravitreal Injection*\n"
        for i, r in enumerate(intravitreal_list, 1):
            msg += f"{i}|{intravitreal_slot}|{_display_uhid(r.patient_uhid)}|{r.patient_name}|{r.surgery}\n"

    pterygium_slot, pterygium_minor_list = pterygium_minor_pair
    if pterygium_minor_list:
        msg += "\n*Pterygium / Minor*\n"
        for i, r in enumerate(pterygium_minor_list, 1):
            msg += f"{i}|{pterygium_slot}|{_display_uhid(r.patient_uhid)}|{r.patient_name}|{r.surgery}\n"

    return msg


def _get_table_font(size=14):
    """Load a readable font for the table image; fall back to default."""
    import sys
    try:
        from PIL import ImageFont
        if sys.platform == "win32":
            return ImageFont.truetype("C:/Windows/Fonts/arial.ttf", size)
        return ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", size)
    except Exception:
        try:
            from PIL import ImageFont
            return ImageFont.load_default()
        except Exception:
            return None


def _get_heading_font(size=22):
    """Load a bold, larger font for the image heading."""
    import sys
    try:
        from PIL import ImageFont
        if sys.platform == "win32":
            return ImageFont.truetype("C:/Windows/Fonts/arialbd.ttf", size)
        return ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", size)
    except Exception:
        return _get_table_font(size)


def generate_sortsend_png(
    left_slots, right_slots, intravitreal_pair, pterygium_minor_pair, date_str: str
) -> bytes:
    """Generate a PNG image of the sortsend list with colored columns. Returns PNG bytes."""
    from PIL import Image, ImageDraw, ImageFont

    # Column colors (RGB): header, Sl.No, Time, UHID, Patient name, Surgery
    HEADER_BG = (45, 55, 72)
    HEADER_FG = (255, 255, 255)
    COL_SLNO_BG = (224, 242, 254)   # light blue
    COL_TIME_BG = (220, 252, 231)   # light green
    COL_UHID_BG = (254, 249, 195)   # light yellow
    COL_NAME_BG = (248, 250, 252)   # light gray
    COL_SURG_BG = (255, 237, 213)  # light orange
    ROW_BORDER = (203, 213, 225)
    FONT_COLOR = (30, 41, 59)

    font = _get_table_font(14)
    font_section = _get_table_font(16)
    if font is None:
        try:
            font = ImageFont.load_default()
        except Exception:
            font = None
    if font_section is None:
        font_section = font

    cell_pad_x = 10
    cell_pad_y = 6
    col_w = (50, 80, 135, 220, 180)  # Sl.No, Time, UHID (+5 chars), Name, Surgery
    row_h = cell_pad_y * 2 + 18
    section_gap = 3   # reduced gap between section label (LEFT/RIGHT/Pterygium) and table below

    def draw_row(draw, x, y, cells, colors, is_header=False):
        cx = x
        for i, (text, bg) in enumerate(zip(cells, colors)):
            w = col_w[i] if i < len(col_w) else col_w[-1]
            draw.rectangle([cx, y, cx + w, y + row_h], fill=bg, outline=ROW_BORDER)
            if text and font:
                draw.text((cx + cell_pad_x, y + cell_pad_y), str(text), fill=FONT_COLOR if not is_header else HEADER_FG, font=font)
            cx += w
        return y + row_h

    # Build rows: (section_title, [(cells), ...])
    rows_data = []
    if left_slots or right_slots:
        rows_data.append(("Cataract", None))
        if left_slots:
            rows_data.append(("LEFT EYE", None))
            rows_data.append((None, [("Sl.No", "Time", "UHID", "Patient name")]))
            for i, (slot, r) in enumerate(left_slots, 1):
                rows_data.append((None, (str(i), slot, _display_uhid(r.patient_uhid), (r.patient_name or "")[:28])))
        if right_slots:
            rows_data.append(("RIGHT EYE", None))
            rows_data.append((None, [("Sl.No", "Time", "UHID", "Patient name")]))
            for i, (slot, r) in enumerate(right_slots, 1):
                rows_data.append((None, (str(i), slot, _display_uhid(r.patient_uhid), (r.patient_name or "")[:28])))

    intravitreal_slot, intravitreal_list = intravitreal_pair
    if intravitreal_list:
        rows_data.append(("Intravitreal Injection", None))
        rows_data.append((None, [("Sl.No", "Time", "UHID", "Patient name", "Surgery")]))
        for i, r in enumerate(intravitreal_list, 1):
            rows_data.append((None, (str(i), intravitreal_slot, _display_uhid(r.patient_uhid), (r.patient_name or "")[:28], (r.surgery or "")[:24])))

    pterygium_slot, pterygium_minor_list = pterygium_minor_pair
    if pterygium_minor_list:
        rows_data.append(("Pterygium / Minor", None))
        rows_data.append((None, [("Sl.No", "Time", "UHID", "Patient name", "Surgery")]))
        for i, r in enumerate(pterygium_minor_list, 1):
            rows_data.append((None, (str(i), pterygium_slot, _display_uhid(r.patient_uhid), (r.patient_name or "")[:28], (r.surgery or "")[:24])))

    if not rows_data:
        # Empty list
        img_w = 600
        img_h = 120
        img = Image.new("RGB", (img_w, img_h), (255, 255, 255))
        draw = ImageDraw.Draw(img)
        if font:
            draw.text((20, 40), "No cases for this date.", fill=(100, 100, 100), font=font)
        buf = io.BytesIO()
        img.save(buf, format="PNG")
        return buf.getvalue()

    total_w = sum(col_w)
    total_h = 90   # space for two-line heading
    for section_or_none, row_or_none in rows_data:
        if section_or_none:
            total_h += row_h + section_gap
        if row_or_none:
            total_h += row_h

    img = Image.new("RGB", (total_w + 40, total_h + 40), (255, 255, 255))
    draw = ImageDraw.Draw(img)

    # Heading: centre-aligned, larger bold font, deep blue; date in a box
    HEADING_BLUE = (0, 51, 102)
    DATE_BOX_BORDER = (0, 51, 102)
    DATE_BOX_FILL = (240, 248, 255)
    img_w = img.size[0]
    font_heading = _get_heading_font(22)
    y = 12
    if font_heading:
        line1 = "Sreekantapuram Hospital"
        bbox1 = draw.textbbox((0, 0), line1, font=font_heading)
        x1 = (img_w - (bbox1[2] - bbox1[0])) // 2
        draw.text((x1, y), line1, fill=HEADING_BLUE, font=font_heading)
        y += 28

        label2 = "Ophthalmology OT list  "
        line2_date = date_str
        bbox_label = draw.textbbox((0, 0), label2, font=font_heading)
        bbox_date = draw.textbbox((0, 0), line2_date, font=font_heading)
        w_label = bbox_label[2] - bbox_label[0]
        w_date = bbox_date[2] - bbox_date[0]
        total_line_w = w_label + 8 + w_date + 16
        x_start = (img_w - total_line_w) // 2
        draw.text((x_start, y), label2, fill=HEADING_BLUE, font=font_heading)
        date_x = x_start + w_label + 8
        date_y = y
        pad = 6
        box_left = date_x - pad
        box_top = date_y - 2
        box_right = date_x + w_date + pad
        box_bottom = date_y + (bbox_date[3] - bbox_date[1]) + 4
        draw.rectangle([box_left, box_top, box_right, box_bottom], fill=DATE_BOX_FILL, outline=DATE_BOX_BORDER, width=2)
        draw.text((date_x, date_y), line2_date, fill=HEADING_BLUE, font=font_heading)
        y += 32
    else:
        y += 36

    header_colors = [HEADER_BG] * 5
    data_colors_4 = [COL_SLNO_BG, COL_TIME_BG, COL_UHID_BG, COL_NAME_BG]
    data_colors_5 = [COL_SLNO_BG, COL_TIME_BG, COL_UHID_BG, COL_NAME_BG, COL_SURG_BG]

    for section_or_none, row_or_none in rows_data:
        if section_or_none:
            if font_section:
                draw.text((20, y), section_or_none, fill=(59, 130, 246), font=font_section)
            y += row_h + section_gap
        if row_or_none:
            if isinstance(row_or_none[0], (list, tuple)):
                for r in row_or_none:
                    cells = list(r) if len(r) > 1 else [r]
                    is_header = cells and str(cells[0]) == "Sl.No"
                    colors = header_colors[: len(cells)] if is_header else (data_colors_5 if len(cells) == 5 else data_colors_4)[: len(cells)]
                    y = draw_row(draw, 20, y, cells, colors, is_header=is_header)
            else:
                cells = list(row_or_none)
                is_header = cells and str(cells[0]) == "Sl.No"
                colors = header_colors[: len(cells)] if is_header else (data_colors_5 if len(cells) == 5 else data_colors_4)[: len(cells)]
                y = draw_row(draw, 20, y, cells, colors, is_header=is_header)

    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


def generate_sort_png(left, right, others, date_str: str) -> bytes:
    """Generate a PNG image of the sort list (Sl.No, UHID, Patient name, Category, IOL/Surgery). Same heading as sortsend."""
    from PIL import Image, ImageDraw, ImageFont

    HEADER_BG = (45, 55, 72)
    HEADER_FG = (255, 255, 255)
    COL_SLNO_BG = (224, 242, 254)
    COL_UHID_BG = (254, 249, 195)
    COL_NAME_BG = (248, 250, 252)
    COL_CAT_BG = (233, 213, 255)
    COL_IOL_BG = (255, 237, 213)
    ROW_BORDER = (203, 213, 225)
    FONT_COLOR = (30, 41, 59)
    HEADING_BLUE = (0, 51, 102)
    DATE_BOX_BORDER = (0, 51, 102)
    DATE_BOX_FILL = (240, 248, 255)

    font = _get_table_font(14)
    font_section = _get_table_font(16)
    if font is None:
        try:
            font = ImageFont.load_default()
        except Exception:
            font = None
    if font_section is None:
        font_section = font

    cell_pad_x = 10
    cell_pad_y = 6
    col_w_sort = (50, 135, 200, 95, 190)  # Sl.No, UHID, Name, Category, IOL/Surgery
    row_h = cell_pad_y * 2 + 18
    section_gap = 3

    def draw_row(draw, x, y, cells, colors, is_header=False):
        cx = x
        for i, (text, bg) in enumerate(zip(cells, colors)):
            w = col_w_sort[i] if i < len(col_w_sort) else col_w_sort[-1]
            draw.rectangle([cx, y, cx + w, y + row_h], fill=bg, outline=ROW_BORDER)
            if text and font:
                draw.text((cx + cell_pad_x, y + cell_pad_y), str(text)[:32], fill=FONT_COLOR if not is_header else HEADER_FG, font=font)
            cx += w
        return y + row_h

    rows_data = []
    if left or right:
        rows_data.append(("Cataract", None))
        if left:
            rows_data.append(("LEFT", None))
            rows_data.append((None, [("Sl.No", "UHID", "Patient name", "Category", "IOL")]))
            for i, r in enumerate(left, 1):
                iol = (r.iol.iol_name if r.iol else "-")[:24]
                rows_data.append((None, (str(i), _display_uhid(r.patient_uhid), (r.patient_name or "")[:28], (r.category or "-")[:12], iol)))
        if right:
            rows_data.append(("RIGHT", None))
            rows_data.append((None, [("Sl.No", "UHID", "Patient name", "Category", "IOL")]))
            for i, r in enumerate(right, 1):
                iol = (r.iol.iol_name if r.iol else "-")[:24]
                rows_data.append((None, (str(i), _display_uhid(r.patient_uhid), (r.patient_name or "")[:28], (r.category or "-")[:12], iol)))
    if others:
        rows_data.append(("Other", None))
        rows_data.append((None, [("Sl.No", "UHID", "Patient name", "Category", "Surgery")]))
        for i, r in enumerate(others, 1):
            rows_data.append((None, (str(i), _display_uhid(r.patient_uhid), (r.patient_name or "")[:28], (r.category or "-")[:12], (r.surgery or "")[:24])))

    if not rows_data:
        img = Image.new("RGB", (600, 120), (255, 255, 255))
        draw = ImageDraw.Draw(img)
        if font:
            draw.text((20, 40), "No cases for this date.", fill=(100, 100, 100), font=font)
        buf = io.BytesIO()
        img.save(buf, format="PNG")
        return buf.getvalue()

    total_w = sum(col_w_sort)
    total_h = 90
    for section_or_none, row_or_none in rows_data:
        if section_or_none:
            total_h += row_h + section_gap
        if row_or_none:
            total_h += row_h

    img = Image.new("RGB", (total_w + 40, total_h + 40), (255, 255, 255))
    draw = ImageDraw.Draw(img)
    img_w = img.size[0]
    font_heading = _get_heading_font(22)
    y = 12
    if font_heading:
        line1 = "Sreekantapuram Hospital"
        bbox1 = draw.textbbox((0, 0), line1, font=font_heading)
        x1 = (img_w - (bbox1[2] - bbox1[0])) // 2
        draw.text((x1, y), line1, fill=HEADING_BLUE, font=font_heading)
        y += 28
        label2 = "Ophthalmology OT list  "
        line2_date = date_str
        bbox_label = draw.textbbox((0, 0), label2, font=font_heading)
        bbox_date = draw.textbbox((0, 0), line2_date, font=font_heading)
        w_label = bbox_label[2] - bbox_label[0]
        w_date = bbox_date[2] - bbox_date[0]
        total_line_w = w_label + 8 + w_date + 16
        x_start = (img_w - total_line_w) // 2
        draw.text((x_start, y), label2, fill=HEADING_BLUE, font=font_heading)
        date_x = x_start + w_label + 8
        date_y = y
        pad = 6
        draw.rectangle([date_x - pad, date_y - 2, date_x + w_date + pad, date_y + (bbox_date[3] - bbox_date[1]) + 4], fill=DATE_BOX_FILL, outline=DATE_BOX_BORDER, width=2)
        draw.text((date_x, date_y), line2_date, fill=HEADING_BLUE, font=font_heading)
        y += 32
    else:
        y += 36

    header_colors = [HEADER_BG] * 5
    data_colors = [COL_SLNO_BG, COL_UHID_BG, COL_NAME_BG, COL_CAT_BG, COL_IOL_BG]
    for section_or_none, row_or_none in rows_data:
        if section_or_none:
            if font_section:
                draw.text((20, y), section_or_none, fill=(59, 130, 246), font=font_section)
            y += row_h + section_gap
        if row_or_none:
            if isinstance(row_or_none[0], (list, tuple)):
                for r in row_or_none:
                    cells = list(r) if len(r) > 1 else [r]
                    is_header = cells and str(cells[0]) == "Sl.No"
                    colors = header_colors[: len(cells)] if is_header else data_colors[: len(cells)]
                    y = draw_row(draw, 20, y, cells, colors, is_header=is_header)
            else:
                cells = list(row_or_none)
                is_header = cells and str(cells[0]) == "Sl.No"
                colors = header_colors[: len(cells)] if is_header else data_colors[: len(cells)]
                y = draw_row(draw, 20, y, cells, colors, is_header=is_header)

    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


# ------------------------------------------------------------
# MONTH SUMMARY
# ------------------------------------------------------------
def get_month_summary(db, month, year, label):

    records = (
        db.query(OTRegister)
        .options(joinedload(OTRegister.iol))
        .filter(
            func.extract("month", OTRegister.date_of_surgery) == month,
            func.extract("year", OTRegister.date_of_surgery) == year,
        )
        .all()
    )

    if not records:
        return f"📭 No cases for {label}"

    surgery = defaultdict(int)
    category = defaultdict(int)
    iol = defaultdict(int)

    for r in records:
        surgery[r.surgery] += 1
        category[r.category] += 1

        if r.iol:
            name = f"{r.iol.iol_name}({r.iol.package})"
        else:
            name = "No IOL"

        iol[name] += 1

    lines = [f"📊 *Case Summary — {label}*\n"]

    lines.append("*🩺 Surgery*")
    for k, v in surgery.items():
        lines.append(f"{k}: {v}")

    lines.append("\n*👥 Category*")
    for k, v in category.items():
        lines.append(f"{k}: {v}")

    lines.append("\n*👁 IOL*")
    for k, v in iol.items():
        lines.append(f"{k}: {v}")

    lines.append(f"\n_Total: {len(records)}_")

    return "\n".join(lines)


    import re
# ============================================================
# TELEGRAM POLLING LOOP
# ============================================================
def telegram_polling_loop():
    if not TELEGRAM_API or SURGEON_CHAT_ID is None:
        print("⚠️ Telegram bot disabled: set TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID in .env (in project root)")
        return
    offset = None
    print("✅ Telegram polling ACTIVE (chat_id=%s)" % SURGEON_CHAT_ID)

    while True:
        try:
            resp = requests.get(
                f"{TELEGRAM_API}/getUpdates",
                params={"timeout": 30, "offset": offset},
                timeout=35,
            ).json()

            for update in resp.get("result", []):

                offset = update["update_id"] + 1

                message = update.get("message", {})
                chat_id = message.get("chat", {}).get("id")
                raw = message.get("text", "")
                text = raw.replace("\n", " ").strip().lower()

                print("CMD:", text)

                if chat_id != SURGEON_CHAT_ID:
                    continue

                # =====================================
                # CMD — list available commands
                # =====================================
                if text == "cmd":
                    send_telegram_message(
                        "*Available commands*\n\n"
                        "• *cmd* — show this list\n"
                        "• *sort dd/mm/yyyy* — sorted OT list (by IOL, then category) with UHID, name, category, IOL\n"
                        "• *sortsend dd/mm/yyyy* — same sort, reply without IOL and category\n"
                        "• *cased dd/mm/yyyy* — cases for that date\n"
                        "• *case* — case counts for next 14 days\n"
                        "• *caseMMYY* — month summary (e.g. case0226 = Feb 2026)"
                    )
                    continue

                # =====================================
                # SORTSEND dd/mm/yyyy (same as sort, output without IOL and category)
                # =====================================
                if text.startswith("sortsend"):

                    match = re.search(r"\d{2}/\d{2}/\d{4}", text)

                    if not match:
                        send_telegram_message("Use: sortsend dd/mm/yyyy")
                        continue

                    target = datetime.strptime(
                        match.group(), "%d/%m/%Y"
                    ).date()

                    db = SessionLocal()
                    try:
                        left_slots, right_slots, intravitreal_pair, pterygium_minor_pair = get_sortsend_slots(db, target)
                        intravitreal_slot, intravitreal_list = intravitreal_pair
                        pterygium_slot, pterygium_minor_list = pterygium_minor_pair
                        has_cases = left_slots or right_slots or intravitreal_list or pterygium_minor_list
                        if has_cases:
                            date_str = target.strftime("%d/%m/%Y")
                            png_bytes = generate_sortsend_png(
                                left_slots, right_slots, intravitreal_pair, pterygium_minor_pair, date_str
                            )
                            send_telegram_photo(png_bytes, f"sortsend_{target:%Y-%m-%d}.png")
                        else:
                            send_telegram_message("No cases for this date.")
                    finally:
                        db.close()

                    continue

                # =====================================
                # SORT dd/mm/yyyy (reply as image, same style as sortsend)
                # =====================================
                if text.startswith("sort"):

                    match = re.search(r"\d{2}/\d{2}/\d{4}", text)

                    if not match:
                        send_telegram_message("Use: sort dd/mm/yyyy")
                        continue

                    target = datetime.strptime(
                        match.group(), "%d/%m/%Y"
                    ).date()

                    db = SessionLocal()
                    try:
                        left, right, others = get_sorted_ot_list(db, target)
                        if left or right or others:
                            date_str = target.strftime("%d/%m/%Y")
                            png_bytes = generate_sort_png(left, right, others, date_str)
                            send_telegram_photo(png_bytes, f"sort_{target:%Y-%m-%d}.png")
                        else:
                            send_telegram_message("No cases for this date.")
                    finally:
                        db.close()

                    continue


                # =====================================
                # CASED dd/mm/yyyy
                # =====================================
                if text.startswith("cased"):

                    match = re.search(r"\d{2}/\d{2}/\d{4}", text)

                    if not match:
                        send_telegram_message("Use: cased dd/mm/yyyy")
                        continue

                    target = datetime.strptime(
                        match.group(), "%d/%m/%Y"
                    ).date()

                    db = SessionLocal()
                    try:
                        reply = get_cases_for_date(db, target)
                    finally:
                        db.close()

                    send_telegram_message(reply)
                    continue


                # =====================================
                # SIMPLE CASE
                # =====================================
                if text == "case":

                    db = SessionLocal()
                    try:
                        reply = get_case_counts_next_14_days(db)
                    finally:
                        db.close()

                    send_telegram_message(reply)
                    continue


              # =====================================
                # MONTH SUMMARY (STRICT caseMMYY)
                # =====================================
                if text.startswith("case") and text != "case":

                    token = text.replace("case", "").strip()

                    # Must be EXACTLY 4 digits
                    if not token.isdigit() or len(token) != 4:
                        send_telegram_message("Use format:\ncase0226")
                        continue

                    month = int(token[:2])
                    year = 2000 + int(token[2:])

                    # Safety validation
                    if month < 1 or month > 12:
                        send_telegram_message("Invalid month")
                        continue

                    if year < 2020:
                        send_telegram_message("Invalid year")
                        continue

                    db = SessionLocal()
                    try:
                        label = datetime(year, month, 1).strftime("%B %Y")
                        reply = get_month_summary(db, month, year, label)
                    finally:
                        db.close()

                    send_telegram_message(reply)
                    continue

        except Exception as e:
            print("Telegram polling error:", e)

        time.sleep(2)





# ------------------------------------------------------------
# DAILY 11AM AUTO-SEND (sort + sortsend for tomorrow's date; only if cases exist)
# ------------------------------------------------------------
def daily_11am_auto_send_loop():
    """Every day at 11:00 AM local time, send sort and sortsend images for *tomorrow's* date. Send only if cases are posted."""
    while True:
        now = datetime.now()
        today_11 = now.replace(hour=11, minute=0, second=0, microsecond=0)
        if now >= today_11:
            next_11 = today_11 + timedelta(days=1)
        else:
            next_11 = today_11
        sleep_secs = (next_11 - now).total_seconds()
        if sleep_secs > 0:
            time.sleep(sleep_secs)

        target_date = date.today() + timedelta(days=1)
        db = SessionLocal()
        try:
            left, right, others = get_sorted_ot_list(db, target_date)
            if not (left or right or others):
                continue
            date_str = target_date.strftime("%d/%m/%Y")
            sort_png = generate_sort_png(left, right, others, date_str)
            send_telegram_photo(sort_png, f"sort_{target_date:%Y-%m-%d}.png")

            left_slots, right_slots, intravitreal_pair, pterygium_minor_pair = get_sortsend_slots(db, target_date)
            sortsend_png = generate_sortsend_png(left_slots, right_slots, intravitreal_pair, pterygium_minor_pair, date_str)
            send_telegram_photo(sortsend_png, f"sortsend_{target_date:%Y-%m-%d}.png")
        finally:
            db.close()


# ------------------------------------------------------------
# START THREAD SAFELY
# ------------------------------------------------------------
@app.on_event("startup")
async def start_bot():
    threading.Thread(
        target=telegram_polling_loop,
        daemon=True
    ).start()
    threading.Thread(
        target=daily_11am_auto_send_loop,
        daemon=True
    ).start()


