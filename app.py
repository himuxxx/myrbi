# language: Python, file: app.py, target: My Robi auto-claim hub
# Added custom cookie/header support to bypass F5 WAF on Cloud IPs.

import os
import sys
import json
import time
import hashlib
import logging
import threading
from datetime import datetime, timedelta, timezone
from typing import Optional, Tuple, List, Dict, Any

from curl_cffi import requests
from flask import Flask, request, jsonify, send_file

CONFIG = {
    "DATA_DIR":        os.environ.get("DATA_DIR", "/data"),
    "SECRET_KEY":      os.environ.get("SECRET_KEY", "myrobi-autoclaim-key-2026"),
    "ENABLE_DAEMON":   os.environ.get("ENABLE_DAEMON", "false").lower() in ("1", "true", "yes"),
    "CRON_SECRET":     os.environ.get("CRON_SECRET", ""),
    "PORT":            int(os.environ.get("PORT", "8080")),

    "ROBI_BASE_URL":       os.environ.get("ROBI_BASE_URL",       "https://myrobi-prod.robi.com.bd"),
    
    "ROBI_OTP_REQUEST":    os.environ.get("ROBI_OTP_REQUEST",    "/api/v1/user/otp/request"),
    "ROBI_OTP_VERIFY":     os.environ.get("ROBI_OTP_VERIFY",     "/api/v1/user/otp/verify"),
    "ROBI_TOKEN_REFRESH":  os.environ.get("ROBI_TOKEN_REFRESH",  "/api/v1/auth/token/refresh"),
    "ROBI_PROFILE":        os.environ.get("ROBI_PROFILE",        "/api/v1/user/profile"),
    "ROBI_POINTS_BALANCE": os.environ.get("ROBI_POINTS_BALANCE", "/api/v1/points/balance"),
    "ROBI_TASKS_LIST":     os.environ.get("ROBI_TASKS_LIST",     "/api/v1/points/tasks"),
    "ROBI_CHECKIN":        os.environ.get("ROBI_CHECKIN",        "/api/v1/points/checkin"),
    "ROBI_CLAIM_TASK":     os.environ.get("ROBI_CLAIM_TASK",     "/api/v1/points/task/claim"),
    "ROBI_REWARDS_LIST":   os.environ.get("ROBI_REWARDS_LIST",   "/api/v1/rewards"),
    "ROBI_REDEEM":         os.environ.get("ROBI_REDEEM",         "/api/v1/rewards/redeem"),
    "ROBI_HISTORY":        os.environ.get("ROBI_HISTORY",        "/api/v1/points/history"),

    # Custom Headers
    "ROBI_UA":             os.environ.get("ROBI_UA",             "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/156.0.0.0 Safari/537.36"),
    "ROBI_MSISDN_HEADER":  os.environ.get("ROBI_MSISDN_HEADER",  "X-MSISDN"),
    "ROBI_DEVICE_HEADER":  os.environ.get("ROBI_DEVICE_HEADER",  "X-Device-Id"),
    "ROBI_APP_VERSION":    os.environ.get("ROBI_APP_VERSION",    "4.8.2"),
    
    # Paste your F5 cookies here (from the log)
    "ROBI_COOKIES":        os.environ.get("ROBI_COOKIES", "f5_cspm=1234; f5avraaaaaaaaaaaaaaaa_session_=KOHBEFFIFFHHJDDIDNJOOLLDEFLNBDPLJHIPKDEGNAGAOKKDKFCLJBNECPFBJPEAIFIDLNOOFDMNLFMJCJMAOJLCNELJPHILEKMOPNGLGKKOIOALIABNHICKNEJAANPH; deviceId=1d35803f-3c8f-4f1b-a9d8-0d962a998e5b; BIGipServerpool_revamp_robi=!bx6ZM/pRvE8BvCm+eFm5G6nnyWNgmCO9AR4A9lFiX46S5Iz/zCyn44kIjwqZ6aUddIbRc0BHJAr37pI=; NEXT_LOCALE=en; mui-mode=dark; TS01a3f0f7=01c9bf80bbdcad91226628fabb14f70951c06f9b4838ecd9934af95b94284a2172f6ed829a8030087531ad932eda7c15e8071c942c23083d22e22c5b7cb8e377484ed5f1195390a859268b96b093c526e8d3c67ef8304570053d06cde1974496d5cc3fd169d3b836daa9b51eacf6c2f3faa649a511733fb072e8bb57a873da5564528c6ceb73cfc470d1fa16ee6bc9bd093174626f50f1733d7215535626fb47f5bf7557339cf8afbe6f9c6b7f066e6ffdae215add"),

    # Custom Extra Headers (from the log)
    "ROBI_EXTRA_HEADERS": {
        "sec-ch-ua": '"Not:A-Brand";v="8", "Chromium";v="156", "Google Chrome";v="156"',
        "sec-ch-ua-mobile": "?0",
        "sec-ch-ua-platform": '"Windows"',
        "sec-fetch-dest": "empty",
        "sec-fetch-mode": "cors",
        "sec-fetch-site": "same-origin",
        "Referer": "https://www.robi.com.bd/en",
        "Origin": "https://www.robi.com.bd"
    }
}

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s", handlers=[logging.StreamHandler(sys.stdout)])
logger = logging.getLogger("MyRobiAutoClaim")
logging.getLogger("werkzeug").setLevel(logging.ERROR)

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
TEMPLATES_DIR = os.path.join(BASE_DIR, "templates")

