#!/usr/bin/env python3
"""Mint a scoped Coolify API token by driving the Coolify UI with Playwright.

Coolify exposes no API for creating API tokens (every /api/v1 token endpoint 404s), so
the only way to mint one is the web UI. This logs in, creates a token with exactly the
permissions asked for, and hands it straight to `gh secret set` or `.env` — the value is
never printed, so it does not end up in terminal scrollback or CI logs.

Credentials come from the environment (never hardcode them):
  COOLIFY_URL       instance to talk to (override with --url)
  COOLIFY_EMAIL     UI login email
  COOLIFY_PASSWORD  UI login password

Usage:
  # create a deploy-scoped token, print only a masked confirmation
  python scripts/coolify_mint_token.py --description "github-actions deploy"

  # create one and push it straight into a GitHub repo secret
  python scripts/coolify_mint_token.py --description "github-actions deploy" \
      --permissions read,deploy --github-secret predictivelabsai/alpatrade

  # target a different instance and store it locally
  python scripts/coolify_mint_token.py --url https://coolify.example.tld --write-env

The instance must be the one that actually hosts the app you want to deploy — a token
from another Coolify install authenticates as 401 everywhere else.
"""
from __future__ import annotations

import argparse
import os
import re
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
try:
    from dotenv import load_dotenv
    load_dotenv()
except Exception:  # noqa: BLE001
    pass

# Laravel Sanctum tokens look like "<id>|<40+ url-safe chars>".
_TOKEN_RE = re.compile(r"\b\d+\|[A-Za-z0-9]{40,}\b")

VALID_PERMISSIONS = ("root", "write", "deploy", "read", "read:sensitive")

# Collect [livewireComponentId, method, tokenId] for every token row whose text
# contains `match`. The id lives in the row's Alpine x-data as submitAction:'revoke(N)'.
_REVOKE_TARGETS_JS = r"""(match) => {
  const rows = [...document.querySelectorAll('tr')].filter(
    tr => tr.innerText.includes('Revoke token') && tr.innerText.includes(match));
  const out = [];
  for (const tr of rows) {
    const holder = tr.querySelector('[x-data]');
    const xd = holder ? holder.getAttribute('x-data') : '';
    const m = xd && xd.match(/submitAction:\s*'(\w+)\((\d+)\)'/);
    if (!m) continue;
    let el = tr;
    while (el && !el.hasAttribute('wire:id')) el = el.parentElement;
    if (!el) continue;
    out.push([el.getAttribute('wire:id'), m[1], parseInt(m[2])]);
  }
  return out;
}"""


def _mask(token: str) -> str:
    head = token.split("|", 1)[0]
    return f"{head}|{token.split('|', 1)[1][:4]}…  ({len(token)} chars)"


def mint(url: str, email: str, password: str, description: str,
         permissions: list[str], expires: str, headless: bool = True) -> str:
    from playwright.sync_api import sync_playwright

    base = url.rstrip("/")
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=headless)
        page = browser.new_page()
        try:
            page.goto(f"{base}/login", wait_until="domcontentloaded", timeout=45000)
            page.fill("input[type=email]", email)
            page.fill("input[type=password]", password)
            page.click("button[type=submit]")
            page.wait_for_load_state("networkidle", timeout=45000)
            if "/login" in page.url:
                body = page.inner_text("body")
                hint = next((l.strip() for l in body.splitlines()
                             if "match our records" in l or "credential" in l.lower()), "")
                raise SystemExit(f"Login failed on {base}. {hint}".strip())

            page.goto(f"{base}/security/api-tokens", wait_until="networkidle", timeout=45000)
            # The page renders many hidden modals; scope to the token form itself.
            form = page.locator("form").filter(has=page.locator("input[name=description]")).first
            form.locator("input[name=description]").fill(description)
            if form.locator("select[name=expiresInDays]").count():
                form.locator("select[name=expiresInDays]").select_option(expires)

            _apply_permissions(form, permissions)
            before = set(_TOKEN_RE.findall(page.inner_text("body")))
            form.locator("button[type=submit]").click()
            page.wait_for_timeout(2500)
            page.wait_for_load_state("networkidle", timeout=30000)

            found = [t for t in _TOKEN_RE.findall(page.inner_text("body")) if t not in before]
            if not found:
                raise SystemExit("Token was not created, or the value was not shown on the "
                                 "page. Check the instance manually at "
                                 f"{base}/security/api-tokens")
            return found[0]
        finally:
            browser.close()


def _login(page, base: str, email: str, password: str) -> None:
    page.goto(f"{base}/login", wait_until="domcontentloaded", timeout=45000)
    page.fill("input[type=email]", email)
    page.fill("input[type=password]", password)
    page.click("button[type=submit]")
    page.wait_for_load_state("networkidle", timeout=45000)
    if "/login" in page.url:
        body = page.inner_text("body")
        hint = next((l.strip() for l in body.splitlines()
                     if "match our records" in l or "credential" in l.lower()), "")
        raise SystemExit(f"Login failed on {base}. {hint}".strip())


def list_tokens(url: str, email: str, password: str, headless: bool = True) -> list[str]:
    """Return one summary line per existing token."""
    from playwright.sync_api import sync_playwright
    base = url.rstrip("/")
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=headless)
        page = browser.new_page()
        try:
            _login(page, base, email, password)
            page.goto(f"{base}/security/api-tokens", wait_until="networkidle", timeout=45000)
            rows = page.locator("tr").filter(has_text="Revoke token")
            out = []
            for i in range(rows.count()):
                text = re.sub(r"\s*\n\s*", " | ", rows.nth(i).inner_text().strip())
                out.append(re.sub(r"\s+", " ", text))
            return out
        finally:
            browser.close()


