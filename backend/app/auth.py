"""Identity and login.

Two ways in, one session model:

  * username + password, hashed with argon2id (see passwords.py)
  * OAuth, which stores only an opaque provider id

Sessions are server-side rows with an opaque random id in an httpOnly cookie.
Nothing about the user is in the cookie, so it cannot be tampered with, and
logout genuinely revokes (the row is deleted) rather than just dropping a JWT
the client might keep using.

With AUTH_ENABLED=false the whole app runs as a single implicit local user,
which is what the eval harness uses.
"""
from __future__ import annotations
import os, re, secrets, sqlite3, time, urllib.parse
import httpx
from fastapi import APIRouter, HTTPException, Request, Response
from fastapi.responses import RedirectResponse
from pydantic import BaseModel
from . import db, passwords, store

COOKIE = "monsoon_session"
# On by default now that password login needs no configuration. Set
# AUTH_ENABLED=false to run the old single-implicit-user mode (handy for evals).
AUTH_ENABLED = os.environ.get("AUTH_ENABLED", "true").lower() not in ("0", "false", "no")
BASE_URL = os.environ.get("APP_BASE_URL", "http://localhost:8077").rstrip("/")
SESSION_DAYS = int(os.environ.get("SESSION_DAYS", "30"))

PROVIDERS = {
    "github": {
        "authorize": "https://github.com/login/oauth/authorize",
        "token": "https://github.com/login/oauth/access_token",
        "userinfo": "https://api.github.com/user",
        "scope": "read:user user:email",
        "client_id": os.environ.get("GITHUB_CLIENT_ID", ""),
        "client_secret": os.environ.get("GITHUB_CLIENT_SECRET", ""),
    },
    "google": {
        "authorize": "https://accounts.google.com/o/oauth2/v2/auth",
        "token": "https://oauth2.googleapis.com/token",
        "userinfo": "https://openidconnect.googleapis.com/v1/userinfo",
        "scope": "openid email profile",
        "client_id": os.environ.get("GOOGLE_CLIENT_ID", ""),
        "client_secret": os.environ.get("GOOGLE_CLIENT_SECRET", ""),
    },
}

# one-shot CSRF states: state -> (provider, expiry). Short-lived by design.
_states: dict[str, tuple[str, float]] = {}

router = APIRouter(prefix="/api/auth")


def configured() -> list[str]:
    return [n for n, p in PROVIDERS.items() if p["client_id"] and p["client_secret"]]


def _sweep() -> None:
    now = time.time()
    for k, (_, exp) in list(_states.items()):
        if exp < now:
            _states.pop(k, None)


def _set_cookie(resp: Response, sid: str) -> None:
    resp.set_cookie(
        COOKIE, sid,
        max_age=SESSION_DAYS * 86400,
        httponly=True,                       # JS can never read it
        samesite="lax",                      # blocks cross-site POST replay
        secure=BASE_URL.startswith("https"), # only over TLS in production
        path="/",
    )


async def resolve_user(request: Request) -> str:
    """The single point where a request becomes a user_id."""
    if not AUTH_ENABLED:
        return db.ensure_user(db.LOCAL_USER_ID)
    sid = request.cookies.get(COOKIE)
    uid = (db.user_for_session(sid) if sid else "") or ""
    # Not signed in is a first-class state, not an error: guests get the market,
    # search and the agent - they just have no book of their own.
    return uid or store.GUEST


class UserMiddleware:
    """Bind the current user for the lifetime of the request."""
    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            return await self.app(scope, receive, send)
        try:
            uid = await resolve_user(Request(scope, receive))
        except Exception:
            uid = ""
        store.set_current_user(uid or (store.GUEST if AUTH_ENABLED else db.LOCAL_USER_ID))
        scope["state"] = {**scope.get("state", {}), "user_id": uid}
        return await self.app(scope, receive, send)


# ───────────────────────── routes ─────────────────────────
@router.get("/providers")
async def providers():
    return {"auth_enabled": AUTH_ENABLED,
            "password": True,                 # always available, needs no config
            "providers": configured(),
            "hint": ("set GITHUB_CLIENT_ID/SECRET or GOOGLE_CLIENT_ID/SECRET to "
                     "add OAuth alongside username and password")}


# ───────────────────── username + password ─────────────────────
USERNAME_RE = re.compile(r"^[a-zA-Z0-9][a-zA-Z0-9._-]{2,31}$")
# names the app already uses for something else, or that would let one account
# impersonate the system in any UI that shows a username
RESERVED = {"guest", "local", "admin", "administrator", "root", "system",
            "monsoon", "support", "me", "api", "null", "undefined", "anonymous"}
