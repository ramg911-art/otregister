# Grandis (SKP Online) patient data integration

This document describes how **OT Register** fetches patient data from the **Grandis HIS** web application hosted at SKP Online. Use it to reimplement the same behavior in another application.

> **Security:** Do not commit real credentials. The production server uses `data/skp_credentials.json` (not in `.env`). Use placeholders in code samples and store secrets via your platform’s secret manager or environment variables.

---

## Summary

| Item | Value |
|------|--------|
| Product | Grandis HIS (SKP Online) |
| Base URL | `https://skponline.in/grandis/public` |
| Integration style | HTTP session (browser-like login + cookie reuse) |
| Session cookie | `grandis_his_session` |
| Credentials | JSON file: `data/skp_credentials.json` |
| Session cache | `data/session.json` |
| Implementation | [`app/skp.py`](../app/skp.py) |
| Python deps | `requests`, `beautifulsoup4` |

There is **no public REST API key**. The app logs in as an admin user, saves session cookies, and calls the same HTML/XHR endpoints the Grandis web UI uses.

---

## Credentials

Create `data/skp_credentials.json` on the server (project root `data/` folder):

```json
{
  "email": "<grandis_admin_email>",
  "password": "<grandis_admin_password>"
}
```

Loaded by `load_config()` in `app/skp.py`. If the file is missing, any SKP call raises `SKP credentials not configured`.

**Recommendation for new apps:** map these to environment variables instead of a JSON file on disk, and ensure the credentials file is listed in `.gitignore` if you keep the file-based approach.

---

## Authentication

### Endpoints

| Step | Method | URL |
|------|--------|-----|
| Login page | GET | `{base}/admin` |
| Login submit | POST | `{base}/admin/authendicate` |
| Session check | GET | `{base}/admin` |

`base` = `https://skponline.in/grandis/public`

### Login payload

Form POST fields:

- `email` — admin username
- `password` — admin password
- `_token` — CSRF token from the login page HTML (`<input name="_token">`)

### Success criteria

Login is treated as successful when the response status is 200 **and** the response body contains the text `logout` (case-insensitive). Otherwise `login_and_get_session` raises `SKP login failed`.

### Session persistence

1. `load_session()` — creates a `requests.Session` and loads cookies from `data/session.json` if present.
2. `save_session(session)` — writes `{"cookies": {...}}` to `data/session.json`.
3. `ensure_logged_in()` — loads cookies, GETs `/admin`; if not logged in, calls `login_and_get_session()` with email/password from credentials file.

```python
# Pseudocode — see app/skp.py for full implementation
def ensure_logged_in():
    creds = load_json("data/skp_credentials.json")
    session = load_cookies_from("data/session.json")
    if "logout" not in session.get(f"{BASE}/admin").text.lower():
        session = login(creds["email"], creds["password"])
        save_cookies(session, "data/session.json")
    return session
```

---

## Grandis endpoints used for patient data

| Purpose | Method | URL | Notes |
|---------|--------|-----|--------|
| EMR Lite home | GET | `{base}/emr_lite` | **Required** before search/detail calls; provides CSRF `_token` and optional `doctor_id` |
| Search by OP / UHID | GET | `{base}/emr_lite/ajaxSearchData` | Query: `op_no_search`, `op_no_search_prog=1` |
| Patient info (XHR) | POST | `{base}/emr_lite/getPatientInfo` | Body: `user_id` (+ optional `doctor_id`, `_token`) |
| Patient admin page | GET | `{base}/admin/patient/{patient_id}` | HTML fallback for name, phone, gender, age |

### Search request headers

```
X-Requested-With: XMLHttpRequest
Referer: {base}/emr_lite
Accept: text/html
```

### getPatientInfo request headers

```
X-Requested-With: XMLHttpRequest
Accept: application/json, text/javascript, */*; q=0.01
Content-Type: application/x-www-form-urlencoded; charset=UTF-8
Origin: https://skponline.in
Referer: {base}/emr_lite/view-patient?user_id={patient_id}  (or variants)
```

---

## Data flows

### 1. Patient search (numeric UHID / OP number)

**OT Register API:** `GET /api/patient/search?q=<digits>`

**Code path:** `search_global_patient` → `search_patient_by_number` → `ajax_search_patients_raw` + `fetch_patient_details`

```
ensure_logged_in()
    → GET /emr_lite
    → GET /emr_lite/ajaxSearchData?op_no_search={query}&op_no_search_prog=1
    → parse <li> elements in HTML response
    → for each match: fetch_patient_details(session, patient_id)
```

**Search HTML parsing** (`ajax_search_patients_raw`):

- Each result is a `<li>` with text like `Patient Name [UHID]`.
- `onclick` may contain `fillGlobalPatientData("12345", ...)` — the first argument is the internal **EMR `patient_id`** (not the UHID string).

**Response shape per result:**

```json
{
  "label": "Patient Name [26/12345]",
  "name": "Patient Name",
  "uhid": "26/12345",
  "patient_id": "12345",
  "age": "65",
  "gender": "Male",
  "phone": "9876543210"
}
```

**Limitation:** Only numeric queries are supported (`query.isdigit()`). Name search is not implemented.

---

### 2. Patient details by internal EMR ID

**Primary:** `POST {base}/emr_lite/getPatientInfo`

**Fallback:** `GET {base}/admin/patient/{patient_id}` and parse form fields with BeautifulSoup.

**Code path:** `fetch_patient_details(session, patient_id)`

