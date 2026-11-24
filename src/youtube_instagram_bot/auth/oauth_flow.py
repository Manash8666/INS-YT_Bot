"""
One-click OAuth 2.0 flow for Instagram and YouTube.

How it works:
  1. User clicks "Connect" in the dashboard
  2. Frontend calls POST /api/oauth/{platform}/start
  3. Backend generates the authorization URL and returns it
  4. Frontend opens that URL in a new browser tab (or popup)
  5. User approves access in Facebook/Google
  6. Platform redirects back to GET /api/oauth/{platform}/callback?code=...
  7. Backend exchanges the code for tokens, saves them to .env, hot-reloads
  8. Backend renders a success HTML page that closes the popup and
     sends a postMessage to the parent window
  9. Frontend receives the message, updates the status badge to LIVE
"""

import os
import httpx
import secrets
import logging
from datetime import datetime, timedelta
from typing import Optional

log = logging.getLogger(__name__)

GRAPH_BASE  = "https://graph.facebook.com/v19.0"
GOOGLE_AUTH = "https://accounts.google.com/o/oauth2/v2/auth"
GOOGLE_TOKEN = "https://oauth2.googleapis.com/token"


# ── State store (in-memory, keyed by random state param) ─────────────────────
_pending: dict[str, dict] = {}   # state -> {platform, redirect_uri, ...}


def generate_state() -> str:
    return secrets.token_urlsafe(32)


# ═════════════════════════════════════════════════════════════════════════════
#  INSTAGRAM (Facebook Graph API — Consumer app, Basic Display or Graph)
# ═════════════════════════════════════════════════════════════════════════════

def instagram_auth_url(
    app_id: str,
    redirect_uri: str,
    state: str,
    scopes: list[str] | None = None,
) -> str:
    """
    Build the Facebook Login URL that asks for Instagram permissions.

    Scopes used:
      instagram_basic           – read profile + media
      instagram_content_publish – publish media  (requires Business/Creator account)
      instagram_manage_insights – read insights
      pages_show_list           – list pages (required by Graph API)
      pages_read_engagement     – read page engagement
    """
    if scopes is None:
        scopes = [
            "instagram_basic",
            "instagram_content_publish",
            "instagram_manage_insights",
            "pages_show_list",
            "pages_read_engagement",
        ]

    import urllib.parse
    params = {
        "client_id":     app_id,
        "redirect_uri":  redirect_uri,
        "scope":         ",".join(scopes),
        "response_type": "code",
        "state":         state,
    }
    return "https://www.facebook.com/v19.0/dialog/oauth?" + urllib.parse.urlencode(params)


def instagram_exchange_code(
    app_id: str,
    app_secret: str,
    redirect_uri: str,
    code: str,
) -> dict:
    """
    Exchange the authorization code for a short-lived token,
    then upgrade it to a 60-day long-lived token.
    Returns: {"access_token": ..., "token_type": ..., "expires_in": ...}
    """
    client = httpx.Client(timeout=30)

    # 1. Short-lived token
    r = client.post("https://graph.facebook.com/v19.0/oauth/access_token", data={
        "client_id":     app_id,
        "client_secret": app_secret,
        "redirect_uri":  redirect_uri,
        "code":          code,
    })
    r.raise_for_status()
    short = r.json()
    if "error" in short:
        raise ValueError(f"Token exchange failed: {short['error']}")
    short_token = short["access_token"]

    # 2. Long-lived token (valid 60 days)
    r2 = client.get(f"{GRAPH_BASE}/oauth/access_token", params={
        "grant_type":        "fb_exchange_token",
        "client_id":         app_id,
        "client_secret":     app_secret,
        "fb_exchange_token": short_token,
    })
    r2.raise_for_status()
    long = r2.json()
    if "error" in long:
        raise ValueError(f"Long-lived token exchange failed: {long['error']}")

    # 3. Get the Instagram user ID linked to this token
    r3 = client.get(f"{GRAPH_BASE}/me/accounts", params={
        "access_token": long["access_token"],
        "fields":       "instagram_business_account",
    })
    r3.raise_for_status()
    pages = r3.json().get("data", [])
    ig_user_id = ""
    for page in pages:
        ig_acc = page.get("instagram_business_account", {})
        if ig_acc.get("id"):
            ig_user_id = ig_acc["id"]
            break

    # 4. If no business account, try Basic Display API path
    if not ig_user_id:
        r4 = client.get(f"{GRAPH_BASE}/me", params={
            "access_token": long["access_token"],
            "fields":       "id,name",
        })
        if r4.status_code == 200:
            ig_user_id = r4.json().get("id", "")

    client.close()

    return {
        "access_token": long["access_token"],
        "expires_in":   long.get("expires_in", 5183944),   # ~60 days
        "ig_user_id":   ig_user_id,
    }


# ═════════════════════════════════════════════════════════════════════════════
#  YOUTUBE (Google OAuth 2.0)
# ═════════════════════════════════════════════════════════════════════════════

def youtube_auth_url(
    client_id: str,
    redirect_uri: str,
    state: str,
) -> str:
    """Build the Google OAuth2 authorization URL for YouTube."""
    import urllib.parse
    params = {
        "client_id":             client_id,
        "redirect_uri":          redirect_uri,
        "response_type":         "code",
        "scope":                 "https://www.googleapis.com/auth/youtube",
        "access_type":           "offline",   # get refresh_token
        "prompt":                "consent",   # always show consent to get refresh_token
        "state":                 state,
        "include_granted_scopes": "true",
    }
    return GOOGLE_AUTH + "?" + urllib.parse.urlencode(params)


def youtube_exchange_code(
    client_id: str,
    client_secret: str,
    redirect_uri: str,
    code: str,
) -> dict:
    """
    Exchange authorization code for access_token + refresh_token.
    Returns: {"access_token": ..., "refresh_token": ..., "expires_in": ...}
    """
    client = httpx.Client(timeout=30)
    r = client.post(GOOGLE_TOKEN, data={
        "code":          code,
        "client_id":     client_id,
        "client_secret": client_secret,
        "redirect_uri":  redirect_uri,
        "grant_type":    "authorization_code",
    })
    client.close()
    r.raise_for_status()
    data = r.json()
    if "error" in data:
        raise ValueError(f"YouTube token exchange failed: {data.get('error_description', data['error'])}")
    if "refresh_token" not in data:
        raise ValueError(
            "No refresh_token returned. "
            "Make sure you approved the app on the Google consent screen. "
            "Try revoking access at myaccount.google.com/permissions and retry."
        )
    return data


# ═════════════════════════════════════════════════════════════════════════════
#  .env persistence helper
# ═════════════════════════════════════════════════════════════════════════════

def save_to_env(env_path: str, updates: dict[str, str]) -> None:
    """Write/update key=value pairs in an .env file."""
    lines = []
    if os.path.exists(env_path):
        with open(env_path, encoding="utf-8") as f:
            lines = f.readlines()

    for key, value in updates.items():
        key_prefix = f"{key}="
        replaced = False
        for i, line in enumerate(lines):
            if line.strip().startswith(key_prefix) or line.strip() == key_prefix.rstrip("="):
                lines[i] = f"{key}={value}\n"
                replaced = True
                break
        if not replaced:
            lines.append(f"{key}={value}\n")

    with open(env_path, "w", encoding="utf-8") as f:
        f.writelines(lines)
    log.info(f"Saved {list(updates.keys())} to .env")