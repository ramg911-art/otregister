"""IOL ordering: validation, status workflow, order-slip JPG generation."""

from __future__ import annotations

import io
import os
import re
from datetime import datetime

from sqlalchemy import extract, func
from sqlalchemy.orm import Session, joinedload

from app.models import IOLOrder, IOLOrderStatusLog, IOLMaster, IOLSupplier, OTRegister, User

# Status constants
STATUS_ORDERED = "ordered"
STATUS_LENS_DELIVERED = "lens_delivered"
STATUS_MISMATCH_TYPE = "mismatch_type"
STATUS_MISMATCH_POWER = "mismatch_power"
STATUS_RESOLVED_REORDERED = "resolved_reordered"
STATUS_RESOLVED_POSTPONED = "resolved_postponed"
STATUS_RESOLVED_OTHER = "resolved_other"

ACTIVE_STATUSES = frozenset(
    {STATUS_ORDERED, STATUS_MISMATCH_TYPE, STATUS_MISMATCH_POWER}
)
TERMINAL_STATUSES = frozenset(
    {STATUS_LENS_DELIVERED, STATUS_RESOLVED_POSTPONED, STATUS_RESOLVED_OTHER}
)

POWER_RE = re.compile(r"^\+\d{1,2}\.\d{2}$")

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
IOL_ORDER_UPLOAD_DIR = os.path.join(BASE_DIR, "uploads", "iol_orders")
HOSPITAL_LOGO_PATH = os.path.join(BASE_DIR, "app", "static", "img", "skp_logo.png")


def ensure_upload_dir() -> str:
    os.makedirs(IOL_ORDER_UPLOAD_DIR, exist_ok=True)
    return IOL_ORDER_UPLOAD_DIR


def normalize_iol_power(raw: str) -> str:
    """Accept +20.50 or +20.50D → stored as +20.50."""
    s = (raw or "").strip().upper().rstrip("D").strip()
    if not POWER_RE.match(s):
        raise ValueError("IOL power must be in format +xx.xx (e.g. +20.50)")
    return s


def format_iol_power_display(power: str) -> str:
    p = (power or "").strip()
    if not p:
        return ""
    if p.upper().endswith("D"):
        return p
    return f"{p}D"


def allocate_order_number(db: Session, when: datetime) -> str:
    """Format mmyyno — e.g. 10th order in June 2026 → 062610."""
    mm = when.month
    yy = when.year % 100
    prefix = f"{mm:02d}{yy:02d}"
    n = (
        db.query(func.count(IOLOrder.id))
        .filter(
            extract("month", IOLOrder.ordered_at) == mm,
            extract("year", IOLOrder.ordered_at) == when.year,
        )
        .scalar()
    ) or 0
    return f"{prefix}{int(n) + 1}"


def order_jpg_filename(patient_name: str, iol_power: str, upload_dir: str) -> str:
    """patientname_IOL_power.jpg (sanitized, unique if collision)."""
    raw_name = (patient_name or "patient").strip()
    name_part = re.sub(r"[^\w]+", "_", raw_name, flags=re.UNICODE)
    name_part = re.sub(r"_+", "_", name_part).strip("_")[:50] or "patient"
    power_part = format_iol_power_display(iol_power).replace(" ", "")
    base = f"{name_part}_{power_part}"
    filename = f"{base}.jpg"
    if not os.path.exists(os.path.join(upload_dir, filename)):
        return filename
    i = 2
    while True:
        filename = f"{base}_{i}.jpg"
        if not os.path.exists(os.path.join(upload_dir, filename)):
            return filename
        i += 1


def is_cataract_case(record: OTRegister) -> bool:
    return (record.surgery or "").lower().startswith("cataract")


def latest_iol_order(db: Session, ot_register_id: int) -> IOLOrder | None:
    return (
        db.query(IOLOrder)
        .options(
            joinedload(IOLOrder.iol).joinedload(IOLMaster.supplier),
            joinedload(IOLOrder.ordered_by),
            joinedload(IOLOrder.received_by),
        )
        .filter(IOLOrder.ot_register_id == ot_register_id)
        .order_by(IOLOrder.id.desc())
        .first()
    )


def latest_orders_for_ot_ids(db: Session, ot_ids: list[int]) -> dict[int, IOLOrder]:
    if not ot_ids:
        return {}
    orders = (
        db.query(IOLOrder)
        .options(
            joinedload(IOLOrder.iol).joinedload(IOLMaster.supplier),
            joinedload(IOLOrder.ordered_by),
        )
        .filter(IOLOrder.ot_register_id.in_(ot_ids))
        .order_by(IOLOrder.ot_register_id, IOLOrder.id.desc())
        .all()
    )
    out: dict[int, IOLOrder] = {}
    for o in orders:
        if o.ot_register_id not in out:
            out[o.ot_register_id] = o
    return out