```
fetch_patient_info_emr_lite(session, base, patient_id)
    → if missing phone/gender: GET /admin/patient/{patient_id}
    → merge fields
```

**Returned dict:**

```json
{
  "patient_id": "12345",
  "patient_name": "...",
  "uhid": "26/12345",
  "phone": "...",
  "gender": "Male",
  "age": "65"
}
```

**getPatientInfo parsing:**

- Response is JSON; may include HTML fragments (`patient_popover`, etc.) with a table (`table_pat_info`).
- Labels like “Phone”, “Gender”, “UHID”, “Patient Name” are parsed from table rows.
- Flat JSON keys are also read: `phone`, `mobile`, `gender`, `patient_name`, `uhid`, etc.
- POST body candidates tried (with/without CSRF `_token`): `user_id`, `patient_id`, `id`, plus `doctor_id` when found on `/emr_lite`.

**Admin page fallback fields** (input/select `name` attributes):

- Name: `patient_name`, `name`
- Phone: `phone`, `mobile`, `mobile_no`, …
- Gender: `genderdesc`, `gender`, `sex`, …
- Age: `age`, `agegender`, or computed from `dob`

---

### 3. Lookup by UHID only (no EMR id stored)

Used when loading dashboard phone numbers for records that only have `patient_uhid`.

**Code path:** `find_patient_id_for_uhid` → `ajax_search_patients_raw` (digit tokens from UHID) → `fetch_patient_details`

---

### 4. Legacy single fetch

`fetch_patient(patient_id)` — GET admin patient page only; used in older code paths. Prefer `fetch_patient_details`.

---

## How OT Register uses this

| Feature | Entry point |
|---------|-------------|
| Patient search autocomplete | `GET /api/patient/search` in `app/main.py` → `search_global_patient()` |
| Save OT case (phone + EMR id) | `_apply_patient_contact_from_form()` → `fetch_patient_details(ensure_logged_in(), patient_id)` |
| Dashboard phone column | `phones_for_ot_dashboard_records()` — uses DB `patient_phone`, else `patient_emr_id`, else UHID search |

**Database fields** (`OTRegister` model):

- `patient_emr_id` — internal Grandis patient id from search (`patient_id` in API responses)
- `patient_phone` — cached from Grandis on save
- `patient_uhid` — display UHID (e.g. `26/12345`)

---

## Caching

In-memory caches in `app/skp.py` (30-minute TTL):

- `_UHID_PHONE_CACHE` — normalized UHID → phone
- `_EMR_PHONE_CACHE` — EMR patient id → phone

Reduces repeated Grandis calls on dashboard reloads.

---

## Minimal reference implementation

```python
import requests
from bs4 import BeautifulSoup

BASE = "https://skponline.in/grandis/public"


def login(email: str, password: str) -> requests.Session:
    s = requests.Session()
    r = s.get(f"{BASE}/admin", timeout=15)
    soup = BeautifulSoup(r.text, "html.parser")
    token_el = soup.find("input", {"name": "_token"})
    token = token_el["value"] if token_el else None
    res = s.post(
        f"{BASE}/admin/authendicate",
        data={"email": email, "password": password, "_token": token},
        allow_redirects=True,
        timeout=15,
    )
    if res.status_code != 200 or "logout" not in res.text.lower():
        raise RuntimeError("Grandis login failed")
    return s


def search_by_op_no(session: requests.Session, query: str) -> list[dict]:
    """query must be digits only."""
    session.get(f"{BASE}/emr_lite", timeout=10)
    r = session.get(
        f"{BASE}/emr_lite/ajaxSearchData",
        params={"op_no_search": query, "op_no_search_prog": 1},
        headers={
            "X-Requested-With": "XMLHttpRequest",
            "Referer": f"{BASE}/emr_lite",
            "Accept": "text/html",
        },
        timeout=10,
    )
    # Parse <li>: name, uhid, patient_id from onclick — see ajax_search_patients_raw in app/skp.py
    ...


def get_patient_info(session: requests.Session, patient_id: str) -> dict:
    session.get(f"{BASE}/emr_lite", timeout=10)
    # POST {BASE}/emr_lite/getPatientInfo with user_id (+ doctor_id, _token if needed)
    # Fallback: GET {BASE}/admin/patient/{patient_id}
    ...
```

For production, copy the full parsing helpers from `app/skp.py` (`_merge_patient_info_from_response_json`, `_extract_patient_details_from_soup`, etc.).

---

## Operational notes

1. **Unofficial integration** — endpoints and HTML structure may change without notice.
2. **Session expiry** — `ensure_logged_in()` re-authenticates when `/admin` no longer shows a logged-in state.
3. **Timeouts** — EMR calls use ~10–12s timeouts; handle failures gracefully in UI.
4. **Compliance** — patient data is PHI; restrict credentials, logs, and session files to authorized servers only.
5. **Repository hygiene** — add `data/skp_credentials.json` and `data/session.json` to `.gitignore` if they are not already excluded before sharing the repo.

---

## Related files

| File | Role |
|------|------|
| [`app/skp.py`](../app/skp.py) | All Grandis HTTP logic |
| [`app/main.py`](../app/main.py) | `/api/patient/search`, save-time phone fetch |
| [`data/skp_credentials.json`](../data/skp_credentials.json) | Login email/password (server-local, not committed with real values) |
| [`data/session.json`](../data/session.json) | Cached session cookies |

---

## Changelog

| Date | Note |
|------|------|
| 2026-05-25 | Initial handoff document |
