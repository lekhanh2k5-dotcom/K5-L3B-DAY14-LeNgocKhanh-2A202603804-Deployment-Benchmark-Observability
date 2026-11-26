# Deployment Information

## Public URL

https://day14-agent-production-e081d384.up.railway.app

## Platform

**Railway** (gói Trial, không gắn thẻ). Project `day14-agent`, môi trường `production`, gồm 2 service:

| Service | Nguồn | Vai trò |
|---|---|---|
| `day14-agent` | Thư mục `06-lab-complete/` (`railway up`), build bằng `Dockerfile` theo `railway.toml` | Agent Part 6, nhận traffic public qua domain ở trên |
| `Redis` | Database Redis của Railway (`railway add --database redis`) | State dùng chung cho rate limit và cost guard, chỉ truy cập được qua mạng nội bộ `redis.railway.internal` |

Lệnh đã dùng (chạy trong `06-lab-complete/`):

```bash
railway login --browserless
railway init --name day14-agent
railway add --database redis
railway add --service day14-agent --variables "AGENT_API_KEY=<secret>" --variables 'REDIS_URL=${{Redis.REDIS_URL}}' ...
railway up --service day14-agent --ci        # build Dockerfile → deploy (deployment 44752edf… SUCCESS)
railway domain --service day14-agent         # tạo domain *.up.railway.app
```

`railway.toml`: `builder = "DOCKERFILE"`, `healthcheckPath = "/health"`, `restartPolicyType = "ON_FAILURE"`. Railway chỉ chuyển traffic sang bản deploy mới khi `/health` trả 200. `PORT` do Railway cấp, và `CMD` của Dockerfile đọc `${PORT:-8000}`.

## Test Commands

Đặt `BASE` là URL public, `AGENT_API_KEY` là key đã đặt trên Railway (key không ghi trong repo):

```bash
BASE=https://day14-agent-production-e081d384.up.railway.app
```

### Health Check
```bash
curl -sS -o /dev/null -w '%{http_code}\n' "$BASE/health"     # 200
curl -s "$BASE/health"
# {"status":"ok","uptime_seconds":36.4,"version":"1.0.0","environment":"production","timestamp":"2026-11-26T09:09:24.053473+00:00"}
```

### Readiness (có kết nối Redis)
```bash
curl -sS -o /dev/null -w '%{http_code}\n' "$BASE/ready"      # 200
curl -s "$BASE/ready"
# {"ready":true}
```

### API Test (with authentication)
```bash
# Không có key → 401
curl -sS -o /dev/null -w '%{http_code}\n' -X POST "$BASE/ask" -H 'Content-Type: application/json' -d '{"question":"Hello"}'
# 401

# Có key → 200
curl -sS -o /dev/null -w '%{http_code}\n' -X POST "$BASE/ask" -H 'Content-Type: application/json' -H "X-API-Key: $AGENT_API_KEY" -d '{"question":"Hello"}'
# 200

curl -s -X POST "$BASE/ask" -H 'Content-Type: application/json' -H "X-API-Key: $AGENT_API_KEY" -d '{"question":"What is deployment?"}'
# {"question":"What is deployment?","answer":"Deployment là quá trình đưa code từ máy bạn lên server để người khác dùng được.","usage":{"input_tokens":5,"output_tokens":20,"cost_usd":1.275e-05,"requests_remaining":8}}
```

Kết quả 4 lệnh tự kiểm tra của CP6, chạy lúc 2026-11-26 16:09 (GMT+7): **200 / 200 / 401 / 200**, xem `screenshots/test.png`.

Script chấm cũng xác nhận URL:

```text
$ python check_production_ready.py --public-url https://day14-agent-production-e081d384.up.railway.app
     ✅ Public URL: GET https://day14-agent-production-e081d384.up.railway.app/health → 200
```

## Environment Variables Set

Đặt trên Railway (service `day14-agent` → Variables), **không** ghi trong code hay repo:

| Biến | Giá trị | Ghi chú |
|---|---|---|
| `AGENT_API_KEY` | *(secret, 43 ký tự ngẫu nhiên, sinh bằng `secrets.token_urlsafe(32)`)* | Bắt buộc vì `ENVIRONMENT=production`, thiếu thì app không khởi động |
| `REDIS_URL` | `${{Redis.REDIS_URL}}` → `redis://default:***@redis.railway.internal:6379` | Railway tham chiếu biến của service Redis, mật khẩu không lộ ra |
| `ENVIRONMENT` | `production` | Tắt `/docs`, bật kiểm tra bắt buộc có key |
| `RATE_LIMIT_PER_MINUTE` | `10` | Đếm theo API key, lưu trong Redis |
| `DAILY_BUDGET_USD` | `1.0` | Cost guard → 402 |
| `MONTHLY_BUDGET_USD` | `10.0` | Cost guard → 402 |
| `LOG_LEVEL` | `INFO` | |
| `WEB_CONCURRENCY` | `2` | Số worker uvicorn |
| `PORT` | *(Railway tự cấp)* | |

## Screenshots

- [Deployment dashboard](screenshots/dashboard.png)
- [Service running](screenshots/running.png): deployment `SUCCESS`, `/health` và `/ready` trả kết quả, log JSON của app trên Railway
- [Test results](screenshots/test.png): 4 lệnh tự kiểm tra CP6
