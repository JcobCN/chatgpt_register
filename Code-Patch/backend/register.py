import base64
import hashlib
import json
import logging
import os
import random
import re
import secrets
import string
import time
import urllib
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from typing import Any, Dict

from curl_cffi import requests
from dotenv import load_dotenv

logger = logging.getLogger("uvicorn.error")

# .env 在根目录（backend/ 的上一级）
ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
load_dotenv(os.path.join(ROOT_DIR, ".env"))

WORKER_URL = os.getenv("WORKER_URL", "").strip()
EMAIL_DOMAIN = os.getenv("EMAIL_DOMAIN", "").strip()
ADMIN_AUTH = os.getenv("ADMIN_AUTH", "").strip()

# ---------------------------------------------------------------------------
# 临时邮箱
# ---------------------------------------------------------------------------

def _random_profile() -> str:
    """生成随机姓名 + 成年出生日期（18-55岁）的 JSON 字符串。"""
    first = ''.join(random.choices(string.ascii_lowercase, k=random.randint(4, 8))).capitalize()
    last  = ''.join(random.choices(string.ascii_lowercase, k=random.randint(4, 8))).capitalize()
    name  = f"{first} {last}"

    today = time.gmtime()
    age   = random.randint(18, 55)
    year  = today.tm_year - age
    month = random.randint(1, 12)
    # 确保出生日期不超过今天
    max_day = [31,28,31,30,31,30,31,31,30,31,30,31][month - 1]
    if year % 4 == 0 and (year % 100 != 0 or year % 400 == 0):
        if month == 2:
            max_day = 29
    day = random.randint(1, max_day)
    birthdate = f"{year}-{month:02d}-{day:02d}"

    return json.dumps({"name": name, "birthdate": birthdate}, separators=(",", ":"))


def generate_random_name() -> str:
    letters1 = ''.join(random.choices(string.ascii_lowercase, k=5))
    numbers = ''.join(random.choices(string.digits, k=random.randint(1, 3)))
    letters2 = ''.join(random.choices(string.ascii_lowercase, k=random.randint(1, 3)))
    return letters1 + numbers + letters2


def get_email() -> tuple[str, str]:
    if not WORKER_URL or not EMAIL_DOMAIN or not ADMIN_AUTH:
        raise RuntimeError("Missing env: WORKER_URL / EMAIL_DOMAIN / ADMIN_AUTH (set them in project root .env)")
    name = generate_random_name()
    res = requests.post(
        f"{WORKER_URL}/admin/new_address",
        json={"enablePrefix": True, "name": name, "domain": EMAIL_DOMAIN},
        headers={"x-admin-auth": ADMIN_AUTH, "Content-Type": "application/json"}
    )
    logger.info("get_email status=%s body=%s", res.status_code, res.text[:200])
    if res.status_code != 200:
        raise RuntimeError(f"邮件服务返回 {res.status_code}: {res.text[:200]}")
    data = res.json()
    return data["address"], data["jwt"]


def get_oai_code(email: str, jwt: str) -> str:
    if not WORKER_URL or not ADMIN_AUTH:
        raise RuntimeError("Missing env: WORKER_URL / ADMIN_AUTH (set them in project root .env)")
    regex = r"(?<!\d)(\d{6})(?!\d)"
    for _ in range(20):
        res = requests.get(
            f"{WORKER_URL}/admin/mails",
            headers={"x-admin-auth": ADMIN_AUTH},
            params={"limit": "20", "offset": "0", "address": email}
        )
        mails = res.json().get("results", [])
        for mail in mails:
            if "openai" in mail.get("source", ""):
                m = re.search(regex, mail.get("subject", ""))
                if m:
                    return m.group(1)
                m = re.search(regex, mail.get("raw", ""))
                if m:
                    return m.group(1)
        time.sleep(3)

# ---------------------------------------------------------------------------
# OAuth / PKCE 工具
# ---------------------------------------------------------------------------

AUTH_URL = "https://auth.openai.com/oauth/authorize"
TOKEN_URL = "https://auth.openai.com/oauth/token"
CLIENT_ID = "app_EMoamEEZ73f0CkXaXp7hrann"
DEFAULT_REDIRECT_URI = "http://localhost:1455/auth/callback"
DEFAULT_SCOPE = "openid email profile offline_access"


