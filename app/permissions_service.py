from __future__ import annotations

from sqlalchemy.orm import Session

from app.models import RolePermission, User
from app.permission_modules import (
    ALL_MATRIX_MODULE_KEYS,
    MATRIX_ROLE_KEYS,
    MODULE_ACCOUNT_PASSWORD,
    default_allowed_modules_for_role,
    landing_path_priority,
)
from app.roles import is_administrator, normalized_role


def _rows_for_role(db: Session, role: str) -> list[RolePermission]:
    return (
        db.query(RolePermission)
        .filter(RolePermission.role == role)
        .all()
    )


def resolve_allowed_modules(db: Session, user: User | None) -> frozenset[str]:
    """Modules this user may access (used by middleware, templates, and checks)."""
    if not user:
        return frozenset()
    if is_administrator(user):
        return ALL_MATRIX_MODULE_KEYS | {MODULE_ACCOUNT_PASSWORD}
    canon = normalized_role(user.role)
    rows = _rows_for_role(db, canon)
    if not rows:
        return frozenset(default_allowed_modules_for_role(canon))
    allowed = {r.module_key for r in rows if r.allowed}
    allowed.add(MODULE_ACCOUNT_PASSWORD)
    return frozenset(allowed)


def module_allowed(db: Session, user: User | None, module_key: str) -> bool:
    if not user:
        return False
    return module_key in resolve_allowed_modules(db, user)


def default_landing_path(db: Session, user: User) -> str:
    if is_administrator(user):
        return "/dashboard"
    allowed = resolve_allowed_modules(db, user)
    for mod, path in landing_path_priority():
        if mod in allowed:
            return path
    return "/change-password"


def seed_role_permissions_if_empty(db: Session) -> None:
    """Insert default matrix rows once (all roles × all matrix modules)."""
    n = db.query(RolePermission).count()
    if n > 0:
        return
    from app.roles import ROLE_ADMINISTRATOR

    roles = (ROLE_ADMINISTRATOR, *MATRIX_ROLE_KEYS)
    for role in roles:
        defaults = default_allowed_modules_for_role(role)
        for key in ALL_MATRIX_MODULE_KEYS:
            db.add(
                RolePermission(
                    role=role,
                    module_key=key,
                    allowed=(key in defaults),
                )
            )
    db.commit()


def matrix_checkbox_state(db: Session) -> dict[str, dict[str, bool]]:
    """For the admin UI: role -> module_key -> checked (optometrist & feedback_user only)."""
    state: dict[str, dict[str, bool]] = {}
    for role in MATRIX_ROLE_KEYS:
        rows = {
            r.module_key: r.allowed
            for r in db.query(RolePermission).filter(RolePermission.role == role).all()
        }
        if not rows:
            defaults = default_allowed_modules_for_role(role)
            state[role] = {k: (k in defaults) for k in ALL_MATRIX_MODULE_KEYS}
        else:
            state[role] = {k: bool(rows.get(k, False)) for k in ALL_MATRIX_MODULE_KEYS}
    return state


def replace_matrix_for_roles(db: Session, role_to_allowed: dict[str, set[str]]) -> None:
    """Replace stored permissions for optometrist / feedback_user from the admin form."""
    for role, keys in role_to_allowed.items():
        if role not in MATRIX_ROLE_KEYS:
            continue
        db.query(RolePermission).filter(RolePermission.role == role).delete(
            synchronize_session=False
        )
        for key in ALL_MATRIX_MODULE_KEYS:
            db.add(
                RolePermission(
                    role=role,
                    module_key=key,
                    allowed=(key in keys),
                )
            )
    db.commit()
