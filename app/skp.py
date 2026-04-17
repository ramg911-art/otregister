import os
import json
import requests
from bs4 import BeautifulSoup
from datetime import date, datetime

# --------------------------------------------------
# Config
# --------------------------------------------------
BASE_URLS = {
    "SKP": "https://skponline.in/grandis/public"
}

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA_DIR = os.path.join(BASE_DIR, "data")
os.makedirs(DATA_DIR, exist_ok=True)

SESSION_PATH = os.path.join(DATA_DIR, "session.json")
CREDS_PATH = os.path.join(DATA_DIR, "skp_credentials.json")


# --------------------------------------------------
# Helpers
# --------------------------------------------------
def load_config():
    if not os.path.exists(CREDS_PATH):
        raise Exception("SKP credentials not configured")
    with open(CREDS_PATH, "r") as f:
        return json.load(f)


def _normalize_gender(value: str) -> str:
    raw = (value or "").strip()
    if not raw:
        return ""
    numeric_map = {
        "1": "Male",
        "2": "Female",
        "3": "Other",
    }
    return numeric_map.get(raw, raw)


# --------------------------------------------------
# Session handling (your logic – simplified)
# --------------------------------------------------
def load_session():
    s = requests.Session()

    if not os.path.exists(SESSION_PATH):
        return s

    try:
        with open(SESSION_PATH, "r") as f:
            data = json.load(f)
            cookies = data.get("cookies", {})
            s.cookies.update(cookies)
    except (json.JSONDecodeError, IOError):
        # Corrupt or empty session file → ignore
        return requests.Session()

    return s


def save_session(session: requests.Session):
    tmp = SESSION_PATH + ".tmp"
    with open(tmp, "w") as f:
        json.dump({"cookies": session.cookies.get_dict()}, f)
    os.replace(tmp, SESSION_PATH)


def login_and_get_session(email, password, clinic="SKP"):
    base = BASE_URLS[clinic]

    login_page = f"{base}/admin"
    login_post = f"{base}/admin/authendicate"

    s = requests.Session()
    r = s.get(login_page)

    soup = BeautifulSoup(r.text, "html.parser")
    token_tag = soup.find("input", {"name": "_token"})
    token = token_tag["value"] if token_tag else None

    payload = {
        "email": email,
        "password": password,
        "_token": token
    }

    res = s.post(login_post, data=payload, allow_redirects=True)

    if res.status_code != 200 or "logout" not in res.text.lower():
        raise Exception("SKP login failed")

    save_session(s)
    return s


def ensure_logged_in(clinic="SKP"):
    creds = load_config()
    s = load_session()

    base = BASE_URLS[clinic]
    test = s.get(f"{base}/admin")

    if "logout" not in test.text.lower():
        s = login_and_get_session(
            creds["email"],
            creds["password"],
            clinic
        )

    return s


# --------------------------------------------------
# Patient fetch
# --------------------------------------------------
def fetch_patient(patient_id: str):
    session = ensure_logged_in("SKP")

    url = f"{BASE_URLS['SKP']}/admin/patient/{patient_id}"
    r = session.get(url)

    if r.status_code != 200:
        return None

    soup = BeautifulSoup(r.text, "html.parser")

    name_input = soup.find("input", {"name": "patient_name"})
    if not name_input:
        return None

    details = _extract_patient_details_from_soup(soup)
    details["patient_id"] = patient_id
    if not details.get("patient_name"):
        details["patient_name"] = name_input.get("value", "").strip()
    return details


def _extract_input_value(soup: BeautifulSoup, field_names: list[str]) -> str:
    for field in field_names:
        tag = (
            soup.find("input", {"name": field})
            or soup.find("select", {"name": field})
            or soup.find("input", {"id": field})
            or soup.find("select", {"id": field})
        )
        if not tag:
            continue
        if tag.name == "select":
            selected = tag.find("option", selected=True) or tag.find("option")
            if selected:
                return (selected.get_text() or "").strip()
        value = tag.get("value", "")
        if value:
            return value.strip()
    return ""