def _b64url_no_pad(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")


def _sha256_b64url_no_pad(s: str) -> str:
    return _b64url_no_pad(hashlib.sha256(s.encode("ascii")).digest())


def _random_state(nbytes: int = 16) -> str:
    return secrets.token_urlsafe(nbytes)


def _pkce_verifier() -> str:
    return secrets.token_urlsafe(64)


def _parse_callback_url(callback_url: str) -> Dict[str, str]:
    candidate = callback_url.strip()
    if not candidate:
        return {"code": "", "state": "", "error": "", "error_description": ""}

    if "://" not in candidate:
        if candidate.startswith("?"):
            candidate = f"http://localhost{candidate}"
        elif any(ch in candidate for ch in "/?#") or ":" in candidate:
            candidate = f"http://{candidate}"
        elif "=" in candidate:
            candidate = f"http://localhost/?{candidate}"

    parsed = urllib.parse.urlparse(candidate)
    query = urllib.parse.parse_qs(parsed.query, keep_blank_values=True)
    fragment = urllib.parse.parse_qs(parsed.fragment, keep_blank_values=True)

    for key, values in fragment.items():
        if key not in query or not query[key] or not (query[key][0] or "").strip():
            query[key] = values

    def get1(k: str) -> str:
        v = query.get(k, [""])
        return (v[0] or "").strip()

    code = get1("code")
    state = get1("state")
    error = get1("error")
    error_description = get1("error_description")

    if code and not state and "#" in code:
        code, state = code.split("#", 1)
    if not error and error_description:
        error, error_description = error_description, ""

    return {"code": code, "state": state, "error": error, "error_description": error_description}


def _jwt_claims_no_verify(id_token: str) -> Dict[str, Any]:
    if not id_token or id_token.count(".") < 2:
        return {}
    payload_b64 = id_token.split(".")[1]
    pad = "=" * ((4 - (len(payload_b64) % 4)) % 4)
    try:
        payload = base64.urlsafe_b64decode((payload_b64 + pad).encode("ascii"))
        return json.loads(payload.decode("utf-8"))
    except Exception:
        return {}


def _to_int(v: Any) -> int:
    try:
        return int(v)
    except (TypeError, ValueError):
        return 0


def _post_form(url: str, data: Dict[str, str], timeout: int = 30) -> Dict[str, Any]:
    body = urllib.parse.urlencode(data).encode("utf-8")
    req = urllib.request.Request(
        url, data=body, method="POST",
        headers={"Content-Type": "application/x-www-form-urlencoded", "Accept": "application/json"},
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            raw = resp.read()
            if resp.status != 200:
                raise RuntimeError(f"token exchange failed: {resp.status}: {raw.decode('utf-8', 'replace')}")
            return json.loads(raw.decode("utf-8"))
    except urllib.error.HTTPError as exc:
        raw = exc.read()
        raise RuntimeError(f"token exchange failed: {exc.code}: {raw.decode('utf-8', 'replace')}") from exc


@dataclass(frozen=True)
class OAuthStart:
    auth_url: str
    state: str
    code_verifier: str
    redirect_uri: str


def generate_oauth_url(
    *, redirect_uri: str = DEFAULT_REDIRECT_URI, scope: str = DEFAULT_SCOPE
) -> OAuthStart:
    state = _random_state()
    code_verifier = _pkce_verifier()
    code_challenge = _sha256_b64url_no_pad(code_verifier)
    params = {
        "client_id": CLIENT_ID, "response_type": "code",
        "redirect_uri": redirect_uri, "scope": scope,
        "state": state, "code_challenge": code_challenge,
        "code_challenge_method": "S256", "prompt": "login",
        "id_token_add_organizations": "true", "codex_cli_simplified_flow": "true",
    }
    auth_url = f"{AUTH_URL}?{urllib.parse.urlencode(params)}"
    return OAuthStart(auth_url=auth_url, state=state, code_verifier=code_verifier, redirect_uri=redirect_uri)


def submit_callback_url(
    *, callback_url: str, expected_state: str, code_verifier: str,
    redirect_uri: str = DEFAULT_REDIRECT_URI
) -> str:
    cb = _parse_callback_url(callback_url)
    if cb["error"]:
        raise RuntimeError(f"oauth error: {cb['error']}: {cb['error_description']}".strip())
    if not cb["code"]:
        raise ValueError("callback url missing ?code=")
    if not cb["state"]:
        raise ValueError("callback url missing ?state=")
    if cb["state"] != expected_state:
        raise ValueError("state mismatch")

    token_resp = _post_form(TOKEN_URL, {
        "grant_type": "authorization_code", "client_id": CLIENT_ID,
        "code": cb["code"], "redirect_uri": redirect_uri, "code_verifier": code_verifier,
    })

    access_token = (token_resp.get("access_token") or "").strip()
    refresh_token = (token_resp.get("refresh_token") or "").strip()
    id_token = (token_resp.get("id_token") or "").strip()
    expires_in = _to_int(token_resp.get("expires_in"))

    claims = _jwt_claims_no_verify(id_token)
    email = str(claims.get("email") or "").strip()
    auth_claims = claims.get("https://api.openai.com/auth") or {}
    account_id = str(auth_claims.get("chatgpt_account_id") or "").strip()

    now = int(time.time())
    expired_rfc3339 = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(now + max(expires_in, 0)))
    now_rfc3339 = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(now))

    return json.dumps({
        "id_token": id_token, "access_token": access_token,
        "refresh_token": refresh_token, "account_id": account_id,
        "last_refresh": now_rfc3339, "email": email,
        "type": "codex", "expired": expired_rfc3339,
    }, ensure_ascii=False, separators=(",", ":"))

