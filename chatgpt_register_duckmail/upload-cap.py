
import json
import os
import re
import sys
import time
import uuid
import random
import string
import secrets
import hashlib
import base64
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone, timedelta
from urllib.parse import urlparse, parse_qs, urlencode

import requests as std_requests
# 使用 curl_ffi 模拟真实浏览器，解决 TLS/JA3 指纹校验
from curl_cffi import requests as curl_requests

# =================== 配置加载 ===================

def load_config():
    """加载配置文件"""
    config = {
        "proxy": "",
        "upload_api_url": "",
        "upload_api_token": "",
        "duckmail_api_base": "https://api.duckmail.sbs",
        "output_file": "registered_accounts.txt",
        "oauth_issuer": "https://auth.openai.com",
        "oauth_client_id": "app_EMoamEEZ73f0CkXaXp7hrann",
        "oauth_redirect_uri": "http://localhost:1455/auth/callback"
    }
    
    config_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "config.json")
    if os.path.exists(config_path):
        try:
            with open(config_path, "r", encoding="utf-8") as f:
                file_config = json.load(f)
                config.update(file_config)
        except Exception as e:
            print(f"⚠️ 加载 config.json 失败: {e}")
    return config

_CONFIG = load_config()
PROXY = _CONFIG.get("proxy")
UPLOAD_API_URL = _CONFIG.get("upload_api_url")
UPLOAD_API_TOKEN = _CONFIG.get("upload_api_token")
DUCKMAIL_API_BASE = _CONFIG.get("duckmail_api_base")
ACCOUNTS_FILE = _CONFIG.get("output_file")
OAUTH_ISSUER = _CONFIG.get("oauth_issuer")
OAUTH_CLIENT_ID = _CONFIG.get("oauth_client_id")
OAUTH_REDIRECT_URI = _CONFIG.get("oauth_redirect_uri")

OPENAI_AUTH_BASE = "https://auth.openai.com"
IMPERSONATE_BROWSER = "chrome131"

COMMON_HEADERS = {
    "accept": "application/json",
    "accept-language": "en-US,en;q=0.9",
    "content-type": "application/json",
    "origin": OPENAI_AUTH_BASE,
    "user-agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
}

NAVIGATE_HEADERS = {
    "accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
    "user-agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
    "upgrade-insecure-requests": "1",
}

# =================== 工具函数 ===================

def create_session():
    session = curl_requests.Session(impersonate=IMPERSONATE_BROWSER)
    if PROXY:
        session.proxies = {"http": PROXY, "https": PROXY}
    return session

def generate_device_id():
    return str(uuid.uuid4())

def generate_pkce():
    code_verifier = base64.urlsafe_b64encode(secrets.token_bytes(64)).rstrip(b"=").decode("ascii")
    digest = hashlib.sha256(code_verifier.encode("ascii")).digest()
    code_challenge = base64.urlsafe_b64encode(digest).rstrip(b"=").decode("ascii")
    return code_verifier, code_challenge

def generate_datadog_trace():
    trace_id = str(random.getrandbits(64))
    parent_id = str(random.getrandbits(64))
    return {
        "traceparent": f"00-0000000000000000{format(int(trace_id), '016x')}-{format(int(parent_id), '016x')}-01",
        "tracestate": "dd=s:1;o:rum",
        "x-datadog-origin": "rum",
        "x-datadog-parent-id": parent_id,
        "x-datadog-sampling-priority": "1",
        "x-datadog-trace-id": trace_id,
    }

# =================== Sentinel Token 逆向生成 ===================

