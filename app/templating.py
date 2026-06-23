"""Shared Jinja2 templates with globals for all app routes."""

from datetime import date, datetime

from fastapi import Request
from fastapi.templating import Jinja2Templates

from app.roles import is_administrator

templates = Jinja2Templates(directory="app/templates")


def format_date(value):
    if not value:
        return ""
    if isinstance(value, (date, datetime)):
        return value.strftime("%d/%m/%Y")
    return value


templates.env.filters["datefmt"] = format_date


def template_user_can(request: Request, module_key: str) -> bool:
    allowed = getattr(request.state, "allowed_modules", None)
    if not allowed:
        return False
    return module_key in allowed


def template_user_is_admin(request: Request) -> bool:
    user = getattr(request.state, "current_user", None)
    return is_administrator(user)


templates.env.globals["user_can"] = template_user_can
templates.env.globals["user_is_admin"] = template_user_is_admin


def register_iol_template_globals() -> None:
    from app.iol_order_service import (
        can_place_order,
        format_iol_power_display,
        is_cataract_case,
        status_display_label,
    )

    templates.env.globals["can_place_iol_order"] = can_place_order
    templates.env.globals["is_cataract_case"] = is_cataract_case
    templates.env.globals["iol_status_label"] = status_display_label
    templates.env.globals["iol_power_display"] = format_iol_power_display