# ---------------------------------------------------------------------------
# 反检测工具
# ---------------------------------------------------------------------------

_IMPERSONATE_POOL = [
    "chrome110", "chrome116", "chrome120", "chrome123", "chrome124",
    "chrome131", "edge101",
    "safari15_5", "safari17_0",
]

# Chrome/Edge Client Hints — 缺少这些头是很大的指纹特征
_CLIENT_HINTS = {
    "chrome110": ('"Chromium";v="110", "Google Chrome";v="110", "Not_A Brand";v="24"', "Windows"),
    "chrome116": ('"Chromium";v="116", "Google Chrome";v="116", "Not_A Brand";v="24"', "Windows"),
    "chrome120": ('"Chromium";v="120", "Google Chrome";v="120", "Not_A Brand";v="24"', "macOS"),
    "chrome123": ('"Chromium";v="123", "Google Chrome";v="123", "Not_A Brand";v="24"', "Windows"),
    "chrome124": ('"Chromium";v="124", "Google Chrome";v="124", "Not_A Brand";v="24"', "macOS"),
    "chrome131": ('"Chromium";v="131", "Google Chrome";v="131", "Not_A Brand";v="24"', "Windows"),
    "edge101":   ('"Chromium";v="101", "Microsoft Edge";v="101", "Not_A Brand";v="99"', "Windows"),
    # Safari 不发送 Client Hints
}

_ACCEPT_LANGUAGES = [
    "en-US,en;q=0.9",
    "en-GB,en;q=0.9",
    "en-US,en;q=0.9,ja;q=0.8",
    "en,en-US;q=0.9",
    "en-US,en;q=0.8,zh-CN;q=0.7",
]


def _human_delay(lo: float = 0.5, hi: float = 2.5):
    """模拟人类操作间隔，带轻微随机抖动。"""
    base = random.uniform(lo, hi)
    # 5% 概率额外停顿，模拟真人偶尔走神
    if random.random() < 0.05:
        base += random.uniform(0.5, 1.5)
    time.sleep(base)


def _make_session(proxy: str) -> requests.Session:
    """创建带随机浏览器指纹的 session，包含 Client Hints。"""
    fp = random.choice(_IMPERSONATE_POOL)
    s = requests.Session(
        proxies={"http": proxy, "https": proxy},
        impersonate=fp,
    )
    headers = {"accept-language": random.choice(_ACCEPT_LANGUAGES)}
    # Chrome/Edge 需要 Client Hints
    if fp in _CLIENT_HINTS:
        ua_str, platform = _CLIENT_HINTS[fp]
        headers["sec-ch-ua"] = ua_str
        headers["sec-ch-ua-mobile"] = "?0"
        headers["sec-ch-ua-platform"] = f'"{platform}"'
    s.headers.update(headers)
    return s


def check_proxy(proxy: str, timeout: int = 8) -> tuple[bool, str]:
    """
    检测代理是否可用（仅验证连通性）。
    地区检查由注册流程中的 _check_loc 负责，因为代理池每次出口 IP 可能不同。
    返回: (可用, 信息)
    """
    try:
        resp = requests.get(
            "https://cloudflare.com/cdn-cgi/trace",
            proxies={"http": proxy, "https": proxy},
            timeout=timeout,
            impersonate=random.choice(_IMPERSONATE_POOL),
        )
        if resp.status_code != 200:
            return False, f"HTTP {resp.status_code}"
        loc_m = re.search(r"^loc=(.+)$", resp.text, re.MULTILINE)
        loc = loc_m.group(1).strip() if loc_m else "unknown"
        return True, loc
    except Exception as e:
        return False, str(e)[:80]


