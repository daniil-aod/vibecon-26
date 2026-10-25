# Clerk dev helper: create a +clerk_test user and mint a sign-in ticket / session JWT (bypasses Turnstile captcha on sign-up).
import os
import sys
import time
import requests
from dotenv import load_dotenv

load_dotenv("/app/backend/.env")
SK = os.environ["CLERK_SECRET_KEY"]
H = {"Authorization": f"Bearer {SK}", "Content-Type": "application/json"}
API = "https://api.clerk.com/v1"


def get_or_create_user(email: str) -> str:
    r = requests.get(f"{API}/users", headers=H, params={"email_address": email}, timeout=15)
    r.raise_for_status()
    if r.json():
        return r.json()[0]["id"]
    r = requests.post(f"{API}/users", headers=H, json={"email_address": [email], "skip_password_requirement": True,
                                                       "skip_password_checks": True}, timeout=15)
    if r.status_code >= 300:
        print(r.text)
    r.raise_for_status()
    return r.json()["id"]


def sign_in_ticket(user_id: str) -> str:
    r = requests.post(f"{API}/sign_in_tokens", headers=H, json={"user_id": user_id, "expires_in_seconds": 3600}, timeout=15)
    r.raise_for_status()
    return r.json()["token"]


def session_jwt(user_id: str) -> str:
    r = requests.post(f"{API}/sessions", headers=H, json={"user_id": user_id}, timeout=15)
    if r.status_code >= 300:
        print(r.text)
    r.raise_for_status()
    sid = r.json()["id"]
    r = requests.post(f"{API}/sessions/{sid}/tokens", headers=H, json={"expires_in_seconds": 3600}, timeout=15)
    if r.status_code >= 300:
        print(r.text)
    r.raise_for_status()
    return r.json()["jwt"]


if __name__ == "__main__":
    email = sys.argv[1] if len(sys.argv) > 1 else f"dockqa{int(time.time())}+clerk_test@example.com"
    uid = get_or_create_user(email)
    print("EMAIL", email)
    print("USER", uid)
    print("TICKET", sign_in_ticket(uid))
