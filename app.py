import os
import sys
import json
import time
import hashlib
import logging
import threading
from datetime import datetime, timedelta, timezone
from typing import Optional, Tuple, List, Dict, Any

# requests এর জায়গায় curl_cffi
from curl_cffi import requests
from flask import Flask, request, jsonify, send_file

CONFIG = {
    # ... (আগের সব কনফিগ থাকবে) ...
    "PORT":            int(os.environ.get("PORT", "8080")),
    
    # নতুন হোস্ট URL
    "ROBI_BASE_URL":       os.environ.get("ROBI_BASE_URL",       "https://myrobi-prod.robi.com.bd"),
    
    # পাথগুলো আপাতত এভাবে রাখুন, রিকোয়াবল (Reqable) থেকে আসলটা পেলে বদলে দেবেন
    "ROBI_OTP_REQUEST":    os.environ.get("ROBI_OTP_REQUEST",    "/api/v1/user/otp/request"),
    "ROBI_OTP_VERIFY":     os.environ.get("ROBI_OTP_VERIFY",     "/api/v1/user/otp/verify"),
    "ROBI_CHECKIN":        os.environ.get("ROBI_CHECKIN",        "/api/v1/points/checkin"),
    # ...
}

# ... (বাকি কনফিগ) ...

class MyRobiClient:
    def __init__(self, msisdn: str, account_data: Optional[dict] = None):
        self.msisdn = normalize_msisdn(msisdn)
        self.data = account_data or {}
        self.access_token = self.data.get("access_token")
        self.refresh_token = self.data.get("refresh_token")
        self.device_id = self.data.get("device_id") or get_device_id(self.msisdn)
        self.expire_at = self.data.get("expire_at", 0)
        
        # curl_cffi সেশন, ব্রাউজারের মতো TLS ফিঙ্গারপ্রিন্ট দিতে impersonate="chrome110" ব্যবহার করা হলো
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
        self.session.headers.update(headers)

    def _url(self, key: str) -> str: return ROBI_ENDPOINTS["base"] + ROBI_ENDPOINTS[key]
    def _get(self, key: str, **kw) -> requests.Response: return self.session.get(self._url(key), timeout=20, **kw)
    def _post(self, key: str, **kw) -> requests.Response: return self.session.post(self._url(key), timeout=20, **kw)

    # ... (বাকি ক্লায়েন্ট মেথডগুলো আগের মতোই থাকবে) ...