class SentinelTokenGenerator:
    MAX_ATTEMPTS = 500000
    ERROR_PREFIX = "wQ8Lk5FbGpA2NcR9dShT6gYjU7VxZ4D"

    def __init__(self, device_id=None):
        self.device_id = device_id or str(uuid.uuid4())
        self.requirements_seed = str(random.random())
        self.sid = str(uuid.uuid4())

    @staticmethod
    def _fnv1a_32(text):
        h = 2166136261
        for ch in text:
            h ^= ord(ch)
            h = ((h * 16777619) & 0xFFFFFFFF)
        h ^= (h >> 16)
        h = ((h * 2246822507) & 0xFFFFFFFF)
        h ^= (h >> 13)
        h = ((h * 3266489909) & 0xFFFFFFFF)
        h ^= (h >> 16)
        return format(h & 0xFFFFFFFF, '08x')

    def _get_config(self):
        screen_info = "1920x1080"
        now = datetime.now(timezone.utc)
        date_str = now.strftime("%a %b %d %Y %H:%M:%S GMT+0000 (Coordinated Universal Time)")
        return [
            screen_info, date_str, 4294705152, random.random(), 
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
            "https://sentinel.openai.com/sentinel/20260124ceb8/sdk.js", None, None,
            "en-US", "en-US,en", random.random(), "vendor-undefined", "location",
            "Object", random.uniform(1000, 50000), self.sid, "", 8, time.time() * 1000
        ]

    def _base64_encode(self, data):
        json_str = json.dumps(data, separators=(',', ':'), ensure_ascii=False)
        return base64.b64encode(json_str.encode('utf-8')).decode('ascii')

    def generate_token(self, seed=None, difficulty=None):
        if seed is None:
            seed = self.requirements_seed
            difficulty = difficulty or "0"
        start_time = time.time()
        config = self._get_config()
        for i in range(self.MAX_ATTEMPTS):
            config[3] = i
            config[9] = round((time.time() - start_time) * 1000)
            data = self._base64_encode(config)
            hash_hex = self._fnv1a_32(seed + data)
            if hash_hex[:len(difficulty)] <= difficulty:
                return "gAAAAAB" + data + "~S"
        return "gAAAAAB" + self.ERROR_PREFIX + self._base64_encode(str(None))

    def generate_requirements_token(self):
        config = self._get_config()
        config[3] = 1
        config[9] = round(random.uniform(5, 50))
        return "gAAAAAC" + self._base64_encode(config)

def fetch_sentinel_challenge(session, device_id, flow="authorize_continue"):
    gen = SentinelTokenGenerator(device_id=device_id)
    req_body = {"p": gen.generate_requirements_token(), "id": device_id, "flow": flow}
    headers = {
        "Content-Type": "text/plain;charset=UTF-8",
        "Referer": "https://sentinel.openai.com/backend-api/sentinel/frame.html",
        "Origin": "https://sentinel.openai.com",
    }
    try:
        resp = session.post("https://sentinel.openai.com/backend-api/sentinel/req",
                            data=json.dumps(req_body), headers=headers, timeout=15)
        if resp.status_code == 200: return resp.json()
    except Exception: pass
    return None

def build_sentinel_token(session, device_id, flow="authorize_continue"):
    challenge = fetch_sentinel_challenge(session, device_id, flow)
    if not challenge: return None
    c_value = challenge.get("token", "")
    pow_data = challenge.get("proofofwork", {})
    gen = SentinelTokenGenerator(device_id=device_id)
    p_value = gen.generate_token(seed=pow_data.get("seed"), difficulty=pow_data.get("difficulty", "0")) \
              if pow_data.get("required") else gen.generate_requirements_token()
    return json.dumps({"p": p_value, "t": "", "c": c_value, "id": device_id, "flow": flow})

# =================== DuckMail 邮件处理 ===================

def get_duckmail_token(email, password):
    session = create_session()
    try:
        res = session.post(f"{DUCKMAIL_API_BASE}/token", json={"address": email, "password": password}, timeout=15)
        if res.status_code == 200: return res.json().get("token")
    except Exception: pass
    return None

