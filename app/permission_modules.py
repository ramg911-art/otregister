"""
Granular permission modules (pages, reports, admin areas).

Keys are stored in role_permissions and referenced by routes and templates.
"""

from dataclasses import dataclass

from app.roles import ROLE_ADMINISTRATOR, ROLE_FEEDBACK_USER, ROLE_OPTOMETRIST

SECTION_PAGES = "Pages"
SECTION_REPORTS = "Reports"
SECTION_ADMIN = "Administration"
SECTION_OTHER = "Other"

# Always granted to any authenticated user (not shown in the admin matrix).
MODULE_ACCOUNT_PASSWORD = "account_password"


@dataclass(frozen=True)
class ModuleDef:
    key: str
    label: str
    section: str


MODULE_DEFINITIONS: tuple[ModuleDef, ...] = (
    ModuleDef("dashboard", "Dashboard", SECTION_PAGES),
    ModuleDef("post_case", "Post case (new / edit OT)", SECTION_PAGES),
    ModuleDef("patient_feedback", "Patient feedback", SECTION_PAGES),
    ModuleDef("devtools", "Developer tools (patient search test)", SECTION_OTHER),
    ModuleDef("reports_surgery", "Report: Surgery list", SECTION_REPORTS),
    ModuleDef("reports_vue", "Report: Vue referral", SECTION_REPORTS),
    ModuleDef("reports_category_iol", "Report: Category / IOL", SECTION_REPORTS),
    ModuleDef("reports_intravitreal", "Report: Intravitreal injections", SECTION_REPORTS),
    ModuleDef("iol_master", "IOL master", SECTION_ADMIN),
    ModuleDef("admin_users", "User management", SECTION_ADMIN),
    ModuleDef("admin_drugs", "Intravitreal drug master", SECTION_ADMIN),
    ModuleDef("admin_dashboard", "Admin dashboard (statistics)", SECTION_ADMIN),
    ModuleDef("admin_permissions", "Role permissions matrix", SECTION_ADMIN),
)

MATRIX_ROLE_KEYS = (ROLE_OPTOMETRIST, ROLE_FEEDBACK_USER)

ALL_MATRIX_MODULE_KEYS: frozenset[str] = frozenset(m.key for m in MODULE_DEFINITIONS)


def default_allowed_modules_for_role(role: str) -> frozenset[str]:
    """Bootstrap defaults when the role_permissions table is empty."""
    r = (role or "").strip()
    if r in (ROLE_ADMINISTRATOR, "admin"):
        return ALL_MATRIX_MODULE_KEYS | {MODULE_ACCOUNT_PASSWORD}
    if r in (ROLE_OPTOMETRIST, "staff"):
        return frozenset(
            {
                "dashboard",
                "post_case",
                "patient_feedback",
                "reports_surgery",
                "reports_vue",
                "reports_category_iol",
                "reports_intravitreal",
                MODULE_ACCOUNT_PASSWORD,
            }
        )
    if r == ROLE_FEEDBACK_USER:
        return frozenset({"patient_feedback", MODULE_ACCOUNT_PASSWORD})
    return frozenset({MODULE_ACCOUNT_PASSWORD})


def landing_path_priority() -> list[tuple[str, str]]:
    """First path whose module is allowed wins (module_key, path)."""
    return [
        ("dashboard", "/dashboard"),
        ("patient_feedback", "/patient-feedback"),
        ("post_case", "/ot/new"),
        ("admin_dashboard", "/admin/dashboard"),
        ("admin_users", "/admin/users"),
        ("admin_drugs", "/admin/drugs"),
        ("admin_permissions", "/admin/permissions"),
        ("iol_master", "/iol"),
        ("account_password", "/change-password"),
    ]