# ---------------------------------------------------------------------------
# 主入口
# ---------------------------------------------------------------------------

def run(proxy: str) -> str:
    s = _make_session(proxy)

    trace_resp = s.get("https://cloudflare.com/cdn-cgi/trace", timeout=10)
    logger.info("trace status=%s len=%s", trace_resp.status_code, len(trace_resp.text))
    trace = trace_resp.text
    ip_re = re.search(r"^ip=(.+)$", trace, re.MULTILINE)
    loc_re = re.search(r"^loc=(.+)$", trace, re.MULTILINE)
    loc = loc_re.group(1) if loc_re else None
    exit_ip = ip_re.group(1) if ip_re else None
    logger.info("proxy=%s exit_ip=%s loc=%s", proxy, exit_ip, loc)
    if loc in ("CN", "HK"):
        raise RuntimeError(f"检查代理哦w (loc={loc}, ip={exit_ip})")

    email, jwt = get_email()
    logger.info("email=%s", email)
    oauth = generate_oauth_url()

    _human_delay(0.3, 1.0)
    s.get(oauth.auth_url)
    did = s.cookies.get("oai-did")

    _human_delay(0.5, 1.5)
    signup_body = f'{{"username":{{"value":"{email}","kind":"email"}},"screen_hint":"signup"}}'
    sen_req_body = f'{{"p":"","id":"{did}","flow":"authorize_continue"}}'
    sen_resp = s.post(
        "https://sentinel.openai.com/backend-api/sentinel/req",
        headers={
            "origin": "https://sentinel.openai.com",
            "referer": "https://sentinel.openai.com/backend-api/sentinel/frame.html?sv=20260219f9f6",
            "content-type": "text/plain;charset=UTF-8",
        },
        data=sen_req_body,
    )
    logger.info("sentinel status=%s body=%s", sen_resp.status_code, sen_resp.text[:200])
    sentinel_token = sen_resp.json()["token"]
    sentinel = f'{{"p": "", "t": "", "c": "{sentinel_token}", "id": "{did}", "flow": "authorize_continue"}}'

    _human_delay(0.8, 2.0)
    signup_resp = s.post(
        "https://auth.openai.com/api/accounts/authorize/continue",
        headers={"referer": "https://auth.openai.com/create-account", "accept": "application/json",
                 "content-type": "application/json", "openai-sentinel-token": sentinel},
        data=signup_body,
    )
    logger.info("signup status=%s body=%s", signup_resp.status_code, signup_resp.text[:200])

    _human_delay(0.5, 1.5)
    otp_resp = s.post(
        "https://auth.openai.com/api/accounts/passwordless/send-otp",
        headers={"referer": "https://auth.openai.com/create-account/password",
                 "accept": "application/json", "content-type": "application/json"},
    )
    logger.info("otp status=%s", otp_resp.status_code)

    code = get_oai_code(email, jwt)
    logger.info("otp code=%s", code)

    _human_delay(1.0, 3.0)
    code_resp = s.post(
        "https://auth.openai.com/api/accounts/email-otp/validate",
        headers={"referer": "https://auth.openai.com/email-verification", "accept": "application/json",
                 "content-type": "application/json"},
        data=f'{{"code":"{code}"}}',
    )
    logger.info("validate status=%s", code_resp.status_code)

    _human_delay(1.0, 3.0)
    create_resp = s.post(
        "https://auth.openai.com/api/accounts/create_account",
        headers={"referer": "https://auth.openai.com/about-you", "accept": "application/json",
                 "content-type": "application/json"},
        data=_random_profile(),
    )
    logger.info("create status=%s", create_resp.status_code)
    if create_resp.status_code != 200:
        logger.warning("create failed: %s", create_resp.text[:200])
        return None

    auth = s.cookies.get("oai-client-auth-session")
    auth = json.loads(base64.b64decode(auth.split(".")[0]))
    workspace_id = auth["workspaces"][0]["id"]

    _human_delay(0.5, 1.5)
    select_resp = s.post(
        "https://auth.openai.com/api/accounts/workspace/select",
        headers={"referer": "https://auth.openai.com/sign-in-with-chatgpt/codex/consent",
                 "content-type": "application/json"},
        data=f'{{"workspace_id":"{workspace_id}"}}',
    )
    logger.info("select status=%s", select_resp.status_code)

    continue_url = select_resp.json()["continue_url"]
    r = s.get(continue_url, allow_redirects=False)
    r = s.get(r.headers.get("Location"), allow_redirects=False)
    r = s.get(r.headers.get("Location"), allow_redirects=False)
    cbk = r.headers.get("Location")

    result_str = submit_callback_url(
        callback_url=cbk,
        code_verifier=oauth.code_verifier,
        redirect_uri=oauth.redirect_uri,
        expected_state=oauth.state,
    )
    # 注入出口 IP 到返回数据
    result = json.loads(result_str)
    result["exit_ip"] = exit_ip
    return json.dumps(result, ensure_ascii=False, separators=(",", ":"))