def fetch_duckmail_emails(mail_token):
    session = create_session()
    try:
        res = session.get(f"{DUCKMAIL_API_BASE}/messages", headers={"Authorization": f"Bearer {mail_token}"}, timeout=15)
        if res.status_code == 200:
            data = res.json()
            return data.get("hydra:member") or data.get("member") or data.get("data") or []
    except Exception: pass
    return []

def get_duckmail_message_detail(mail_token, msg_id):
    session = create_session()
    if isinstance(msg_id, str) and msg_id.startswith("/messages/"):
        msg_id = msg_id.split("/")[-1]
    try:
        res = session.get(f"{DUCKMAIL_API_BASE}/messages/{msg_id}", headers={"Authorization": f"Bearer {mail_token}"}, timeout=15)
        if res.status_code == 200: return res.json()
    except Exception: pass
    return None

def _extract_verification_code(email_content: str):
    if not email_content: return None
    patterns = [r"Verification code:?\s*(\d{6})", r"code is\s*(\d{6})", r"验证码[:：]?\s*(\d{6})", r">\s*(\d{6})\s*<", r"(?<![#&])\b(\d{6})\b"]
    for pattern in patterns:
        matches = re.findall(pattern, email_content, re.IGNORECASE)
        for code in matches:
            if code == "177010": continue
            return code
    return None

def wait_for_otp(mail_token, timeout=120):
    start = time.time()
    while time.time() - start < timeout:
        messages = fetch_duckmail_emails(mail_token)
        if messages:
            detail = get_duckmail_message_detail(mail_token, messages[0].get("id") or messages[0].get("@id"))
            if detail:
                code = _extract_verification_code(detail.get("text") or detail.get("html") or "")
                if code: return code
        time.sleep(4)
    return None

# =================== OAuth 登录流程辅助 ===================

def _extract_code_from_url(url):
    if not url: return None
    try:
        parsed = urlparse(url)
        params = parse_qs(parsed.query)
        code = params.get("code", [None])[0]
        if code: return code
    except Exception: pass
    return None

def _follow_redirects_for_code(session, url, headers=None, depth=0):
    if depth > 10: 
        print(f"  [DEBUG] 跳转过深，停止追踪: {url}")
        return None
    
    print(f"  [DEBUG] 正在追踪 URL: {url[:100]}...")
    try:
        # 使用 allow_redirects=False 以便逐级观察
        r = session.get(url, headers=headers or NAVIGATE_HEADERS, allow_redirects=False, timeout=15)
        
        # 检查响应 URL (如果是 200)
        code = _extract_code_from_url(r.url)
        if code: return code
        
        # 检查重定向 Location
        if r.status_code in (301, 302, 303, 307, 308):
            loc = r.headers.get("Location") or r.headers.get("location")
            if not loc: return None
            
            # 捕获 code
            code = _extract_code_from_url(loc)
            if code: return code
            
            # 拼接完整路径
            next_url = loc if loc.startswith("http") else f"{OAUTH_ISSUER}{loc}"
            
            # 拦截 localhost 回调 (精确匹配 hostname)
            parsed_next = urlparse(next_url)
            if parsed_next.hostname in ("localhost", "127.0.0.1"):
                print(f"  [DEBUG] 捕获到本地回调: {next_url[:100]}")
                return _extract_code_from_url(next_url)
            
            return _follow_redirects_for_code(session, next_url, headers, depth + 1)
        
        print(f"  [DEBUG] 页面停止在: {r.status_code}, URL: {r.url[:100]}")
    except Exception as e:
        err_str = str(e)
        m = re.search(r'(https?://(?:localhost|127\.0\.0\.1)[^\s\'"]+)', err_str)
        if m: return _extract_code_from_url(m.group(1))
    return None

def _decode_auth_session_safe(session_obj):
    """安全解密 session cookie"""
    try:
        cookies_dict = session_obj.cookies.get_dict()
        val = cookies_dict.get("oai-client-auth-session")
        if not val: return None
        
        first_part = val.split(".")[0]
        pad = 4 - len(first_part) % 4
        if pad != 4: first_part += "=" * pad
        return json.loads(base64.urlsafe_b64decode(first_part).decode("utf-8"))
    except Exception as e:
        print(f"  [DEBUG] 解密 session 失败: {e}")
        return None

