"""
Gemini Cookie Refresher - Playwright 自动续期

通过真实 Chromium 浏览器定时访问 Gemini 页面，
触发 Google 前端 JS 自动续期 __Secure-1PSIDTS，
然后将最新 Cookie 写入共享文件并通知 gemini2api 热更新。
"""
import os
import sys
import json
import time
import requests as http_requests
from playwright.sync_api import sync_playwright

DATA_DIR = "/app/data"
STATE_DIR = os.path.join(DATA_DIR, "browser_states")
COOKIES_OUTPUT = os.path.join(DATA_DIR, "refreshed_cookies.json")
GEMINI2API_URL = os.environ.get("GEMINI2API_URL", "http://gemini2api:5918")
API_KEY = os.environ.get("API_KEY", "")
REFRESH_INTERVAL = int(os.environ.get("REFRESH_INTERVAL_SECONDS", "480"))
SINGLE_RUN = os.environ.get("SINGLE_RUN", "false").lower() == "true"


def load_accounts():
    accounts_file = os.path.join(DATA_DIR, "refresher_accounts.json")
    if os.path.exists(accounts_file):
        with open(accounts_file, "r") as f:
            return json.load(f)

    psid = os.environ.get("GEMINI_PSID", "")
    psidts = os.environ.get("GEMINI_PSIDTS", "")
    if psid:
        return [{"id": "account-0", "psid": psid, "psidts": psidts, "label": "Default"}]
    return []


def ensure_state_dir(account_id):
    path = os.path.join(STATE_DIR, account_id)
    os.makedirs(path, exist_ok=True)
    return path


def inject_cookies_to_state(state_dir, psid, psidts):
    state_file = os.path.join(state_dir, "state.json")
    if os.path.exists(state_file):
        return
    state = {
        "cookies": [
            {"name": "__Secure-1PSID", "value": psid, "domain": ".google.com", "path": "/", "secure": True, "httpOnly": True, "sameSite": "None"},
            {"name": "__Secure-1PSIDTS", "value": psidts, "domain": ".google.com", "path": "/", "secure": True, "httpOnly": True, "sameSite": "None"},
        ],
        "origins": []
    }
    with open(state_file, "w") as f:
        json.dump(state, f)
    print(f"  [init] Injected initial cookies for first run")


def refresh_account(browser, account):
    account_id = account["id"]
    label = account.get("label", account_id)
    state_dir = ensure_state_dir(account_id)
    state_file = os.path.join(state_dir, "state.json")

    if not os.path.exists(state_file):
        inject_cookies_to_state(state_dir, account["psid"], account.get("psidts", ""))

    print(f"  [{label}] Opening browser context...")
    context = browser.new_context(
        storage_state=state_file,
        locale="en-US",
        timezone_id="America/New_York",
    )
    page = context.new_page()

    try:
        page.goto("https://gemini.google.com/app", timeout=90000, wait_until="domcontentloaded")
        time.sleep(15)

        cookies = context.cookies()
        psid = next((c["value"] for c in cookies if c["name"] == "__Secure-1PSID"), None)
        psidts = next((c["value"] for c in cookies if c["name"] == "__Secure-1PSIDTS"), None)

        if psid and psidts:
            context.storage_state(path=state_file)
            print(f"  [{label}] OK - PSIDTS: {psidts[:20]}...")
            return {"id": account_id, "label": label, "psid": psid, "psidts": psidts, "status": "active", "updated_at": time.time()}
        else:
            print(f"  [{label}] FAILED - Cookie not found, may need re-login")
            return {"id": account_id, "label": label, "status": "expired", "updated_at": time.time()}
    except Exception as e:
        print(f"  [{label}] ERROR - {e}")
        return {"id": account_id, "label": label, "status": "error", "error": str(e), "updated_at": time.time()}
    finally:
        context.close()


def notify_gemini2api(account_id, psid, psidts):
    headers = {"Content-Type": "application/json"}
    if API_KEY:
        headers["Authorization"] = f"Bearer {API_KEY}"

    # 优先按账号 ID 精确更新（多账号隔离）
    try:
        resp = http_requests.put(
            f"{GEMINI2API_URL}/admin/accounts/{account_id}/cookies",
            json={"psid": psid, "psidts": psidts},
            headers=headers,
            timeout=10
        )
        if resp.status_code == 200:
            print(f"  [notify] {account_id} cookies updated via PUT")
            return True
        elif resp.status_code == 404:
            # 账号不存在，fallback 到全局 reload
            resp2 = http_requests.post(
                f"{GEMINI2API_URL}/admin/reload-cookies",
                json={"psid": psid, "psidts": psidts},
                headers=headers,
                timeout=10
            )
            if resp2.status_code == 200:
                print(f"  [notify] cookies reloaded via POST (account not in pool)")
                return True
            else:
                print(f"  [notify] reload failed: {resp2.status_code} {resp2.text[:100]}")
                return False
        else:
            print(f"  [notify] PUT failed: {resp.status_code} {resp.text[:100]}")
            return False
    except Exception as e:
        print(f"  [notify] Failed to reach gemini2api: {e}")
        return False


def refresh_all():
    ts = time.strftime("%Y-%m-%d %H:%M:%S")
    print(f"\n{'='*50}")
    print(f"[{ts}] Starting cookie refresh cycle...")
    print(f"{'='*50}")

    accounts = load_accounts()
    if not accounts:
        print("  [ERROR] No accounts configured!")
        print("  Set GEMINI_PSID/GEMINI_PSIDTS env vars or create data/refresher_accounts.json")
        return

    os.makedirs(DATA_DIR, exist_ok=True)
    results = []

    with sync_playwright() as p:
        browser = p.chromium.launch(
            headless=True,
            args=[
                "--no-sandbox",
                "--disable-setuid-sandbox",
                "--disable-gpu",
                "--disable-dev-shm-usage",
                "--single-process",
                "--no-zygote",
                "--disable-extensions",
            ]
        )

        for i, account in enumerate(accounts):
            result = refresh_account(browser, account)
            results.append(result)
            if i < len(accounts) - 1:
                time.sleep(5)

        browser.close()

    with open(COOKIES_OUTPUT, "w") as f:
        json.dump(results, f, indent=2)

    active = [r for r in results if r.get("status") == "active"]
    for acc in active:
        notify_gemini2api(acc["id"], acc["psid"], acc["psidts"])

    print(f"\n  Summary: {len(active)}/{len(results)} accounts active")


if __name__ == "__main__":
    if SINGLE_RUN:
        refresh_all()
        print("\n[Single run mode] Done, exiting.")
        sys.exit(0)

    print(f"Gemini Cookie Refresher started (interval: {REFRESH_INTERVAL}s)")
    while True:
        try:
            refresh_all()
        except Exception as e:
            print(f"[FATAL] {e}")
        print(f"\nSleeping {REFRESH_INTERVAL}s until next refresh...")
        time.sleep(REFRESH_INTERVAL)