DATA_DIR = CONFIG["DATA_DIR"]
if not (os.path.isdir(DATA_DIR) and os.access(DATA_DIR, os.W_OK)):
    DATA_DIR = BASE_DIR
try:
    os.makedirs(DATA_DIR, exist_ok=True)
except Exception:
    DATA_DIR = BASE_DIR
ACCOUNTS_FILE = os.path.join(DATA_DIR, "accounts.json")

ROBI_ENDPOINTS = {
    "base":           CONFIG["ROBI_BASE_URL"],
    "otp_request":    CONFIG["ROBI_OTP_REQUEST"],
    "otp_verify":     CONFIG["ROBI_OTP_VERIFY"],
    "token_refresh":  CONFIG["ROBI_TOKEN_REFRESH"],
    "profile":        CONFIG["ROBI_PROFILE"],
    "points_balance": CONFIG["ROBI_POINTS_BALANCE"],
    "tasks_list":     CONFIG["ROBI_TASKS_LIST"],
    "checkin":        CONFIG["ROBI_CHECKIN"],
    "claim_task":     CONFIG["ROBI_CLAIM_TASK"],
    "rewards_list":   CONFIG["ROBI_REWARDS_LIST"],
    "redeem":         CONFIG["ROBI_REDEEM"],
    "history":        CONFIG["ROBI_HISTORY"],
}

ROBI_HEADERS = {
    "user_agent":    CONFIG["ROBI_UA"],
    "msisdn_header": CONFIG["ROBI_MSISDN_HEADER"],
    "device_header": CONFIG["ROBI_DEVICE_HEADER"],
    "app_version":   CONFIG["ROBI_APP_VERSION"],
}

def get_bd_now() -> datetime:
    return datetime.now(timezone(timedelta(hours=6)))

def normalize_msisdn(phone: str) -> str:
    cleaned = "".join(filter(str.isdigit, str(phone)))
    if cleaned.startswith("880") and len(cleaned) == 13: return cleaned
    if cleaned.startswith("0") and len(cleaned) == 11: return "88" + cleaned
    if len(cleaned) == 10 and cleaned.startswith("1"): return "880" + cleaned
    return cleaned

def get_device_id(msisdn: str) -> str:
    return hashlib.md5(f"myrobi_device_{msisdn}".encode()).hexdigest()[:16]

def today_str() -> str:
    return get_bd_now().strftime("%Y-%m-%d")

activity_logs: List[Dict[str, Any]] = []

def add_log(msg: str, level: str = "INFO"):
    now_str = get_bd_now().strftime("%d-%b %I:%M:%S %p")
    activity_logs.append({"timestamp": now_str, "level": level, "message": msg})
    if len(activity_logs) > 150: activity_logs.pop(0)
    lvl = level.lower()
    if lvl == "error": logger.error(msg)
    elif lvl in ("warn", "warning"): logger.warning(msg)
    else: logger.info(msg)