# =================== 登录主逻辑 ===================

def perform_login(email, password, mail_token=None):
    print(f"🔑 尝试登录: {email}")
    session = create_session()
    device_id = generate_device_id()
    session.cookies.set("oai-did", device_id, domain=".auth.openai.com")
    
    code_verifier, code_challenge = generate_pkce()
    state = secrets.token_urlsafe(32)
    auth_params = {
        "response_type": "code", "client_id": OAUTH_CLIENT_ID, "redirect_uri": OAUTH_REDIRECT_URI,
        "scope": "openid profile email offline_access", "code_challenge": code_challenge,
        "code_challenge_method": "S256", "state": state
    }
    
    # 1. 授权初始化
    try: 
        session.get(f"{OAUTH_ISSUER}/oauth/authorize?{urlencode(auth_params)}", headers=NAVIGATE_HEADERS, timeout=30)
    except Exception as e:
        print(f"  ❌ 授权初始化失败: {e}")
        return None

    # 2. 提交邮箱
    headers = dict(COMMON_HEADERS); headers["referer"] = f"{OAUTH_ISSUER}/log-in"; headers["oai-device-id"] = device_id
    headers.update(generate_datadog_trace())
    sentinel = build_sentinel_token(session, device_id, "authorize_continue")
    if sentinel: headers["openai-sentinel-token"] = sentinel
    
    try:
        resp = session.post(f"{OAUTH_ISSUER}/api/accounts/authorize/continue", 
                            json={"username": {"kind": "email", "value": email}}, headers=headers, timeout=30)
        if resp.status_code != 200:
            print(f"  ❌ 提交邮箱失败: {resp.status_code}")
            return None
    except Exception as e:
        print(f"  ❌ 提交邮箱异常: {e}")
        return None

    # 3. 提交密码
    headers["referer"] = f"{OAUTH_ISSUER}/log-in/password"; headers.update(generate_datadog_trace())
    sentinel = build_sentinel_token(session, device_id, "password_verify")
    if sentinel: headers["openai-sentinel-token"] = sentinel
    
    try:
        resp = session.post(f"{OAUTH_ISSUER}/api/accounts/password/verify", 
                            json={"password": password}, headers=headers, timeout=30)
        if resp.status_code != 200:
            print(f"  ❌ 密码验证失败: {resp.status_code}")
            return None
        data = resp.json()
        continue_url = data.get("continue_url", "")
        page_type = data.get("page", {}).get("type", "")
        print(f"  [DEBUG] 密码验证成功，当前页面类型: {page_type}")
    except Exception as e:
        print(f"  ❌ 密码验证异常: {e}")
        return None

    # 3.5. OTP 验证
    if "email" in page_type or "verification" in continue_url:
        print("  ⏳ 触发 OTP 验证，等待邮件...")
        code = wait_for_otp(mail_token or get_duckmail_token(email, password))
        if not code:
            print("  ❌ 未能获取到 OTP 验证码")
            return None
        print(f"  [DEBUG] 填入验证码: {code}")
        h_otp = dict(COMMON_HEADERS); h_otp["referer"] = f"{OAUTH_ISSUER}/email-verification"; h_otp.update(generate_datadog_trace())
        resp = session.post(f"{OAUTH_ISSUER}/api/accounts/email-otp/validate", json={"code": code}, headers=h_otp, timeout=30)
        if resp.status_code == 200:
            continue_url = resp.json().get("continue_url", continue_url)
            print(f"  [DEBUG] OTP 验证成功，新 continue_url: {continue_url[:50]}...")
        else:
            print(f"  ❌ OTP 验证失败: {resp.status_code}")
            return None

    # 4. Consent / Workspace 选择
    auth_code = None
    try:
        full_url = f"{OAUTH_ISSUER}{continue_url}" if continue_url.startswith("/") else continue_url
        print(f"  [DEBUG] 准备处理跳转链，起点: {full_url[:100]}...")
        auth_code = _follow_redirects_for_code(session, full_url)
        
        # 兜底：如果没捕获到 code，尝试处理组织选择
        if not auth_code:
            session_data = _decode_auth_session_safe(session)
            if session_data and session_data.get("workspaces"):
                ws_id = session_data["workspaces"][0]["id"]
                print(f"  [DEBUG] 检测到组织选择页面，自动选择 Workspace: {ws_id}")
                h_ws = dict(COMMON_HEADERS); h_ws["referer"] = full_url; h_ws.update(generate_datadog_trace())
                r = session.post(f"{OAUTH_ISSUER}/api/accounts/workspace/select", 
                                 json={"workspace_id": ws_id}, headers=h_ws, allow_redirects=False, timeout=30)
                
                if r.status_code in (301, 302, 303, 307, 308):
                    loc = r.headers.get("Location") or r.headers.get("location")
                    if loc:
                        auth_code = _follow_redirects_for_code(session, loc if loc.startswith("http") else f"{OAUTH_ISSUER}{loc}")
                elif r.status_code == 200:
                    ws_data = r.json()
                    ws_next = ws_data.get("continue_url", "")
                    ws_page = ws_data.get("page", {}).get("type", "")
                    print(f"  [DEBUG] Workspace 选择成功，下个页面: {ws_page}, continue_url: {ws_next}")
                    
                    if "organization" in ws_next or "organization" in ws_page:
                        ws_orgs = ws_data.get("data", {}).get("orgs", [])
                        if ws_orgs:
                            org_id = ws_orgs[0].get("id")
                            projects = ws_orgs[0].get("projects", [])
                            project_id = projects[0].get("id") if projects else None
                            body = {"org_id": org_id}
                            if project_id: body["project_id"] = project_id
                            
                            print(f"  [DEBUG] 自动选择 Organization: {org_id}")
                            r_org = session.post(f"{OAUTH_ISSUER}/api/accounts/organization/select", 
                                                 json=body, headers=h_ws, allow_redirects=False, timeout=30)
                            
                            if r_org.status_code in (301, 302, 303, 307, 308):
                                loc = r_org.headers.get("Location") or r_org.headers.get("location")
                                if loc: auth_code = _follow_redirects_for_code(session, loc if loc.startswith("http") else f"{OAUTH_ISSUER}{loc}")
                            elif r_org.status_code == 200:
                                org_next = r_org.json().get("continue_url", "")
                                if org_next: auth_code = _follow_redirects_for_code(session, org_next if org_next.startswith("http") else f"{OAUTH_ISSUER}{org_next}")
                    elif ws_next:
                        auth_code = _follow_redirects_for_code(session, ws_next if ws_next.startswith("http") else f"{OAUTH_ISSUER}{ws_next}")
    except Exception as e:
        print(f"  ⚠️ 处理跳转链异常: {e}")

    if not auth_code:
        print("  ❌ 无法捕获 Authorization Code")
        return None

    # 5. 换取 Token
    print(f"  [DEBUG] 正在使用 Code 换取 Token (Code 长度: {len(auth_code)})")
    try:
        resp = session.post(f"{OAUTH_ISSUER}/oauth/token", 
                            data={"grant_type": "authorization_code", "code": auth_code, "redirect_uri": OAUTH_REDIRECT_URI, "client_id": OAUTH_CLIENT_ID, "code_verifier": code_verifier}, 
                            timeout=30)
        if resp.status_code == 200:
            print("  ✅ Token 获取成功")
            return resp.json()
        else:
            print(f"  ❌ Token 换取失败: {resp.status_code} - {resp.text[:200]}")
    except Exception as e:
        print(f"  ❌ Token 换取异常: {e}")
    return None