# ---------------------------------------------------------------------------
# 存活检测
# ---------------------------------------------------------------------------

CHATGPT_API_BASE = "https://chatgpt.com/backend-api"


CODEX_USAGE_URL = f"{CHATGPT_API_BASE}/wham/usage"

_CODEX_VERSIONS = ["0.74.0", "0.75.0", "0.76.0", "0.77.0", "0.78.0"]
_CODEX_PLATFORMS = [
    "(Debian 13.0.0; x86_64) WindowsTerminal",
    "(Ubuntu 22.04; x86_64) WindowsTerminal",
    "(macOS 14.5; arm64) Terminal",
    "(Windows 11; x86_64) WindowsTerminal",
    "(Debian 12.0.0; x86_64) tmux",
]


def _codex_ua() -> str:
    ver = random.choice(_CODEX_VERSIONS)
    plat = random.choice(_CODEX_PLATFORMS)
    return f"codex_cli_rs/{ver} {plat}"


def check_alive(refresh_token: str, proxy: str) -> tuple:
    """
    三步验证账号存活：
    1. 用 refresh_token 换新的 access_token
    2. 从 id_token 中解析 account_id
    3. 用 access_token + account_id 调用 /backend-api/wham/usage 检查配额

    返回: (status, access_token, refresh_token, id_token, plan_type, expires_at, usage_json)
    status: 'alive' | 'dead' | 'error'
    """
    s = _make_session(proxy)

    # Step 1: 刷新 token
    try:
        resp = s.post(
            TOKEN_URL,
            data={
                "grant_type": "refresh_token",
                "client_id": CLIENT_ID,
                "refresh_token": refresh_token,
            },
            headers={"Content-Type": "application/x-www-form-urlencoded",
                     "Accept": "application/json"},
            timeout=20,
        )
        if resp.status_code in (400, 401):
            return "dead", None, None, None, None, None, None
        if resp.status_code != 200:
            return "error", None, None, None, None, None, None

        token_data = resp.json()
        new_access = token_data.get("access_token")
        new_refresh = token_data.get("refresh_token")
        new_id = token_data.get("id_token")
        if not new_access:
            return "dead", None, None, None, None, None, None
    except Exception:
        return "error", None, None, None, None, None, None

    # Step 2: 从 id_token 解析 account_id
    account_id = ""
    if new_id:
        claims = _jwt_claims_no_verify(new_id)
        auth_claims = claims.get("https://api.openai.com/auth") or {}
        account_id = str(auth_claims.get("chatgpt_account_id") or "").strip()

    _human_delay(0.3, 1.0)

    # Step 3: 用 wham/usage 接口检查配额状态
    try:
        usage_headers = {
            "Content-Type": "application/json",
            "User-Agent": _codex_ua(),
            "Authorization": f"Bearer {new_access}",
        }
        if account_id:
            usage_headers["Chatgpt-Account-Id"] = account_id

        usage_resp = s.get(
            CODEX_USAGE_URL,
            headers=usage_headers,
            timeout=20,
        )

        if usage_resp.status_code in (401, 403):
            return "dead", None, None, None, None, None, None
        if usage_resp.status_code != 200:
            return "error", new_access, new_refresh, new_id, None, None, None

        data = usage_resp.json()
        plan_type = data.get("plan_type")
        usage_json = json.dumps(data, ensure_ascii=False, separators=(",", ":"))

        # 从 token expires_in 计算过期时间
        expires_in = _to_int(token_data.get("expires_in"))
        now = int(time.time())
        expires_at = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(now + max(expires_in, 0)))

        return "alive", new_access, new_refresh, new_id, plan_type, expires_at, usage_json
    except Exception:
        # wham/usage 失败但 token 刷新成功，保守标记为 error
        return "error", new_access, new_refresh, new_id, None, None, None