def _compute_age_from_dob(dob_value: str) -> str:
    if not dob_value:
        return ""
    for fmt in ("%Y-%m-%d", "%d-%m-%Y", "%d/%m/%Y", "%m/%d/%Y"):
        try:
            dob = datetime.strptime(dob_value.strip(), fmt).date()
            today = date.today()
            years = today.year - dob.year - ((today.month, today.day) < (dob.month, dob.day))
            return str(max(years, 0))
        except ValueError:
            continue
    return ""


def _extract_age_from_agegender(agegender_value: str) -> str:
    if not agegender_value:
        return ""
    digits = "".join(ch for ch in agegender_value if ch.isdigit())
    return digits


def _extract_patient_details_from_soup(soup: BeautifulSoup) -> dict:
    patient_name = _extract_input_value(soup, ["patient_name", "name"])
    gender = _extract_input_value(
        soup,
        ["genderdesc", "gender_name", "gender.name", "gender", "sex", "patient_gender"],
    )
    phone = _extract_input_value(
        soup,
        ["phone", "mobile", "mobile_no", "mobile_number", "contact_no", "patient_mobile"],
    )
    age = _extract_input_value(soup, ["age", "patient_age"])
    if not age:
        agegender = _extract_input_value(soup, ["agegender", "age_gender"])
        age = _extract_age_from_agegender(agegender)
    if not age:
        dob = _extract_input_value(soup, ["dob", "date_of_birth", "birth_date"])
        age = _compute_age_from_dob(dob)

    return {
        "patient_name": patient_name,
        "gender": _normalize_gender(gender),
        "phone": phone,
        "age": age,
    }


def fetch_patient_details(session: requests.Session, patient_id: str) -> dict:
    if not patient_id:
        return {}

    url = f"{BASE_URLS['SKP']}/admin/patient/{patient_id}"
    try:
        r = session.get(url, timeout=10)
    except Exception:
        return {}

    if r.status_code != 200 or not r.text:
        return {}

    soup = BeautifulSoup(r.text, "html.parser")
    details = _extract_patient_details_from_soup(soup)
    details["patient_id"] = patient_id
    return details


def _safe_json(response: requests.Response):
    try:
        return response.json()
    except Exception:
        return None


def _extract_patient_list(data) -> list:
    if isinstance(data, list):
        return data
    if not isinstance(data, dict):
        return []
    for key in ("patients", "data", "patient_list", "result", "results", "records"):
        value = data.get(key)
        if isinstance(value, list):
            return value
    return []


def _extract_bearer_token(data: dict) -> str:
    if not isinstance(data, dict):
        return ""
    for key in ("token", "access_token", "auth_token"):
        value = data.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    nested = data.get("data")
    if isinstance(nested, dict):
        for key in ("token", "access_token", "auth_token"):
            value = nested.get(key)
            if isinstance(value, str) and value.strip():
                return value.strip()
    return ""


def _emr_api_login(session: requests.Session, base: str, email: str, password: str) -> str:
    url = f"{base}/mobile_emr_apis/login"
    payloads = [
        {"email": email, "password": password},
        {"username": email, "password": password},
        {"user_name": email, "password": password},
    ]

    for payload in payloads:
        try:
            response = session.post(url, data=payload, timeout=10)
        except Exception:
            continue
        if response.status_code != 200:
            continue
        token = _extract_bearer_token(_safe_json(response) or {})
        if token:
            return token
    return ""


def _map_api_patient_item(item: dict) -> dict:
    if not isinstance(item, dict):
        return {}

    patient_name = (
        item.get("patient_name")
        or item.get("name")
        or ""
    )
    uhid = item.get("uhid") or item.get("patient_uhid") or ""
    phone = (
        item.get("phone")
        or item.get("mobile")
        or item.get("mobile_no")
        or item.get("mobile_number")
        or ""
    )
    gender = (
        item.get("genderdesc")
        or item.get("gender_name")
        or item.get("gender")
        or ""
    )
    patient_id = item.get("patient_id") or item.get("id")

    label_name = str(patient_name).strip()
    label_uhid = str(uhid).strip()
    label = f"{label_name} [{label_uhid}]".strip()

    return {
        "label": label,
        "name": label_name,
        "uhid": label_uhid,
        "patient_id": str(patient_id) if patient_id is not None else None,
        "phone": str(phone).strip(),
        "gender": _normalize_gender(str(gender)),
    }