# a signup budget, so one host cannot mint accounts in a loop
MAX_SIGNUPS_PER_IP = 10

# One message for every failed sign-in. "No such user" and "wrong password"
# must be indistinguishable, or the login form becomes a way to enumerate who
# has an account here.
BAD_LOGIN = "That username and password do not match."


class Credentials(BaseModel):
    username: str
    password: str
    name: str | None = None


class PasswordChange(BaseModel):
    current: str
    new: str


def _client_key(request: Request) -> str:
    fwd = request.headers.get("x-forwarded-for", "")
    return (fwd.split(",")[0].strip() or
            (request.client.host if request.client else "unknown"))


def _sign_in(uid: str, payload: dict) -> Response:
    from fastapi.responses import JSONResponse
    resp = JSONResponse(payload)
    _set_cookie(resp, db.create_session(uid, SESSION_DAYS))
    return resp


@router.post("/register")
async def register(body: Credentials, request: Request):
    username = body.username.strip()
    if not USERNAME_RE.match(username):
        raise HTTPException(400, "Usernames are 3-32 characters: letters, digits, "
                                 ". _ or -, starting with a letter or digit.")
    if username.lower() in RESERVED:
        raise HTTPException(400, "That username is reserved.")
    ipkey = f"signup:{_client_key(request)}"
    if len(passwords.fail_count(ipkey)) >= MAX_SIGNUPS_PER_IP:
        raise HTTPException(429, "Too many accounts created from here. Try later.")
    problem = passwords.strength_problem(body.password)
    if problem:
        raise HTTPException(400, problem)

    pw_hash = passwords.hash_password(body.password)
    try:
        uid = db.create_password_user(username, pw_hash, name=body.name or username)
    except sqlite3.IntegrityError:
        raise HTTPException(409, "That username is taken.")

    passwords.record_failure(ipkey)          # counts signups, not failures
    passwords.clear_failures(f"u:{username}")
    return _sign_in(uid, {"id": uid, "username": username,
                          "name": body.name or username, "signed_in": True,
                          "legacy_book": db.legacy_book_summary()})


@router.post("/claim-legacy")
async def claim_legacy(request: Request):
    """Move the pre-login book onto this account.

    This used to happen automatically for whichever account registered first.
    That was wrong: anything that can POST /register could take the book, and
    my own eval harness did exactly that. Claiming a book is now a thing the
    person asks for, once, from a page that shows them what they are claiming.
    """
    uid = (request.scope.get("state") or {}).get("user_id") or ""
    if not uid or uid == store.GUEST:
        raise HTTPException(401, "Sign in first.")
    if not db.legacy_book_summary():
        raise HTTPException(409, "There is no pre-login book left to claim.")
    moved = db.adopt_user_data(db.LOCAL_USER_ID, uid)
    return {"claimed": moved}


@router.post("/login")
async def login_password(body: Credentials, request: Request):
    username = body.username.strip()
    ukey, ipkey = f"u:{username}", f"ip:{_client_key(request)}"

    wait = max(passwords.locked_for(ukey), passwords.locked_for(ipkey))
    if wait:
        raise HTTPException(429, f"Too many attempts. Try again in "
                                 f"{max(1, wait // 60)} minute(s).")

    user = db.user_by_username(username)
    if not user or not user.get("password_hash"):
        passwords.dummy_verify()             # equalise timing; do not leak existence
        passwords.record_failure(ukey)
        passwords.record_failure(ipkey)
        raise HTTPException(401, BAD_LOGIN)

    if not passwords.verify_password(body.password, user["password_hash"]):
        passwords.record_failure(ukey)
        passwords.record_failure(ipkey)
        raise HTTPException(401, BAD_LOGIN)

    # cheap upgrade path: re-hash on a correct login if parameters moved
    if passwords.needs_rehash(user["password_hash"]):
        db.set_password_hash(user["id"], passwords.hash_password(body.password))

    passwords.clear_failures(ukey)
    passwords.clear_failures(ipkey)
    return _sign_in(user["id"], {"id": user["id"], "username": user["username"],
                                 "name": user.get("name"), "signed_in": True})


@router.post("/password")
async def change_password(body: PasswordChange, request: Request):
    uid = (request.scope.get("state") or {}).get("user_id") or ""
    user = db.get_user(uid) if uid else None
    if not user or not user.get("password_hash"):
        raise HTTPException(401, "Sign in first.")
    if not passwords.verify_password(body.current, user["password_hash"]):
        raise HTTPException(401, "Your current password is not right.")
    problem = passwords.strength_problem(body.new)
    if problem:
        raise HTTPException(400, problem)
    db.set_password_hash(uid, passwords.hash_password(body.new))
    # every other device is logged out: a leaked cookie must not survive this
    revoked = db.drop_user_sessions(uid, keep=request.cookies.get(COOKIE))
    return {"ok": True, "other_sessions_revoked": revoked}


