import os
import json
import requests
from bs4 import BeautifulSoup

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

    return {
        "patient_id": patient_id,
        "patient_name": name_input.get("value", "").strip()
    }

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

        results.append({
            "label": text,
            "name": name.strip(),
            "uhid": uhid,
            "patient_id": patient_id
        })

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

    # Numeric search (UHID / OP No)
    if query.isdigit():
        return search_patient_by_number(query)

    # Name search can be added later
    return []