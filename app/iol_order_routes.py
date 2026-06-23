"""Routes for IOL ordering, supplier master, and related APIs."""

import os

from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session, joinedload
from urllib.parse import quote

from app.auth import require_module
from app.database import get_db
from app.iol_order_service import (
    STATUS_MISMATCH_POWER,
    STATUS_MISMATCH_TYPE,
    STATUS_ORDERED,
    can_place_order,
    create_iol_order,
    format_iol_power_display,
    latest_iol_order,
    order_jpg_full_path,
    receive_iol_verified,
    report_lens_mismatch,
    resolve_mismatch,
    status_display_label,
)
from app.models import IOLMaster, IOLSupplier, IOLOrder, OTRegister, User

router = APIRouter()
templates = Jinja2Templates(directory="app/templates")


def _json_error(message: str, status: int = 400) -> JSONResponse:
    return JSONResponse({"ok": False, "error": message}, status_code=status)


# -----------------------------
# Supplier master (admin)
# -----------------------------
@router.get("/admin/suppliers")
def supplier_master_page(
    request: Request,
    db: Session = Depends(get_db),
    admin: User = Depends(require_module("admin_suppliers")),
):
    suppliers = db.query(IOLSupplier).order_by(IOLSupplier.supplier_name.asc()).all()
    return templates.TemplateResponse(
        "admin_supplier_master.html",
        {
            "request": request,
            "suppliers": suppliers,
            "current_user": admin,
        },
    )


@router.post("/admin/suppliers/add")
def supplier_add(
    supplier_name: str = Form(...),
    supplier_phone: str = Form(...),
    contact_person_name: str = Form(...),
    contact_person_phone: str = Form(...),
    _admin: User = Depends(require_module("admin_suppliers")),
    db: Session = Depends(get_db),
):
    db.add(
        IOLSupplier(
            supplier_name=supplier_name.strip(),
            supplier_phone=supplier_phone.strip(),
            contact_person_name=contact_person_name.strip(),
            contact_person_phone=contact_person_phone.strip(),
        )
    )
    db.commit()
    return RedirectResponse("/admin/suppliers", status_code=303)


@router.post("/admin/suppliers/{supplier_id}/edit")
def supplier_edit(
    supplier_id: int,
    supplier_name: str = Form(...),
    supplier_phone: str = Form(...),
    contact_person_name: str = Form(...),
    contact_person_phone: str = Form(...),
    _admin: User = Depends(require_module("admin_suppliers")),
    db: Session = Depends(get_db),
):
    s = db.query(IOLSupplier).filter(IOLSupplier.id == supplier_id).first()
    if not s:
        raise HTTPException(404, "Supplier not found")
    s.supplier_name = supplier_name.strip()
    s.supplier_phone = supplier_phone.strip()
    s.contact_person_name = contact_person_name.strip()
    s.contact_person_phone = contact_person_phone.strip()
    db.commit()
    return RedirectResponse("/admin/suppliers", status_code=303)


@router.post("/admin/suppliers/{supplier_id}/delete")
def supplier_delete(
    supplier_id: int,
    _admin: User = Depends(require_module("admin_suppliers")),
    db: Session = Depends(get_db),
):
    s = db.query(IOLSupplier).filter(IOLSupplier.id == supplier_id).first()
    if not s:
        raise HTTPException(404, "Supplier not found")
    in_use = db.query(IOLMaster).filter(IOLMaster.supplier_id == supplier_id).first()
    if in_use:
        return RedirectResponse(
            "/admin/suppliers?error=in_use",
            status_code=303,
        )
    db.delete(s)
    db.commit()
    return RedirectResponse("/admin/suppliers", status_code=303)


# -----------------------------
# IOL order APIs (dashboard)
# -----------------------------
@router.get("/api/iol-orders/meta")
def iol_orders_meta(
    db: Session = Depends(get_db),
    user: User = Depends(require_module("dashboard")),
):
    iols = (
        db.query(IOLMaster)
        .options(joinedload(IOLMaster.supplier))
        .order_by(IOLMaster.iol_name.asc())
        .all()
    )
    return {
        "iols": [
            {
                "id": i.id,
                "name": i.iol_name,
                "package": i.package,
                "supplier_id": i.supplier_id,
                "supplier_name": i.supplier.supplier_name if i.supplier else None,
                "has_supplier": bool(i.supplier_id),
            }
            for i in iols
        ]
    }