@router.get("/login/{provider}")
async def login(provider: str):
    p = PROVIDERS.get(provider)
    if not p or not p["client_id"]:
        raise HTTPException(404, f"{provider} is not configured")
    _sweep()
    state = secrets.token_urlsafe(24)
    _states[state] = (provider, time.time() + 600)       # 10 minutes
    qs = urllib.parse.urlencode({
        "client_id": p["client_id"],
        "redirect_uri": f"{BASE_URL}/api/auth/callback/{provider}",
        "scope": p["scope"], "state": state, "response_type": "code",
    })
    return RedirectResponse(f"{p['authorize']}?{qs}", status_code=302)


@router.get("/callback/{provider}")
async def callback(provider: str, code: str = "", state: str = ""):
    p = PROVIDERS.get(provider)
    if not p:
        raise HTTPException(404, "unknown provider")
    want = _states.pop(state, None)
    if not want or want[0] != provider or want[1] < time.time():
        raise HTTPException(400, "invalid or expired login state")   # CSRF guard
    if not code:
        raise HTTPException(400, "no authorization code returned")

    async with httpx.AsyncClient(timeout=20) as c:
        tok = await c.post(p["token"], headers={"Accept": "application/json"}, data={
            "client_id": p["client_id"], "client_secret": p["client_secret"],
            "code": code, "redirect_uri": f"{BASE_URL}/api/auth/callback/{provider}",
            "grant_type": "authorization_code"})
        tok.raise_for_status()
        access = tok.json().get("access_token")
        if not access:
            raise HTTPException(400, "provider did not return an access token")
        who = await c.get(p["userinfo"], headers={
            "Authorization": f"Bearer {access}", "Accept": "application/json"})
        who.raise_for_status()
        info = who.json()

    pid = str(info.get("id") or info.get("sub") or "")
    if not pid:
        raise HTTPException(400, "provider did not identify the user")
    email = info.get("email")
    name = info.get("name") or info.get("login") or email or "User"

    existing = db.user_by_provider(provider, pid)
    uid = existing["id"] if existing else db.ensure_user(
        db.new_id(), email=email, name=name, provider=provider, provider_id=pid)

    resp = RedirectResponse("/", status_code=302)
    _set_cookie(resp, db.create_session(uid, SESSION_DAYS))
    return resp


@router.delete("/account")
async def delete_account(request: Request, confirm: str = ""):
    """Delete the signed-in account and everything under it.

    `confirm` must be the username: a DELETE that a stray fetch could fire by
    accident is not an acceptable way to lose a portfolio. Positions, accounts,
    watchlist, prefs and sessions all go with it via ON DELETE CASCADE.
    """
    uid = (request.scope.get("state") or {}).get("user_id") or ""
    user = db.get_user(uid) if uid and uid != store.GUEST else None
    if not user:
        raise HTTPException(401, "Sign in first.")
    if confirm.strip().lower() != (user.get("username") or "").lower():
        raise HTTPException(400, "Type your username to confirm.")
    db.delete_user(uid)
    resp = Response(status_code=204)
    resp.delete_cookie(COOKIE, path="/")
    return resp


@router.post("/logout")
async def logout(request: Request):
    sid = request.cookies.get(COOKIE)
    if sid:
        db.drop_session(sid)                 # server-side revoke, not just a cleared cookie
    resp = Response(status_code=204)
    resp.delete_cookie(COOKIE, path="/")
    return resp


# kept at /api/me for the client
me_router = APIRouter(prefix="/api")


@me_router.get("/me")
async def me(request: Request):
    uid = (request.scope.get("state") or {}).get("user_id") or store.current_user_id()
    u = db.get_user(uid) or {}
    guest = AUTH_ENABLED and uid in ("", store.GUEST)
    return {"id": store.GUEST if guest else (uid or db.LOCAL_USER_ID),
            "name": "Guest" if guest else u.get("name"),
            "username": None if guest else u.get("username"),
            "email": None if guest else u.get("email"),
            "provider": None if guest else u.get("provider"),
            "signed_in": not guest,
            "guest": guest,
            "can_save": not guest,
            "legacy_book": None if guest else db.legacy_book_summary(),
            "auth_enabled": AUTH_ENABLED, "password_login": True,
            "providers": configured()}