# =================== 上传逻辑 ===================

def upload_to_cpa(email, tokens):
    if not UPLOAD_API_URL or not UPLOAD_API_TOKEN:
        print("  ⚠️ 未配置 CPA，跳过上传")
        return False
    success = False
    try:
        access_token = tokens.get("access_token")
        payload_part = access_token.split(".")[1]
        pad = 4 - len(payload_part) % 4
        if pad != 4: payload_part += "=" * pad
        payload = json.loads(base64.urlsafe_b64decode(payload_part).decode("utf-8", "ignore"))
        
        account_id = payload.get("https://api.openai.com/auth", {}).get("chatgpt_account_id", "")
        exp = payload.get("exp", 0)
        if exp:
            exp_dt = datetime.fromtimestamp(exp, tz=timezone(timedelta(hours=8)))
            expired_str = exp_dt.strftime("%Y-%m-%dT%H:%M:%S+08:00")
        else:
            expired_str = ""
            
        token_data = {
            "type": "codex", "email": email, "expired": expired_str,
            "id_token": tokens.get("id_token", ""), "account_id": account_id,
            "access_token": access_token, "refresh_token": tokens.get("refresh_token", ""),
            "last_refresh": datetime.now(timezone(timedelta(hours=8))).strftime("%Y-%m-%dT%H:%M:%S+08:00")
        }
        
        # 打印即将上传的 JSON 内容供用户核对
        print(f"\n  [DEBUG] 准备保存并上传的 Token 数据:")
        print(json.dumps(token_data, indent=2, ensure_ascii=False))
        print("  --------------------------------------\n")
        
        filename = f"{email}.json"
        with open(filename, "w", encoding="utf-8") as f: json.dump(token_data, f, ensure_ascii=False)
        
        # 使用标准 requests 库上传，CPA 面板不需要过 TLS 指纹，完美支持 files=
        with open(filename, "rb") as f:
            files_data = {"file": (filename, f, "application/json")}
            resp = std_requests.post(UPLOAD_API_URL, files=files_data, headers={"Authorization": f"Bearer {UPLOAD_API_TOKEN}"}, verify=False, timeout=30)
            
            if resp.status_code == 200: 
                print(f"  ✅ 已成功上传: {email}")
                success = True
            else: 
                print(f"  ❌ 上传 CPA 失败: {resp.status_code} - {resp.text[:200]}")
        os.remove(filename)
    except Exception as e: print(f"  ❌ 上传异常: {e}")
    return success