def can_place_order(order: IOLOrder | None) -> bool:
    if order is None:
        return True
    if order.status in TERMINAL_STATUSES:
        return True
    if order.status == STATUS_RESOLVED_REORDERED:
        return True
    return False


def _log_status(
    db: Session,
    order: IOLOrder,
    *,
    action: str,
    from_status: str | None,
    to_status: str,
    user_id: int,
    notes: str | None = None,
) -> None:
    db.add(
        IOLOrderStatusLog(
            iol_order_id=order.id,
            action=action,
            from_status=from_status,
            to_status=to_status,
            user_id=user_id,
            notes=notes,
            created_at=datetime.now(),
        )
    )


def _get_iol_with_supplier(db: Session, iol_id: int) -> IOLMaster:
    iol = (
        db.query(IOLMaster)
        .options(joinedload(IOLMaster.supplier))
        .filter(IOLMaster.id == iol_id)
        .first()
    )
    if not iol:
        raise ValueError("IOL not found")
    if not iol.supplier_id or not iol.supplier:
        raise ValueError("This IOL has no supplier mapped. Set supplier in IOL Master.")
    return iol


def generate_order_jpg(
    *,
    order: IOLOrder,
    ot: OTRegister,
    iol: IOLMaster,
    supplier: IOLSupplier,
    ordered_by: User,
) -> bytes:
    from PIL import Image, ImageDraw, ImageFont

    img_w = 760
    line_h = 26
    iol_name = iol.iol_name or "—"
    iol_power_disp = format_iol_power_display(order.iol_power)

    pre_lines = [
        ("Order date / time", order.ordered_at.strftime("%d/%m/%Y %H:%M")),
        ("Ordered by", ordered_by.username if ordered_by else "—"),
        ("", ""),
        ("Patient", ot.patient_name or "—"),
        ("UHID", ot.patient_uhid or "—"),
        (
            "Surgery date",
            ot.date_of_surgery.strftime("%d/%m/%Y") if ot.date_of_surgery else "—",
        ),
        ("Eye", ot.eye or "—"),
        ("", ""),
    ]
    post_lines = [
        ("", ""),
        ("Supplier", supplier.supplier_name),
        ("Supplier phone", supplier.supplier_phone),
        ("Contact person", supplier.contact_person_name),
        ("Contact phone", supplier.contact_person_phone),
    ]

    box_pad = 14
    box_line_h = 30
    box_h = box_pad * 2 + box_line_h * 2
    box_gap = 12

    def _section_height(lines: list[tuple[str, str]]) -> int:
        return sum(line_h if label or value else 8 for label, value in lines)

    header_h = 118
    title_block = 72
    body_h = _section_height(pre_lines) + box_h + box_gap + _section_height(post_lines)
    img_h = header_h + title_block + body_h + 32

    img = Image.new("RGB", (img_w, img_h), (255, 255, 255))
    draw = ImageDraw.Draw(img)

    try:
        if os.name == "nt":
            font = ImageFont.truetype("C:/Windows/Fonts/arial.ttf", 15)
            font_b = ImageFont.truetype("C:/Windows/Fonts/arialbd.ttf", 16)
            font_title = ImageFont.truetype("C:/Windows/Fonts/arialbd.ttf", 22)
            font_hospital = ImageFont.truetype("C:/Windows/Fonts/arialbd.ttf", 19)
            font_iol = ImageFont.truetype("C:/Windows/Fonts/arialbd.ttf", 18)
        else:
            font = ImageFont.truetype(
                "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", 15
            )
            font_b = ImageFont.truetype(
                "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", 16
            )
            font_title = ImageFont.truetype(
                "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", 22
            )
            font_hospital = ImageFont.truetype(
                "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", 19
            )
            font_iol = ImageFont.truetype(
                "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", 18
            )
        except Exception:
        font = ImageFont.load_default()
        font_b = font
        font_title = font
        font_hospital = font

        font_hospital = font
        font_iol = font_b

    def _draw_lines(lines: list[tuple[str, str]], start_y: int) -> int:
        cy = start_y
        for label, value in lines:
            if not label and not value:
                cy += 8
                continue
            draw.text((40, cy), f"{label}:", fill=(80, 80, 80), font=font_b)
            draw.text((220, cy), value, fill=(30, 30, 30), font=font)
            cy += line_h
        return cy

    blue = (0, 51, 102)
    gray = (60, 60, 60)
    y = 16

    if os.path.isfile(HOSPITAL_LOGO_PATH):
        logo = Image.open(HOSPITAL_LOGO_PATH).convert("RGBA")
        logo.thumbnail((88, 88), Image.Resampling.LANCZOS)
        img.paste(logo, (24, y), logo)

    hx = 128
    draw.text((hx, y), "Sreekantapuram Hospital", fill=blue, font=font_hospital)
    draw.text((hx, y + 28), "Kandiyoor, Mavelikara", fill=gray, font=font)
    draw.text((hx, y + 50), "Phone 9061401183, 8281379059", fill=gray, font=font)

    y = header_h
    draw.line((20, y, img_w - 20, y), fill=blue, width=2)
    y += 18

    title = "IOL ORDER"
    bbox = draw.textbbox((0, 0), title, font=font_title)
    draw.text(
        ((img_w - (bbox[2] - bbox[0])) // 2, y), title, fill=blue, font=font_title
    )
    y += 36

    order_no = order.order_no or str(order.id)
    order_line = f"Order No: {order_no}"
    bbox = draw.textbbox((0, 0), order_line, font=font_b)
    draw.text(
        ((img_w - (bbox[2] - bbox[0])) // 2, y), order_line, fill=(30, 30, 30), font=font_b
    )
    y += 36

    y = _draw_lines(pre_lines, y)

    box_x1, box_x2 = 32, img_w - 32
    box_y1 = y
    box_y2 = y + box_h
    draw.rectangle([box_x1, box_y1, box_x2, box_y2], outline=blue, width=2)

    inner_x_label = box_x1 + box_pad
    inner_x_value = box_x1 + box_pad + 100
    inner_y = box_y1 + box_pad
    draw.text((inner_x_label, inner_y), "IOL:", fill=(80, 80, 80), font=font_b)
    draw.text((inner_x_value, inner_y), iol_name, fill=(20, 20, 20), font=font_iol)
    inner_y += box_line_h
    draw.text((inner_x_label, inner_y), "IOL power:", fill=(80, 80, 80), font=font_b)
    draw.text(
        (inner_x_value, inner_y), iol_power_disp, fill=(20, 20, 20), font=font_iol
    )

    y = box_y2 + box_gap
    _draw_lines(post_lines, y)

    buf = io.BytesIO()
    img.save(buf, format="JPEG", quality=92)
    return buf.getvalue()


def _create_iol_order_record(
    db: Session,
    *,
    ot_register_id: int,
    iol_id: int,
    iol_power: str,
    user: User,
    commit: bool = True,
) -> IOLOrder:
    ot = db.query(OTRegister).filter(OTRegister.id == ot_register_id).first()
    if not ot:
        raise ValueError("OT case not found")
    if not is_cataract_case(ot):
        raise ValueError("IOL orders are only for cataract cases")

    existing = latest_iol_order(db, ot_register_id)
    if existing and not can_place_order(existing):
        raise ValueError("An active IOL order already exists for this case")

    power = normalize_iol_power(iol_power)
    iol = _get_iol_with_supplier(db, iol_id)
    supplier = iol.supplier
    if not supplier:
        raise ValueError("Supplier not found for this IOL")

    now = datetime.now()
    order_no = allocate_order_number(db, now)
    order = IOLOrder(
        ot_register_id=ot_register_id,
        iol_id=iol_id,
        iol_power=power,
        status=STATUS_ORDERED,
        ordered_at=now,
        ordered_by_user_id=user.id,
        order_no=order_no,
    )
    db.add(order)
    db.flush()

    jpg_bytes = generate_order_jpg(
        order=order, ot=ot, iol=iol, supplier=supplier, ordered_by=user
    )
    upload_dir = ensure_upload_dir()
    filename = order_jpg_filename(ot.patient_name or "patient", power, upload_dir)
    filepath = os.path.join(upload_dir, filename)
    with open(filepath, "wb") as f:
        f.write(jpg_bytes)
    order.order_jpg_path = filename

    _log_status(
        db,
        order,
        action="order_created",
        from_status=None,
        to_status=STATUS_ORDERED,
        user_id=user.id,
        notes=f"IOL {iol.iol_name} {format_iol_power_display(power)}",
    )
    if commit:
        db.commit()
        db.refresh(order)
    return order


def create_iol_order(
    db: Session,
    *,
    ot_register_id: int,
    iol_id: int,
    iol_power: str,
    user: User,
) -> IOLOrder:
    return _create_iol_order_record(
        db,
        ot_register_id=ot_register_id,
        iol_id=iol_id,
        iol_power=iol_power,
        user=user,
        commit=True,
    )


def receive_iol_verified(
    db: Session,
    *,
    order_id: int,
    iol_id: int,
    iol_power: str,
    verified: bool,
    user: User,
) -> IOLOrder:
    if not verified:
        raise ValueError("You must verify the IOL details before submitting")

    order = db.query(IOLOrder).filter(IOLOrder.id == order_id).first()
    if not order:
        raise ValueError("Order not found")
    if order.status != STATUS_ORDERED:
        raise ValueError("Order is not awaiting receipt")

    power = normalize_iol_power(iol_power)
    iol = db.query(IOLMaster).filter(IOLMaster.id == iol_id).first()
    if not iol:
        raise ValueError("IOL not found")

    if iol_id != order.iol_id or power != order.iol_power:
        raise ValueError(
            "Received IOL does not match order. Use Lens mismatch instead."
        )

    prev = order.status
    order.status = STATUS_LENS_DELIVERED
    order.received_at = datetime.now()
    order.received_by_user_id = user.id

    _log_status(
        db,
        order,
        action="lens_delivered",
        from_status=prev,
        to_status=STATUS_LENS_DELIVERED,
        user_id=user.id,
        notes=f"Verified {iol.iol_name} {format_iol_power_display(power)}",
    )
    db.commit()
    db.refresh(order)
    return order


def report_lens_mismatch(
    db: Session,
    *,
    order_id: int,
    mismatch_kind: str,
    user: User,
) -> IOLOrder:
    if mismatch_kind not in ("lens_type", "iol_power"):
        raise ValueError("Invalid mismatch type")

    order = db.query(IOLOrder).filter(IOLOrder.id == order_id).first()
    if not order:
        raise ValueError("Order not found")
    if order.status != STATUS_ORDERED:
        raise ValueError("Order is not awaiting receipt")

    new_status = (
        STATUS_MISMATCH_TYPE if mismatch_kind == "lens_type" else STATUS_MISMATCH_POWER
    )
    prev = order.status
    order.status = new_status
    order.mismatch_kind = mismatch_kind
    order.received_at = datetime.now()
    order.received_by_user_id = user.id

    label = "Lens type mismatch" if mismatch_kind == "lens_type" else "IOL power mismatch"
    _log_status(
        db,
        order,
        action="mismatch_reported",
        from_status=prev,
        to_status=new_status,
        user_id=user.id,
        notes=label,
    )
    db.commit()
    db.refresh(order)
    return order


def resolve_mismatch(
    db: Session,
    *,
    order_id: int,
    resolution_action: str,
    resolution_notes: str | None,
    user: User,
    reorder_iol_id: int | None = None,
    reorder_iol_power: str | None = None,
) -> IOLOrder:
    if resolution_action not in ("reordered", "postponed", "other"):
        raise ValueError("Invalid resolution action")

    order = (
        db.query(IOLOrder)
        .options(joinedload(IOLOrder.ot_register))
        .filter(IOLOrder.id == order_id)
        .first()
    )
    if not order:
        raise ValueError("Order not found")
    if order.status not in (STATUS_MISMATCH_TYPE, STATUS_MISMATCH_POWER):
        raise ValueError("Order is not awaiting mismatch resolution")

    notes = (resolution_notes or "").strip()
    if resolution_action == "other" and not notes:
        raise ValueError("Please enter a reason for Others")

    status_map = {
        "reordered": STATUS_RESOLVED_REORDERED,
        "postponed": STATUS_RESOLVED_POSTPONED,
        "other": STATUS_RESOLVED_OTHER,
    }
    new_status = status_map[resolution_action]
    prev = order.status
    order.resolution_notes = notes or None

    if resolution_action == "reordered":
        if not reorder_iol_id or not reorder_iol_power:
            raise ValueError("IOL and power required for re-order")
        # Mark resolved so a new order can be placed for this case
        order.status = new_status
        order.resolution_action = resolution_action
        db.flush()
        new_order = _create_iol_order_record(
            db,
            ot_register_id=order.ot_register_id,
            iol_id=reorder_iol_id,
            iol_power=reorder_iol_power,
            user=user,
            commit=False,
        )
        order.superseded_by_order_id = new_order.id
    else:
        order.status = new_status
        order.resolution_action = resolution_action

    _log_status(
        db,
        order,
        action="mismatch_resolved",
        from_status=prev,
        to_status=new_status,
        user_id=user.id,
        notes=notes or resolution_action,
    )
    db.commit()
    db.refresh(order)
    return order


def order_jpg_full_path(order: IOLOrder) -> str | None:
    if not order.order_jpg_path:
        return None
    return os.path.join(IOL_ORDER_UPLOAD_DIR, order.order_jpg_path)


def status_display_label(status: str) -> str:
    labels = {
        STATUS_ORDERED: "Ordered",
        STATUS_LENS_DELIVERED: "Lens Delivered",
        STATUS_MISMATCH_TYPE: "Mismatch (type)",
        STATUS_MISMATCH_POWER: "Mismatch (power)",
        STATUS_RESOLVED_REORDERED: "Re-ordered",
        STATUS_RESOLVED_POSTPONED: "Case postponed",
        STATUS_RESOLVED_OTHER: "Other",
    }
    return labels.get(status, status)