def revoke_tokens(url: str, email: str, password: str, match: str,
                  headless: bool = True) -> int:
    """Revoke every token whose description contains `match`. Returns the count."""
    from playwright.sync_api import sync_playwright
    base = url.rstrip("/")
    revoked = 0
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=headless)
        page = browser.new_page()
        try:
            _login(page, base, email, password)
            page.goto(f"{base}/security/api-tokens", wait_until="networkidle", timeout=45000)
            # Clicking "Revoke token" only opens an Alpine modal that demands the
            # token's description be retyped. Rather than drive that, read each row's
            # x-data for its `submitAction: 'revoke(<id>)'` and call the Livewire
            # method directly — no modal, and it can't mis-target a re-rendered row.
            targets = page.evaluate(_REVOKE_TARGETS_JS, match)
            for component_id, method, token_id in targets:
                page.evaluate("([c, m, i]) => window.Livewire.find(c).call(m, i)",
                              [component_id, method, token_id])
                page.wait_for_timeout(1500)
                revoked += 1
            return revoked
        finally:
            browser.close()


def _apply_permissions(form, wanted: list[str]) -> None:
    """Tick exactly the requested permission checkboxes.

    Checkboxes carry no name/id, so match each one by the text of its enclosing label.
    """
    boxes = form.locator("input[type=checkbox]")
    seen: dict[str, object] = {}
    for i in range(boxes.count()):
        box = boxes.nth(i)
        try:
            label = box.locator("xpath=ancestor::label[1]").inner_text().strip().lower()
        except Exception:  # noqa: BLE001
            continue
        label = re.sub(r"\s+", " ", label)
        for perm in VALID_PERMISSIONS:
            if label == perm or label.startswith(perm + " "):
                seen.setdefault(perm, box)
                break
    missing = [p for p in wanted if p not in seen]
    if missing:
        raise SystemExit(f"Permissions not found in the UI: {', '.join(missing)} "
                         f"(available: {', '.join(sorted(seen)) or 'none detected'})")
    for perm, box in seen.items():
        should = perm in wanted
        if box.is_checked() != should:
            box.click()


def main() -> int:
    ap = argparse.ArgumentParser(description="Mint a scoped Coolify API token via the UI")
    ap.add_argument("--url", default=os.getenv("COOLIFY_URL"),
                    help="Coolify instance (default: COOLIFY_URL)")
    ap.add_argument("--description", help="token description shown in the UI (required to create)")
    ap.add_argument("--list", action="store_true", help="list existing tokens and exit")
    ap.add_argument("--revoke", metavar="SUBSTRING",
                    help="revoke every token whose description contains SUBSTRING")
    ap.add_argument("--permissions", default="read,deploy",
                    help=f"comma-separated, from: {', '.join(VALID_PERMISSIONS)}")
    ap.add_argument("--expires", default="365",
                    help="7 / 30 / 60 / 90 / 365, or 'never'")
    ap.add_argument("--github-secret", default=None, metavar="OWNER/REPO",
                    help="pipe the token into `gh secret set COOLIFY_API_TOKEN` for this repo")
    ap.add_argument("--secret-name", default="COOLIFY_API_TOKEN")
    ap.add_argument("--write-env", action="store_true",
                    help="append the token to .env as COOLIFY_API_TOKEN_<suffix>")
    ap.add_argument("--headed", action="store_true", help="show the browser (debugging)")
    args = ap.parse_args()

    if not args.url:
        raise SystemExit("No Coolify URL — pass --url or set COOLIFY_URL.")
    email = os.getenv("COOLIFY_EMAIL")
    password = os.getenv("COOLIFY_PASSWORD")
    if not (email and password):
        raise SystemExit("Set COOLIFY_EMAIL and COOLIFY_PASSWORD (e.g. in .env).")

    if args.list:
        for line in list_tokens(args.url, email, password, headless=not args.headed):
            print(" ", line)
        return 0

    if args.revoke:
        n = revoke_tokens(args.url, email, password, args.revoke, headless=not args.headed)
        print(f"Revoked {n} token(s) matching {args.revoke!r} on {args.url}")
        return 0

    if not args.description:
        raise SystemExit("--description is required when creating a token.")

    perms = [p.strip() for p in args.permissions.split(",") if p.strip()]
    bad = [p for p in perms if p not in VALID_PERMISSIONS]
    if bad:
        raise SystemExit(f"Unknown permission(s): {', '.join(bad)}. "
                         f"Valid: {', '.join(VALID_PERMISSIONS)}")
    expires = "" if args.expires.lower() == "never" else args.expires

    token = mint(args.url, email, password, args.description, perms, expires,
                 headless=not args.headed)
    print(f"Created token on {args.url}: {args.description}")
    print(f"  permissions: {', '.join(perms)} · expires: {args.expires}")
    print(f"  value: {_mask(token)}  (not printed in full by design)")

    if args.github_secret:
        r = subprocess.run(["gh", "secret", "set", args.secret_name,
                            "--repo", args.github_secret],
                           input=token.encode(), capture_output=True)
        if r.returncode:
            print(f"  gh secret set FAILED: {r.stderr.decode()[:200]}", file=sys.stderr)
            return 1
        print(f"  → set {args.secret_name} on {args.github_secret}")

    if args.write_env:
        with open(Path(__file__).resolve().parents[1] / ".env", "a") as f:
            f.write(f"\n# minted by coolify_mint_token.py: {args.description}\n"
                    f"{args.secret_name}={token}\n")
        print(f"  → appended {args.secret_name} to .env")

    if not args.github_secret and not args.write_env:
        print("  (nothing stored — pass --github-secret or --write-env to persist it)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
