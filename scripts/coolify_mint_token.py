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

# Every token, read from its Alpine x-data rather than from page layout: one instance
# renders tokens as table rows and another as cards, so a `tr` selector silently found
# nothing on the latter and reported "no tokens" for an account that had several.
# The x-data carries both the description (confirmationText) and submitAction:'revoke(N)'.
_TOKENS_JS = r"""() => {
  const out = [];
  for (const el of document.querySelectorAll('[x-data]')) {
    const xd = el.getAttribute('x-data') || '';
    const m = xd.match(/submitAction:\s*'(\w+)\((\d+)\)'/);
    if (!m) continue;
    let desc = '';
    const d = xd.match(/textarea\.innerHTML\s*=\s*'((?:[^'\\]|\\.)*)'/);
    if (d) {
      const ta = document.createElement('textarea');
      ta.innerHTML = d[1].replace(/\\u0022/g, '"').replace(/\\'/g, "'");
      desc = ta.value;
    }
    let owner = el;
    while (owner && !owner.hasAttribute('wire:id')) owner = owner.parentElement;
    let box = el;
    for (let i = 0; i < 6 && box.parentElement; i++) {
      box = box.parentElement;
      if ((box.innerText || '').includes('Permissions')) break;
    }
    out.push({
      id: parseInt(m[2]), method: m[1], description: desc,
      componentId: owner ? owner.getAttribute('wire:id') : null,
      text: (box.innerText || '').replace(/\s+/g, ' ').trim().slice(0, 200),
    });
  }
  return out;
}"""


# {visible team name: option value} from the (hidden) team switcher.
_TEAM_OPTIONS_JS = r"""() => {
  const sel = [...document.querySelectorAll('select')].find(
    s => s.querySelector("option[value='default']"));
  if (!sel) return null;
  const out = {};
  for (const o of sel.options) out[o.textContent.trim()] = o.value;
  return out;
}"""

# Set selectedTeamId on the switch-team Livewire component; returns its id or null.
_SWITCH_TEAM_JS = r"""(teamId) => {
  for (const el of document.querySelectorAll('[wire\\:id]')) {
    const snap = el.getAttribute('wire:snapshot') || '';
    if (snap.includes('"switch-team"')) {
      window.Livewire.find(el.getAttribute('wire:id')).set('selectedTeamId', teamId);
      return el.getAttribute('wire:id');
    }
  }
  return null;
}"""


def _mask(token: str) -> str:
    head = token.split("|", 1)[0]
    return f"{head}|{token.split('|', 1)[1][:4]}…  ({len(token)} chars)"


def mint(url: str, email: str, password: str, description: str,
         permissions: list[str], expires: str, headless: bool = True,
         team: str | None = None) -> str:
    from playwright.sync_api import sync_playwright

    base = url.rstrip("/")
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=headless)
        page = browser.new_page()
        try:
            _login(page, base, email, password)
            if team:
                _switch_team(page, base, team)
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


def _switch_team(page, base: str, team: str) -> None:
    """Activate `team` (by visible name or numeric id) before acting.

    Tokens are scoped to the team that is active when they are created. A token minted
    under the wrong team authenticates fine but reports "Application not found" for
    every app it cannot see, which is easy to misread as a bad token.
    """
    options = page.evaluate(_TEAM_OPTIONS_JS)
    if not options:
        raise SystemExit("Team switcher not found — is this a multi-team instance?")
    value = options.get(team) or (team if team in options.values() else None)
    if value is None:
        raise SystemExit(f"Team {team!r} not found. Available: "
                         f"{', '.join(n for n in options if n != 'Switch team')}")
    # The switcher lives in a collapsed sidebar, so it is present but not visible and
    # select_option() times out waiting for it. Set the Livewire property instead,
    # which fires the same server-side switch the dropdown would.
    switched = page.evaluate(_SWITCH_TEAM_JS, value)
    if not switched:
        raise SystemExit("Could not find the switch-team Livewire component.")
    page.wait_for_timeout(2500)
    page.wait_for_load_state("networkidle", timeout=45000)


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


def list_tokens(url: str, email: str, password: str, headless: bool = True,
                team: str | None = None) -> list[str]:
    """Return one summary line per existing token."""
    from playwright.sync_api import sync_playwright
    base = url.rstrip("/")
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=headless)
        page = browser.new_page()
        try:
            _login(page, base, email, password)
            if team:
                _switch_team(page, base, team)
            page.goto(f"{base}/security/api-tokens", wait_until="networkidle", timeout=45000)
            return [f"{t['description']}  ·  {t['text']}" for t in page.evaluate(_TOKENS_JS)]
        finally:
            browser.close()


def revoke_tokens(url: str, email: str, password: str, match: str,
                  headless: bool = True, team: str | None = None) -> int:
    """Revoke every token whose description contains `match`. Returns the count."""
    from playwright.sync_api import sync_playwright
    base = url.rstrip("/")
    revoked = 0
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=headless)
        page = browser.new_page()
        try:
            _login(page, base, email, password)
            if team:
                _switch_team(page, base, team)
            page.goto(f"{base}/security/api-tokens", wait_until="networkidle", timeout=45000)
            # Clicking "Revoke token" only opens an Alpine modal that demands the
            # token's description be retyped. Rather than drive that, read each row's
            # x-data for its `submitAction: 'revoke(<id>)'` and call the Livewire
            # method directly — no modal, and it can't mis-target a re-rendered row.
            targets = [t for t in page.evaluate(_TOKENS_JS)
                       if match in (t["description"] or "") and t["componentId"]]
            for t in targets:
                page.evaluate("([c, m, i]) => window.Livewire.find(c).call(m, i)",
                              [t["componentId"], t["method"], t["id"]])
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

    # Ticking one box makes Coolify rewrite the whole set server-side — selecting
    # `deploy`, for instance, clears `read`. Each click is a Livewire round-trip, so
    # settle after every one (reading state too early returns the pre-render value)
    # and re-converge until the selection matches, rather than assuming one pass.
    page = form.page
    for _ in range(len(seen) + 2):
        wrong = [(perm, box) for perm, box in seen.items()
                 if box.is_checked() != (perm in wanted)]
        if not wrong:
            break
        perm, box = wrong[0]
        box.click()
        page.wait_for_timeout(1200)
    else:
        actual = sorted(p for p, b in seen.items() if b.is_checked())
        raise SystemExit(f"Could not set permissions to {sorted(wanted)}; "
                         f"the form settled on {actual}.")


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
    ap.add_argument("--team", default=os.getenv("COOLIFY_TEAM"),
                    help="team name or id to act under (default: COOLIFY_TEAM). "
                         "Tokens are scoped to the active team.")
    ap.add_argument("--headed", action="store_true", help="show the browser (debugging)")
    args = ap.parse_args()

    if not args.url:
        raise SystemExit("No Coolify URL — pass --url or set COOLIFY_URL.")
    email = os.getenv("COOLIFY_EMAIL")
    password = os.getenv("COOLIFY_PASSWORD")
    if not (email and password):
        raise SystemExit("Set COOLIFY_EMAIL and COOLIFY_PASSWORD (e.g. in .env).")

    if args.list:
        for line in list_tokens(args.url, email, password, headless=not args.headed,
                                team=args.team):
            print(" ", line)
        return 0

    if args.revoke:
        n = revoke_tokens(args.url, email, password, args.revoke,
                          headless=not args.headed, team=args.team)
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
                 headless=not args.headed, team=args.team)
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
