# FClashBack

FlClash 的账号与配置同步服务端。一个账号下多台设备共用一份最新配置快照，写入带版本号，旧版本写入会被拒绝而不是静默覆盖。

- 技术栈：FastAPI + SQLAlchemy 2 + SQLite / PostgreSQL
- 认证：JWT（access + refresh），密码用 bcrypt 存哈希
- 同步单元：不透明二进制快照（客户端决定内容，服务端只存字节）
- 并发模型：`base_revision` 乐观锁；冲突返回 409 并带上当前版本号
- 历史：保留最近 N 个版本，可回滚
- 订阅台账：结构化的机场记录（官网、机场账号、到期、流量），供 Web 控制台管理

## 本地运行

```bash
python -m venv .venv
.venv/Scripts/activate          # Linux/macOS: source .venv/bin/activate
pip install -r requirements.txt -r requirements-dev.txt

uvicorn app.main:app --reload --port 8780
```

打开 <http://127.0.0.1:8780/docs> 可以直接调接口。不配环境变量时使用 `./data/fclash.db`。

跑测试：

```bash
python -m pytest
```

## 配置

全部通过环境变量，见 `.env.example`。

| 变量 | 默认 | 说明 |
| --- | --- | --- |
| `FCLASH_JWT_SECRET` | 开发用固定值 | **上线必须改**，否则任何拿到仓库的人都能签发 token |
| `FCLASH_DATABASE_URL` | `sqlite:///<data>/fclash.db` | 生产建议 PostgreSQL：`postgresql+psycopg://user:pass@host/db` |
| `FCLASH_DATA_DIR` | `./data` | SQLite 文件所在目录 |
| `FCLASH_ACCESS_TOKEN_MINUTES` | `1440` | access token 有效期 |
| `FCLASH_REFRESH_TOKEN_DAYS` | `180` | refresh token 有效期，设备长期免登录 |
| `FCLASH_MAX_SNAPSHOT_BYTES` | `8388608` | 单次快照上限 |
| `FCLASH_HISTORY_LIMIT` | `20` | 保留的历史版本数 |
| `FCLASH_ALLOW_REGISTRATION` | `true` | 建好自己的账号后建议设为 `false` |

## 部署

### Docker

```bash
cp .env.example .env
# 编辑 .env：至少改 FCLASH_JWT_SECRET
docker compose up -d --build
```

容器只监听 `127.0.0.1:8780`，TLS 交给反向代理：

```nginx
server {
    listen 443 ssl http2;
    server_name sync.example.com;

    ssl_certificate     /etc/letsencrypt/live/sync.example.com/fullchain.pem;
    ssl_certificate_key /etc/letsencrypt/live/sync.example.com/privkey.pem;

    client_max_body_size 16m;

    location / {
        proxy_pass http://127.0.0.1:8780;
        proxy_set_header Host $host;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }
}
```

### systemd（不用 Docker）

```ini
[Unit]
Description=FClash sync server
After=network.target

[Service]
WorkingDirectory=/opt/fclash-back
EnvironmentFile=/opt/fclash-back/.env
ExecStart=/opt/fclash-back/.venv/bin/uvicorn app.main:app --host 127.0.0.1 --port 8780
Restart=always
User=fclash

[Install]
WantedBy=multi-user.target
```

```bash
systemctl enable --now fclash-sync
```

备份就是备份 `FCLASH_DATA_DIR`：

```bash
sqlite3 /data/fclash.db ".backup '/backup/fclash-$(date +%F).db'"
```

## API

前缀 `/api/v1`，除注册/登录/刷新外都需要 `Authorization: Bearer <access_token>`。

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| POST | `/auth/register` | `{username, password, device:{key,name,platform}}` → 用户、设备、token |
| POST | `/auth/login` | 同上，`device.key` 复用则不会新增设备行 |
| POST | `/auth/refresh` | `{refresh_token}` → 新 token 对 |
| GET | `/auth/me` | 当前账号 |
| GET | `/devices` | 设备列表 |
| DELETE | `/devices/{id}` | 吊销设备（该设备的 token 立即失效） |
| GET | `/sync/state` | `{revision, checksum, size, updated_at, device_id}` |
| GET | `/sync/snapshot` | 当前快照字节，响应头带 `X-Revision` / `X-Checksum` |
| PUT | `/sync/snapshot?base_revision=N` | 上传新快照；版本不匹配返回 409 |
| GET | `/sync/history` | 历史版本列表 |
| GET | `/sync/history/{revision}` | 指定版本内容 |
| POST | `/sync/restore/{revision}?base_revision=N` | 把旧版本恢复成新版本 |
| GET | `/subscriptions` | 订阅台账列表 |
| POST | `/subscriptions` | 新增订阅 `{name, url, site_url, account, password, note, enabled, expire_at, traffic_used, traffic_total}` |
| PATCH | `/subscriptions/{id}` | 只改传入的字段 |
| DELETE | `/subscriptions/{id}` | 删除订阅 |

冲突响应：

```json
{
  "detail": {
    "detail": "revision_conflict",
    "current_revision": 7,
    "current_checksum": "…"
  }
}
```

## 客户端约定

- 快照内容由客户端定义，服务端不解析。当前实现是 zip：`manifest.json` + `profiles/*.yaml` + `config.json`。
- `device.key` 在客户端首次启动时生成并持久化，登录时复用，避免设备列表膨胀。
- 客户端按 `revision` 做本地缓存：拉取后记下版本号，上传时作为 `base_revision`。
- 离线时客户端不允许改配置——这由客户端保证，服务端只负责拒绝过期写入。

## 控制台（FClashFront）

控制台是纯静态站点，构建后放进 `frontend/`，后端会在同一域名下托管它：

```bash
# 在 FClashFront 仓库
npm install && npm run build
# 产物 dist/ 整个复制到服务器
scp -r dist/* server:/opt/fclash-back/frontend/
```

`app/main.py` 会检测 `frontend/index.html`，存在就挂载静态资源并接管其余路由；不存在则保持纯 API 部署。也可以用 `FCLASH_FRONTEND_DIR` 指向别处。这样浏览器和后端同源，不需要处理 CORS。

## 运维命令

```bash
# 忘记密码时在服务器上重置（不走 HTTP，避免控制台被用来改密码）
python -m app.cli reset-password <username>
```

## 安全边界

- 快照里是代理订阅，等同于密码。**必须走 HTTPS**，别用明文 80 端口。
- 服务端不做端到端加密；如果以后要防「服务器被拖库」，在客户端加一层对称加密再把密文当快照上传即可，接口不用改。
- 注册默认开放，部署完立刻注册自己的账号，然后把 `FCLASH_ALLOW_REGISTRATION` 设为 `false`。
- 订阅台账里的机场密码需要回显给本人，因此按原样存入数据库；数据库文件等同凭据库，请限制 `FCLASH_DATA_DIR` 的权限，备份时加密。
- 没有内置限流，公网部署建议在 Nginx 上加 `limit_req`。