@router.post("/api/iol-orders")
async def api_create_iol_order(
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(require_module("dashboard")),
):
    body = await request.json()
    try:
        ot_id = int(body.get("ot_register_id"))
        iol_id = int(body.get("iol_id"))
        power = body.get("iol_power", "")
    except (TypeError, ValueError):
        return _json_error("Invalid request")

    try:
        order = create_iol_order(
            db,
            ot_register_id=ot_id,
            iol_id=iol_id,
            iol_power=power,
            user=user,
        )
        order = (
            db.query(IOLOrder)
            .options(joinedload(IOLOrder.iol))
            .filter(IOLOrder.id == order.id)
            .first()
        )
    except ValueError as e:
        return _json_error(str(e))

    return {
        "ok": True,
        "order": _order_json(order),
        "jpg_url": f"/api/iol-orders/{order.id}/jpg",
    }


@router.post("/api/iol-orders/{order_id}/receive")
async def api_receive_iol(
    order_id: int,
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(require_module("dashboard")),
):
    body = await request.json()
    try:
        iol_id = int(body.get("iol_id"))
        power = body.get("iol_power", "")
        verified = bool(body.get("verified"))
    except (TypeError, ValueError):
        return _json_error("Invalid request")

    try:
        order = receive_iol_verified(
            db,
            order_id=order_id,
            iol_id=iol_id,
            iol_power=power,
            verified=verified,
            user=user,
        )
    except ValueError as e:
        return _json_error(str(e))

    return {"ok": True, "order": _order_json(order)}


@router.post("/api/iol-orders/{order_id}/mismatch")
async def api_mismatch_iol(
    order_id: int,
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(require_module("dashboard")),
):
    body = await request.json()
    kind = (body.get("mismatch_kind") or "").strip()
    try:
        order = report_lens_mismatch(
            db, order_id=order_id, mismatch_kind=kind, user=user
        )
    except ValueError as e:
        return _json_error(str(e))
    return {"ok": True, "order": _order_json(order)}


@router.post("/api/iol-orders/{order_id}/resolve")
async def api_resolve_mismatch(
    order_id: int,
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(require_module("dashboard")),
):
    body = await request.json()
    action = (body.get("resolution_action") or "").strip()
    notes = body.get("resolution_notes")
    reorder_iol_id = body.get("reorder_iol_id")
    reorder_power = body.get("reorder_iol_power")
    try:
        if reorder_iol_id is not None:
            reorder_iol_id = int(reorder_iol_id)
    except (TypeError, ValueError):
        reorder_iol_id = None

    try:
        order = resolve_mismatch(
            db,
            order_id=order_id,
            resolution_action=action,
            resolution_notes=notes,
            user=user,
            reorder_iol_id=reorder_iol_id,
            reorder_iol_power=reorder_power,
        )
    except ValueError as e:
        return _json_error(str(e))

    out = {"ok": True, "order": _order_json(order)}
    if order.superseded_by_order_id:
        new_o = db.query(IOLOrder).filter(IOLOrder.id == order.superseded_by_order_id).first()
        if new_o:
            out["new_order"] = _order_json(new_o)
    return out


@router.get("/api/iol-orders/{order_id}/jpg")
def api_order_jpg(
    order_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(require_module("dashboard")),
):
    order = db.query(IOLOrder).filter(IOLOrder.id == order_id).first()
    if not order:
        raise HTTPException(404, "Order not found")
    path = order_jpg_full_path(order)
    if not path or not os.path.isfile(path):
        raise HTTPException(404, "Order slip not found")
    return FileResponse(path, media_type="image/jpeg", filename=order.order_jpg_path)


def _order_json(order: IOLOrder) -> dict:
    return {
        "id": order.id,
        "ot_register_id": order.ot_register_id,
        "iol_id": order.iol_id,
        "iol_name": order.iol.iol_name if order.iol else "",
        "iol_power": order.iol_power,
        "iol_power_display": format_iol_power_display(order.iol_power),
        "status": order.status,
        "status_label": status_display_label(order.status),
        "ordered_at": order.ordered_at.strftime("%d/%m/%Y %H:%M") if order.ordered_at else "",
        "ordered_at_date": order.ordered_at.strftime("%d/%m/%Y") if order.ordered_at else "",
        "can_receive": order.status == STATUS_ORDERED,
        "can_resolve_mismatch": order.status in (STATUS_MISMATCH_TYPE, STATUS_MISMATCH_POWER),
        "jpg_url": f"/api/iol-orders/{order.id}/jpg",
    }