def load_accounts() -> Dict[str, Any]:
    if not os.path.exists(ACCOUNTS_FILE): return {}
    try:
        with open(ACCOUNTS_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
            if isinstance(data, list):
                return {normalize_msisdn(a.get("msisdn", "")): a for a in data if a.get("msisdn")}
            return data if isinstance(data, dict) else {}
    except Exception as e:
        add_log(f"Error reading accounts.json: {e}", "ERROR")
        return {}

def save_accounts(accounts: Dict[str, Any]):
    try:
        with open(ACCOUNTS_FILE, "w", encoding="utf-8") as f:
            json.dump(accounts, f, indent=2, ensure_ascii=False)
    except Exception as e:
        add_log(f"Error saving accounts.json: {e}", "ERROR")

def _points_from_body(body: dict) -> int:
    for k in ("points", "coins", "points_earned", "reward", "value"):
        try:
            if body.get(k): return int(body[k])
        except Exception: continue
    return 0

class MyRobiClient:
    def __init__(self, msisdn: str, account_data: Optional[dict] = None):
        self.msisdn = normalize_msisdn(msisdn)
        self.data = account_data or {}
        self.access_token = self.data.get("access_token")
        self.refresh_token = self.data.get("refresh_token")
        self.device_id = self.data.get("device_id") or get_device_id(self.msisdn)
        self.expire_at = self.data.get("expire_at", 0)
        
        self.session = requests.Session(impersonate="chrome110") 
        self._set_headers()

    def _set_headers(self):
        headers = {
            "User-Agent": ROBI_HEADERS["user_agent"],
            ROBI_HEADERS["msisdn_header"]: self.msisdn,
            ROBI_HEADERS["device_header"]: self.device_id,
            "X-App-Version": ROBI_HEADERS["app_version"],
            "Accept": "application/json",
            "Content-Type": "application/json; charset=UTF-8",
            "Accept-Language": "en",
        }
        if self.access_token:
            headers["Authorization"] = f"Bearer {self.access_token}"
            
        # WAF Headers Inject
        headers.update(CONFIG["ROBI_EXTRA_HEADERS"])
        self.session.headers.update(headers)
        
        # WAF Cookies Inject
        cookie_str = CONFIG["ROBI_COOKIES"]
        if cookie_str:
            for cookie in cookie_str.split(";"):
                if "=" in cookie:
                    k, v = cookie.strip().split("=", 1)
                    self.session.cookies.set(k, v)

    def _url(self, key: str) -> str: return ROBI_ENDPOINTS["base"] + ROBI_ENDPOINTS[key]
    def _get(self, key: str, **kw) -> requests.Response: return self.session.get(self._url(key), timeout=20, **kw)
    def _post(self, key: str, **kw) -> requests.Response: return self.session.post(self._url(key), timeout=20, **kw)

    def is_token_expired(self) -> bool:
        if not self.access_token: return True
        if self.expire_at and isinstance(self.expire_at, (int, float)) and self.expire_at > 0:
            return time.time() >= (self.expire_at - 300)
        return False

    def refresh_auth_token(self) -> Tuple[bool, str]:
        if not self.refresh_token: return False, "no refresh_token"
        try:
            resp = self._post("token_refresh", json={"refresh_token": self.refresh_token, "grant_type": "refresh_token"})
            if resp.status_code == 200:
                d = resp.json(); nested = d.get("data") or {}
                self.access_token = d.get("access_token") or d.get("token") or nested.get("access_token")
                new_refresh = d.get("refresh_token") or nested.get("refresh_token")
                if new_refresh: self.refresh_token = new_refresh
                expires_in = d.get("expires_in") or nested.get("expires_in")
                if expires_in: self.expire_at = int(time.time() + expires_in)
                self._set_headers()
                return True, "refreshed"
            return False, f"{resp.status_code} {resp.text[:100]}"
        except Exception as e: return False, str(e)

    def request_otp(self) -> Tuple[bool, str]:
        try:
            payload = {
                "msisdn": self.msisdn,
                "device_id": self.device_id,
                "app_version": ROBI_HEADERS["app_version"]
            }
            resp = self._post("otp_request", json=payload)
            
            print(f"[DEBUG OTP REQUEST] URL: {self._url('otp_request')}")
            print(f"[DEBUG OTP REQUEST] Status: {resp.status_code}, Body: {resp.text[:300]}")
            
            if resp.status_code in (200, 201):
                try:
                    body = resp.json()
                    if body.get("success") is False or body.get("error"):
                        return False, f"Robi rejected: {body.get('message', body)}"
                except Exception:
                    pass
                return True, "OTP sent"
            return False, (resp.text[:300] or f"status {resp.status_code}")
        except Exception as e:
            return False, str(e)

    def verify_otp(self, otp: str) -> Tuple[bool, str]:
        try:
            payload = {
                "msisdn": self.msisdn,
                "otp": str(otp).strip(),
                "device_id": self.device_id,
                "app_version": ROBI_HEADERS["app_version"],
                "device_model": "SM-S901U1",
                "device_name": "Samsung"
            }
            resp = self._post("otp_verify", json=payload)
            print(f"[DEBUG OTP VERIFY] Status: {resp.status_code}, Body: {resp.text[:300]}")
            
            if resp.status_code == 200:
                d = resp.json()
                nested = d.get("data") or {}
                self.access_token = d.get("access_token") or d.get("token") or nested.get("access_token")
                self.refresh_token = d.get("refresh_token") or nested.get("refresh_token")
                expires_in = d.get("expires_in") or nested.get("expires_in")
                if expires_in: self.expire_at = int(time.time() + expires_in)
                self._set_headers()
                if not self.access_token: return False, f"no token: {resp.text[:100]}"
                return True, "Login successful"
            return False, (resp.text[:300] or f"status {resp.status_code}")
        except Exception as e:
            return False, str(e)

    def fetch_points_balance(self) -> dict:
        try:
            resp = self._get("points_balance")
            if resp.status_code == 200: return resp.json()
        except Exception: pass
        return {}

    def fetch_tasks(self) -> list:
        try:
            resp = self._get("tasks_list")
            if resp.status_code == 200:
                d = resp.json()
                if isinstance(d, list): return d
                for k in ("tasks", "data", "items"):
                    if isinstance(d.get(k), list): return d[k]
        except Exception: pass
        return []

    def checkin(self) -> Tuple[bool, dict, str]:
        payload = {"msisdn": self.msisdn, "device_id": self.device_id}
        try:
            resp = self._post("checkin", json=payload)
            body = resp.json() if resp.text else {}
            if resp.status_code in (200, 201):
                ok = body.get("success") is True or str(body.get("status", "")).lower() in ("success", "ok", "true", "1") or (not body.get("error") and body.get("message"))
                return ok, body, body.get("message", "checkin done")
            return False, body, body.get("message", f"status {resp.status_code}")
        except Exception as e: return False, {}, str(e)

    def claim_task(self, task_id: str) -> Tuple[bool, dict, str]:
        payload = {"task_id": task_id, "msisdn": self.msisdn}
        try:
            resp = self._post("claim_task", json=payload)
            body = resp.json() if resp.text else {}
            if resp.status_code in (200, 201):
                ok = body.get("success") is True or str(body.get("status", "")).lower() in ("success", "ok", "true", "1") or (not body.get("error") and body.get("message"))
                return ok, body, body.get("message", "claimed")
            return False, body, body.get("message", f"status {resp.status_code}")
        except Exception as e: return False, {}, str(e)

def process_account_claim(client: MyRobiClient) -> dict:
    result = {"msisdn": client.msisdn, "actions": [], "success": True, "points_gained": 0, "error": None}
    if client.is_token_expired():
        ok, msg = client.refresh_auth_token()
        if not ok: result["success"] = False; result["error"] = f"token failed: {msg}"; return result

    ok, body, msg = client.checkin()
    result["actions"].append({"action": "daily_checkin", "success": ok, "message": msg, "raw": body})
    if ok: result["points_gained"] += _points_from_body(body)

    accounts = load_accounts(); acc = accounts.get(client.msisdn, {}); today = today_str()
    already = {h.get("task_id") for h in acc.get("claim_history", []) if h.get("date") == today and h.get("status") == "SUCCESS" and h.get("task_id")}

    for task in client.fetch_tasks():
        task_id = str(task.get("id") or task.get("task_id") or task.get("slug") or "")
        if not task_id or task_id in already: continue
        if str(task.get("status", "")).lower() in ("locked", "unavailable", "expired", "claimed"): continue
        
        ok, body, msg = client.claim_task(task_id)
        result["actions"].append({"action": f"claim_task:{task_id}", "success": ok, "message": msg, "raw": body})
        if ok: already.add(task_id); result["points_gained"] += _points_from_body(body)

    if client.msisdn in accounts:
        balance = client.fetch_points_balance(); points = 0
        for k in ("coins", "points", "balance", "total", "points_balance"):
            if balance.get(k):
                try: points = int(balance[k]); break
                except Exception: continue
        acc = accounts[client.msisdn]; acc["coins_balance"] = points; acc["last_claim_at"] = get_bd_now().strftime("%Y-%m-%d %I:%M:%S %p BD")
        history = acc.get("claim_history", []); time_str = get_bd_now().strftime("%Y-%m-%d %I:%M:%S %p BD")
        
        for act in result["actions"]:
            if act["success"]: history.append({"date": today, "time": time_str, "action": act["action"], "task_id": act["action"].split(":", 1)[1] if ":" in act["action"] else None, "status": "SUCCESS", "message": act["message"]})
        acc["claim_history"] = history[-500:]; accounts[client.msisdn] = acc; save_accounts(accounts)
    return result

def run_all_claims() -> dict:
    accounts = load_accounts()
    if not accounts: return {}
    results = {}
    for msisdn, acc in accounts.items():
        try: results[msisdn] = process_account_claim(MyRobiClient(msisdn, acc))
        except Exception as e: results[msisdn] = {"success": False, "error": str(e)}
    return results

app = Flask(__name__, template_folder=TEMPLATES_DIR)
app.secret_key = CONFIG["SECRET_KEY"]

@app.route("/")
def index():
    p = os.path.join(TEMPLATES_DIR, "index.html")
    if os.path.exists(p):
        with open(p, "r", encoding="utf-8") as f: return f.read(), 200, {"Content-Type": "text/html; charset=utf-8"}
    return "<h1>templates/index.html missing</h1>", 500

@app.route("/api/status")
def api_status():
    accounts = load_accounts(); out = []; today = today_str()
    for msisdn, acc in accounts.items():
        history = acc.get("claim_history", []); today_success = [h for h in history if h.get("date") == today and h.get("status") == "SUCCESS"]
        out.append({"msisdn": msisdn, "coins_balance": acc.get("coins_balance", 0), "claimed_today": len(today_success), "is_done_today": bool(today_success), "last_claim_at": acc.get("last_claim_at", ""), "history": history[-25:]})
    now_bd = get_bd_now(); next_midnight = (now_bd + timedelta(days=1)).replace(hour=0, minute=0, second=0, microsecond=0)
    return jsonify({"success": True, "current_bd_time": now_bd.strftime("%d-%b-%Y %I:%M:%S %p"), "seconds_to_midnight": max(0, int((next_midnight - now_bd).total_seconds())), "accounts": out, "total_accounts": len(out), "logs": activity_logs[-40:]})

@app.route("/api/otp/request", methods=["POST"])
def api_otp_request():
    data = request.json or {}; phone = (data.get("phone") or "").strip()
    if not phone: return jsonify({"success": False, "message": "phone required"}), 400
    client = MyRobiClient(phone); ok, msg = client.request_otp()
    return jsonify({"success": ok, "message": msg, "msisdn": client.msisdn})

@app.route("/api/otp/verify", methods=["POST"])
def api_otp_verify():
    data = request.json or {}; phone = (data.get("phone") or "").strip(); otp = (data.get("otp") or "").strip()
    if not phone or not otp: return jsonify({"success": False, "message": "phone and otp required"}), 400
    client = MyRobiClient(phone); ok, msg = client.verify_otp(otp)
    if not ok: return jsonify({"success": False, "message": msg}), 400
    
    accounts = load_accounts(); existing = accounts.get(client.msisdn, {})
    accounts[client.msisdn] = {"msisdn": client.msisdn, "access_token": client.access_token, "refresh_token": client.refresh_token, "device_id": client.device_id, "expire_at": client.expire_at, "last_login": get_bd_now().strftime("%Y-%m-%d %I:%M:%S %p BD"), "claim_history": existing.get("claim_history", []), "coins_balance": existing.get("coins_balance", 0)}
    save_accounts(accounts); return jsonify({"success": True, "message": "Login successful, account saved."})

@app.route("/api/claim/all", methods=["POST"])
def api_claim_all(): return jsonify({"success": True, "results": run_all_claims()})

@app.route("/api/claim/<phone>", methods=["POST"])
def api_claim_single(phone):
    accounts = load_accounts(); msisdn = normalize_msisdn(phone)
    if msisdn not in accounts: return jsonify({"success": False, "message": "not found"}), 404
    try: return jsonify({"success": True, "result": process_account_claim(MyRobiClient(msisdn, accounts[msisdn]))})
    except Exception as e: return jsonify({"success": False, "message": str(e)}), 500

@app.route("/api/tokens/refresh", methods=["POST"])
def api_refresh_tokens():
    accounts = load_accounts(); refreshed = 0
    for msisdn, acc in accounts.items():
        client = MyRobiClient(msisdn, acc)
        if client.refresh_auth_token()[0]:
            accounts[msisdn].update({"access_token": client.access_token, "refresh_token": client.refresh_token, "expire_at": client.expire_at})
            refreshed += 1
    save_accounts(accounts); return jsonify({"success": True, "message": f"Refreshed {refreshed}/{len(accounts)}"})

@app.route("/api/account/delete", methods=["POST"])
def api_delete_account():
    data = request.json or {}; msisdn = normalize_msisdn(data.get("phone", ""))
    accounts = load_accounts()
    if msisdn in accounts:
        del accounts[msisdn]; save_accounts(accounts)
        return jsonify({"success": True, "message": f"{msisdn} removed"})
    return jsonify({"success": False, "message": "not found"}), 404

@app.route("/api/accounts/download")
def api_accounts_download():
    if os.path.exists(ACCOUNTS_FILE): return send_file(ACCOUNTS_FILE, mimetype="application/json", as_attachment=True, download_name="accounts.json")
    return jsonify({"success": False, "message": "no accounts.json"}), 404

@app.route("/api/accounts/upload", methods=["POST"])
def api_accounts_upload():
    if 'file' not in request.files: return jsonify({"success": False, "message": "No file part"}), 400
    file = request.files['file']
    if file.filename == '' or not file.filename.endswith('.json'): return jsonify({"success": False, "message": "Invalid file"}), 400
    try:
        data = json.load(file)
        if isinstance(data, dict) or isinstance(data, list):
            save_accounts(data); add_log("Accounts imported via JSON.", "SUCCESS")
            return jsonify({"success": True, "message": "Accounts imported."})
    except Exception as e: return jsonify({"success": False, "message": f"Invalid JSON: {e}"}), 400
    return jsonify({"success": False, "message": "Invalid file"}), 400

@app.route("/api/diagnose")
def api_diagnose():
    results = {}; dummy = MyRobiClient("8801700000000")
    for key in ("otp_request", "otp_verify", "token_refresh", "profile", "points_balance", "tasks_list", "checkin", "claim_task", "rewards_list", "history"):
        try:
            r = dummy.session.get(dummy._url(key), timeout=10, allow_redirects=False)
            body_text = r.text or ""
            
            if "Request Rejected" in body_text or "support ID is" in body_text:
                verdict = "WAF BLOCKED (Cloud IP)"
            elif r.status_code == 404:
                verdict = "WRONG PATH"
            elif r.status_code == 200:
                verdict = "OK (Valid Path)"
            else:
                verdict = f"UNKNOWN ({r.status_code})"

            results[key] = {"url": dummy._url(key), "status": r.status_code, "verdict": verdict, "body": body_text[:150]}
        except Exception as e: 
            results[key] = {"url": dummy._url(key), "error": str(e)}
    return jsonify({"success": True, "base_url": ROBI_ENDPOINTS["base"], "results": results})

@app.route("/api/cron/claim")
def api_cron_claim():
    secret = CONFIG["CRON_SECRET"]
    if secret and (request.headers.get("X-Cron-Secret") or request.args.get("secret")) != secret: return jsonify({"success": False, "message": "Unauthorized"}), 401
    return jsonify({"success": True, "results": run_all_claims()})

if __name__ == "__main__": app.run(host="0.0.0.0", port=CONFIG["PORT"])
