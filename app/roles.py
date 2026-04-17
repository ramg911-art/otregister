"""
Role identifiers stored on User.role (see models.User).

Legacy values "admin" and "staff" are still recognized at runtime until migrated.
"""

ROLE_ADMINISTRATOR = "administrator"
ROLE_OPTOMETRIST = "optometrist"
ROLE_FEEDBACK_USER = "feedback_user"

ROLES = (
    ROLE_ADMINISTRATOR,
    ROLE_OPTOMETRIST,
    ROLE_FEEDBACK_USER,
)

_LEGACY_ADMIN = frozenset({ROLE_ADMINISTRATOR, "admin"})
_LEGACY_CLINICAL = frozenset({ROLE_OPTOMETRIST, "staff"})


def normalized_role(role: str | None) -> str:
    r = (role or "").strip()
    if r in _LEGACY_ADMIN:
        return ROLE_ADMINISTRATOR
    if r in _LEGACY_CLINICAL:
        return ROLE_OPTOMETRIST
    if r == ROLE_FEEDBACK_USER:
        return ROLE_FEEDBACK_USER
    return ROLE_OPTOMETRIST


def coerce_stored_role(role: str | None) -> str:
    """Map form/API input to a value persisted on User.role."""
    r = (role or "").strip()
    if r in _LEGACY_ADMIN or r == ROLE_ADMINISTRATOR:
        return ROLE_ADMINISTRATOR
    if r in _LEGACY_CLINICAL or r == ROLE_OPTOMETRIST:
        return ROLE_OPTOMETRIST
    if r == ROLE_FEEDBACK_USER:
        return ROLE_FEEDBACK_USER
    return ROLE_OPTOMETRIST


def role_value(user) -> str:
    return (getattr(user, "role", None) or "").strip()


def is_administrator(user) -> bool:
    return bool(user) and role_value(user) in _LEGACY_ADMIN


def is_feedback_user(user) -> bool:
    return bool(user) and role_value(user) == ROLE_FEEDBACK_USER


def is_clinical_staff(user) -> bool:
    """Optometrist, administrator, or legacy staff — not feedback-only."""
    if not user:
        return False
    r = role_value(user)
    if r == ROLE_FEEDBACK_USER:
        return False
    return r in _LEGACY_ADMIN or r in _LEGACY_CLINICAL