def search_patient_by_mobile_emr_api(query: str) -> list:
    query = (query or "").strip()
    if len(query) < 2:
        return []

    creds = load_config()
    base = BASE_URLS["SKP"]
    session = requests.Session()
    token = _emr_api_login(session, base, creds.get("email", ""), creds.get("password", ""))
    if not token:
        return []

    url = f"{base}/mobile_emr_apis/fetchPatientList"
    headers = {
        "Authorization": f"Bearer {token}",
        "Accept": "application/json",
        "X-Requested-With": "XMLHttpRequest",
    }
    payload_candidates = [
        {"search": query},
        {"query": query},
        {"keyword": query},
        {"op_no_search": query},
        {"uhid": query},
    ]

    for payload in payload_candidates:
        try:
            response = session.post(url, data=payload, headers=headers, timeout=12)
        except Exception:
            continue
        if response.status_code != 200:
            continue

        data = _safe_json(response)
        patients = _extract_patient_list(data)
        mapped = [_map_api_patient_item(item) for item in patients]
        mapped = [row for row in mapped if row and (row.get("name") or row.get("uhid"))]
        if mapped:
            return mapped

    return []

# app/skp.py
def search_global_patient(query: str):
    query = query.strip()
    if len(query) < 2:
        return []

    # Numeric search (UHID / OP no)
    if query.isdigit():
        return search_patient_by_number(query)

    # (Optional) Name search can be added later
    return []
# app/skp.py

from bs4 import BeautifulSoup

def search_patient_by_number(query: str):
    if not query.isdigit():
        return []

    session = ensure_logged_in("SKP")
    base = BASE_URLS["SKP"]

    # Prime EMR Lite session (required)
    session.get(f"{base}/emr_lite")

    # Call the SAME endpoint SKP uses
    r = session.get(
        f"{base}/emr_lite/ajaxSearchData",
        params={
            "op_no_search": query,
            "op_no_search_prog": 1
        },
        headers={
            "X-Requested-With": "XMLHttpRequest",
            "Referer": f"{base}/emr_lite",
            "Accept": "text/html"
        },
        timeout=10
    )

    if r.status_code != 200 or not r.text:
        return []

    soup = BeautifulSoup(r.text, "html.parser")

    results = []
    for li in soup.find_all("li"):
        text = li.get_text(strip=True)

        # Example: SUBHA [SKP/2526/000056]
        if "[" not in text or "]" not in text:
            continue

        name, uhid = text.rsplit("[", 1)
        uhid = uhid.replace("]", "").strip()

        # Extract internal patient id from onclick
        onclick = li.get("onclick", "")
        patient_id = None
        if "fillGlobalPatientData" in onclick:
            try:
                patient_id = onclick.split("(")[1].split(",")[0].replace('"', '')
            except Exception:
                pass

        result = {
            "label": text,
            "name": name.strip(),
            "uhid": uhid,
            "patient_id": patient_id
        }
        # Enrich with details available in patient profile page.
        details = fetch_patient_details(session, patient_id) if patient_id else {}
        if details:
            if details.get("patient_name"):
                result["name"] = details["patient_name"]
            result["age"] = details.get("age", "")
            result["gender"] = details.get("gender", "")
            result["phone"] = details.get("phone", "")

        results.append(result)

    return results
def search_global_patient(query: str):
    """
    Unified patient search.
    Currently supports numeric UHID / OP No.
    Can be extended for name search later.
    """
    query = query.strip()
    if len(query) < 2:
        return []

    # Prefer EMR API search (returns phone/gender when available).
    api_results = search_patient_by_mobile_emr_api(query)
    if api_results:
        return api_results

    # Fallback to existing numeric search (UHID / OP No).
    if query.isdigit():
        return search_patient_by_number(query)

    # Name search can be added later
    return []