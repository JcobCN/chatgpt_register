# ChatGPT 批量自动注册工具 (DuckMail + OAuth + Sub2Api 版)

## 项目概述

这是一个功能完整的 ChatGPT 批量自动注册工具，支持使用 DuckMail 临时邮箱进行并发注册，自动获取 OTP 验证码，并可通过 OAuth 方式自动授权上传账号 Token 到 Sub2Api 平台。

## 功能特性

- **DuckMail 临时邮箱**：自动生成临时邮箱账号，接收验证码
- **并发注册**：支持多线程并发批量注册账号
- **代理验证**：自动验证代理 IP 是否可用，支持代理池管理
- **OAuth 登录**：支持 OAuth 方式自动登录获取 Token
- **Sub2Api 上传**：注册成功后自动将 Token 上传到 Sub2Api 平台
- **Web 管理界面**：提供可视化 Web 界面查看注册进度和日志

## 项目结构

```
GPT_register+duckmail+CPA+autouploadsub2api/
├── chatgpt_register.py    # 主注册脚本（并发版）
├── server.py              # FastAPI Web 服务
├── config.json            # 配置文件
├── requirements.txt       # Python 依赖
├── stable_proxy.txt       # 稳定代理列表
├── web/                   # Web 前端
│   ├── index.html
│   ├── app.js
│   └── style.css
└── codex_tokens/          # 生成的 Token 存储目录
```

## 环境要求

- Python 3.10+
- curl_cffi >= 0.14.0
- fastapi >= 0.100.0
- uvicorn >= 0.20.0

## 快速开始

### 1. 安装依赖

```bash
cd GPT_register+duckmail+CPA+autouploadsub2api
pip install -r requirements.txt
```

### 2. 配置 config.json

```json
{
  "total_accounts": 3,
  "duckmail_api_base": "https://api.duckmail.sbs",
  "duckmail_bearer": "your-duckmail-api-key",
  "proxy": "",
  "proxy_list_url": "https://github.com/proxifly/free-proxy-list/blob/main/proxies/countries/US/data.txt",
  "proxy_validate_enabled": true,
  "stable_proxy": "http://127.0.0.1:7890",
  "prefer_stable_proxy": true,
  "output_file": "registered_accounts.txt",
  "enable_oauth": true,
  "oauth_required": true,
  "ak_file": "ak.txt",
  "rk_file": "rk.txt",
  "sub2api_base_url": "https://your-sub2api.com",
  "sub2api_bearer": "your-sub2api-token",
  "auto_upload_sub2api": false,
  "sub2api_group_ids": [2]
}
```

### 3. 配置说明

| 配置项 | 说明 |
|--------|------|
| `total_accounts` | 需要注册的账号数量 |
| `duckmail_api_base` | DuckMail API 地址 |
| `duckmail_bearer` | DuckMail API 密钥 |
| `proxy_list_url` | 代理列表 URL |
| `proxy_validate_enabled` | 是否启用代理验证 |
| `stable_proxy` | 稳定代理地址 |
| `prefer_stable_proxy` | 优先使用稳定代理 |
| `auto_upload_sub2api` | 注册成功后自动上传到 Sub2Api |
| `sub2api_group_ids` | Sub2Api 分组 ID |

### 4. 运行方式

#### 方式一：Web 界面启动（推荐）

```bash
python server.py
```

然后访问 `http://localhost:18421`

#### 方式二：直接运行注册脚本

```bash
python chatgpt_register.py
```

## 环境变量

所有配置项都支持通过环境变量覆盖：

```bash
export DUCKMAIL_BEARER="your-api-key"
export PROXY="http://proxy:port"
export TOTAL_ACCOUNTS=10
export AUTO_UPLOAD_SUB2API=true
```

## 输出文件

- `registered_accounts.txt` - 注册成功的账号信息
- `stable_proxy.txt` - 验证通过的稳定代理
- `codex_tokens/` - 生成的 Token JSON 文件

## 注意事项

1. 请确保 DuckMail API 密钥有效
2. 代理需要稳定，建议使用住宅代理
3. 注册过程请遵守 OpenAI 服务条款
4. 批量注册时注意控制频率，避免触发限制
5. Sub2Api 上传功能需要正确的 API 配置

## 端口说明

- **18421** - Web 管理服务端口

## 许可证

仅供学习和研究使用，请遵守相关服务条款。

---

**更新日期**：2026-03-19
