import os
import re
import json
import requests
from urllib.parse import urlparse
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


def _unwrap_patient_info_payload(data) -> dict:
    """EMR getPatientInfo may return the patient object at top level or under data/patient."""
    if not isinstance(data, dict):
        return {}
    if data.get("success") is False and not any(
        k in data for k in ("patient_name", "uhid", "phone", "data", "patient")
    ):
        return {}
    for key in ("patient", "data", "result", "info"):
        inner = data.get(key)
        if isinstance(inner, dict):
            return inner
        if isinstance(inner, list) and inner and isinstance(inner[0], dict):
            return inner[0]
    return data


def _extract_phone_from_dict(d: dict) -> str:
    if not isinstance(d, dict):
        return ""
    for key in (
        "phone",
        "mobile",
        "mobile_no",
        "mobile_number",
        "contact_no",
        "patient_mobile",
    ):
        v = d.get(key)
        if v is not None and str(v).strip():
            return str(v).strip()
    return ""


def _extract_gender_from_dict(d: dict) -> str:
    if not isinstance(d, dict):
        return ""
    for key in ("genderdesc", "gender_name", "gender", "sex"):
        v = d.get(key)
        if v is not None and str(v).strip():
            return _normalize_gender(str(v).strip())
    return ""


def _try_parse_doctor_id_from_emr_html(html: str) -> str:
    if not html:
        return ""
    m = re.search(r"doctor_id=(\d+)", html)
    if m:
        return m.group(1)
    m = re.search(r"['\"]doctor_id['\"]\s*:\s*['\"]?(\d+)", html)
    if m:
        return m.group(1)
    return ""


def fetch_patient_info_emr_lite(
    session: requests.Session, base: str, patient_id: str
) -> dict:
    """
    Same XHR as browser: POST emr_lite/getPatientInfo (application/json response).
    """
    if not patient_id:
        return {}

    url = f"{base}/emr_lite/getPatientInfo"
    parsed = urlparse(base)
    origin = f"{parsed.scheme}://{parsed.netloc}" if parsed.scheme and parsed.netloc else base
    headers_base = {
        "X-Requested-With": "XMLHttpRequest",
        "Accept": "application/json, text/javascript, */*; q=0.01",
        "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8",
        "Origin": origin,
    }

    doctor_id = ""
    csrf_token = ""
    try:
        lite = session.get(f"{base}/emr_lite", timeout=10)
        if lite.status_code == 200 and lite.text:
            doctor_id = _try_parse_doctor_id_from_emr_html(lite.text)
            lsoup = BeautifulSoup(lite.text, "html.parser")
            tok = lsoup.find("input", {"name": "_token"})
            if tok and tok.get("value"):
                csrf_token = str(tok["value"]).strip()
    except Exception:
        pass

    referer_templates = [f"{base}/emr_lite/view-patient?user_id={patient_id}"]
    if doctor_id:
        referer_templates.insert(
            0,
            f"{base}/emr_lite/view-patient?user_id={patient_id}&doctor_id={doctor_id}",
        )
    referer_templates.append(f"{base}/emr_lite")

    payload_candidates = []
    if doctor_id:
        payload_candidates.append(
            {"user_id": str(patient_id), "doctor_id": str(doctor_id)}
        )
    payload_candidates.extend(
        [
            {"user_id": str(patient_id)},
            {"patient_id": str(patient_id)},
            {"id": str(patient_id)},
        ]
    )

    if csrf_token:
        expanded = []
        for p in payload_candidates:
            expanded.append(p)
            q = dict(p)
            q["_token"] = csrf_token
            expanded.append(q)
        payload_candidates = expanded

    for referer in referer_templates:
        hdrs = {**headers_base, "Referer": referer}
        for payload in payload_candidates:
            try:
                r = session.post(url, data=payload, headers=hdrs, timeout=12)
            except Exception:
                continue
            if r.status_code != 200:
                continue
            data = _safe_json(r)
            if not isinstance(data, dict):
                continue
            inner = _unwrap_patient_info_payload(data)
            if not inner:
                continue
            phone = _extract_phone_from_dict(inner)
            gender = _extract_gender_from_dict(inner)
            name = (
                inner.get("patient_name")
                or inner.get("name")
                or ""
            )
            if isinstance(name, str):
                name = name.strip()
            uhid = inner.get("uhid") or inner.get("patient_uhid") or ""
            if isinstance(uhid, str):
                uhid = uhid.strip()
            if phone or gender or name or uhid:
                return {
                    "patient_name": name,
                    "uhid": uhid,
                    "phone": phone,
                    "gender": gender,
                }

    return {}


def fetch_patient_details(session: requests.Session, patient_id: str) -> dict:
    if not patient_id:
        return {}

    base = BASE_URLS["SKP"]
    info = fetch_patient_info_emr_lite(session, base, patient_id)

    soup_details: dict = {}
    if not info or (not info.get("phone") and not info.get("gender")):
        url = f"{BASE_URLS['SKP']}/admin/patient/{patient_id}"
        try:
            r = session.get(url, timeout=10)
        except Exception:
            r = None

        if r and r.status_code == 200 and r.text:
            soup = BeautifulSoup(r.text, "html.parser")
            soup_details = _extract_patient_details_from_soup(soup)

    patient_name = (info.get("patient_name") or soup_details.get("patient_name") or "").strip()
    phone = info.get("phone") or soup_details.get("phone", "")
    gender = info.get("gender") or soup_details.get("gender", "")
    uhid = (info.get("uhid") or "").strip()

    return {
        "patient_id": patient_id,
        "patient_name": patient_name,
        "uhid": uhid,
        "phone": phone,
        "gender": gender,
        "age": soup_details.get("age", ""),
    }


def _safe_json(response: requests.Response):
    try:
        return response.json()
    except Exception:
        return None


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
            if details.get("uhid"):
                result["uhid"] = details["uhid"]
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

    if query.isdigit():
        return search_patient_by_number(query)

    return []