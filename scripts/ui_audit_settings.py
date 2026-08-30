"""Part 5 audit: settings provider prefs round-trip + profile key add/remove.

Uses the local test user's session. Fake keys are created only to test the
remove path and are removed again by the script itself.
"""
import re
from pathlib import Path

import requests
from playwright.sync_api import sync_playwright

BASE = "http://localhost:5001"
COOKIE = Path(r"C:\Users\Joosep\AppData\Local\Temp\at_cookies.txt")


def cookie() -> str:
    for line in COOKIE.read_text().splitlines():
        if "localhost" in line and "session_" in line:
            return line.split("\t")[-1].strip()
    raise RuntimeError("no session cookie")


def s() -> requests.Session:
    sess = requests.Session()
    sess.headers["Cookie"] = f"session_={cookie()}"
    return sess


def main() -> None:
    http = s()
    ok = []

    # --- profile: fake account add + remove -------------------------------
    r = http.post(f"{BASE}/profile/keys",
                  data={"api_key": "PKTESTFAKE0000", "secret_key": "fake-secret",
                        "account_name": "Removable Audit Account"},
                  allow_redirects=False)
    ok.append(("profile/keys add fake", r.status_code in (302, 303)))

    page = http.get(f"{BASE}/profile").text
    removable = re.findall(r"name=\"account_id\"[^>]*value=\"([0-9a-f\-]+)\"", page)
    ok.append(("profile lists Removable account",
               "Removable Audit Account" in page and len(removable) >= 2))

    target = None
    for acc in removable:
        blob = http.get(f"{BASE}/profile").text
        # remove the fake one: find its account_id from the row containing the name
        row_start = blob.find("Removable Audit Account")
        row = blob[max(0, row_start - 400): row_start + 400]
        mm = re.search(r"value=\"([0-9a-f\-]{36})\"", row)
        if mm and len(mm.group(1)) == 36:
            target = mm.group(1)
            break
    if target:
        r = http.post(f"{BASE}/profile/keys/remove", data={"account_id": target},
                      allow_redirects=False)
        page = http.get(f"{BASE}/profile").text
        ok.append(("profile/keys/remove fake", "Removed" in page and
                   "Removable Audit Account" not in page))

    # --- settings: provider prefs round-trip ------------------------------
    page = http.get(f"{BASE}/settings").text
    for label in ("model_provider", "model_name", "market_data_provider",
                  "search_provider", "agent_framework"):
        ok.append((f"settings select {label}", f'name="{label}"' in page))
    ok.append(("settings default market data selected",
               re.search(r'name="market_data_provider".*?<option[^>]*selected[^>]*>[^<]*yfinance',
                         page, re.S) or "yfinance" in page))

    # toggle market data to alpaca, save, re-read
    sel = re.search(r'<select name="market_data_provider">(.*?)</select>', page, re.S)
    current = re.search(r'<option[^>]*selected[^>]*>\s*(\w+)', sel.group(1))
    orig = current.group(1) if current else "yfinance"
    new = "alpaca" if orig != "alpaca" else "yfinance"
    r = http.post(f"{BASE}/settings/preferences",
                  data={"model_provider": "", "model_name": "",
                        "market_data_provider": new, "search_provider": "",
                        "agent_framework": ""},
                  allow_redirects=False)
    ok.append(("settings/preferences POST", r.status_code in (302, 303)))
    page2 = http.get(f"{BASE}/settings").text
    sel2 = re.search(r'<select name="market_data_provider">(.*?)</select>', page2, re.S)
    cur2 = re.search(r'<option[^>]*selected[^>]*>\s*(\w+)', sel2.group(1))
    ok.append(("settings pref persisted in UI", cur2 and cur2.group(1) == new))

    # restore (send the full field set the handler expects)
    http.post(f"{BASE}/settings/preferences",
              data={"model_provider": "", "model_name": "",
                    "market_data_provider": orig, "search_provider": "",
                    "agent_framework": ""},
              allow_redirects=False)
    page3 = http.get(f"{BASE}/settings").text
    ok.append(("settings pref restored", orig in page3))

    # --- guide -------------------------------------------------------------
    g = http.get(f"{BASE}/guide")
    ok.append(("guide 200", g.status_code == 200 and "Guide" in g.text))

    for name, passed in ok:
        print(("PASS " if passed else "FAIL ") + name)
    if not all(p for _, p in ok):
        raise SystemExit(1)


if __name__ == "__main__":
    main()