# =================== 主程序 ===================

def main():
    if not os.path.exists(ACCOUNTS_FILE):
        print(f"❌ 找不到账号文件: {ACCOUNTS_FILE}")
        return

    with open(ACCOUNTS_FILE, "r", encoding="utf-8") as f:
        valid_lines = [l.strip() for l in f if l.strip() and not l.strip().startswith("#")]

    print(f"🚀 任务启动: {len(valid_lines)} 个账号")
    for line in valid_lines:
        try:
            parts = line.split("----"); email = parts[0]; password = parts[1]
            mail_token = get_duckmail_token(email, parts[2] if len(parts) > 2 else password)
            tokens = perform_login(email, password, mail_token)
            if tokens: 
                if upload_to_cpa(email, tokens):
                    with open(ACCOUNTS_FILE, "r", encoding="utf-8") as f:
                        all_lines = f.readlines()
                    with open(ACCOUNTS_FILE, "w", encoding="utf-8") as f:
                        for l in all_lines:
                            if l.strip() == line:
                                f.write(f"#{l}")
                            else:
                                f.write(l)
            time.sleep(2)
        except KeyboardInterrupt:
            print("\n🛑 用户停止运行")
            sys.exit(0)
        except Exception as e:
            print(f"❌ 账号 {email} 出错: {e}")

if __name__ == "__main__":
    main()
