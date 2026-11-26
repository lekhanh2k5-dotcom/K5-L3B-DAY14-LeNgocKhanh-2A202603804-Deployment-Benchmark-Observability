# Day 14 Lab - Mission Answers

> Mọi output dưới đây là output thật từ máy làm bài (Windows 11, Python 3.12.10, venv `.venv`), chạy ngày 26/11/2026.
> Token JWT đã được che (`eyJ***`). Header `date` được lược bớt cho gọn.

## Part 1: Localhost vs Production

### Exercise 1.1: Anti-patterns found

Trong `01-localhost-vs-production/develop/app.py`:

1. **Hardcode secret** (dòng 17–18): `OPENAI_API_KEY = "sk-hardcoded-..."` và `DATABASE_URL` chứa luôn mật khẩu `password123`. Push lên GitHub là lộ, và muốn đổi key phải sửa code rồi deploy lại.
2. **Ghi secret ra log** (dòng 34): `print(f"[DEBUG] Using key: {OPENAI_API_KEY}")`. Khi chạy thật, log in nguyên key (xem Exercise 1.2). Ai đọc được log là có key.
3. **Dùng `print()` thay vì logging** (dòng 33–38): không có mức log, không có cấu trúc, không lọc được. Code còn in nguyên câu hỏi và câu trả lời, có thể chứa dữ liệu cá nhân.
4. **Không có health check**: gọi `GET /health` thì nhận **404** (Exercise 1.2). Platform không biết agent còn sống không để restart.
5. **Bind `host="localhost"`** (dòng 51): chạy trong container thì bên ngoài không gọi vào được, vì chỉ nghe trên loopback của container. Phải bind `0.0.0.0`.
6. **Port cố định 8000** (dòng 52): Railway và Render cấp port qua biến `PORT`, cố định thì app không nhận được traffic.
7. **Bật debug và reload cứng trong code** (`DEBUG = True` dòng 21, `reload=True` dòng 53): reload theo dõi file và tốn tài nguyên. Debug có thể lộ thông tin lỗi. Không tắt được nếu không sửa code.
8. **Không xử lý shutdown**: không có lifespan hay handler SIGTERM. Khi platform tắt container thì request đang chạy bị cắt ngang.
9. **Input không kiểm tra, đi qua query string** (dòng 31): `question: str` lấy từ URL, nên câu hỏi nằm luôn trong access log (`POST /ask?question=Hello`). Không giới hạn độ dài, không chặn chuỗi rỗng.
10. **Không có xác thực**: ai biết URL cũng gọi được `/ask` và tiêu tiền LLM.

### Exercise 1.2: Chạy bản develop

Bản develop nhận `question` qua query (README, lưu ý số 3):

```text
$ curl -i -X POST "http://localhost:8000/ask?question=Hello"
HTTP/1.1 200 OK
content-type: application/json

{"answer":"Đây là câu trả lời từ AI agent (mock). Trong production, đây sẽ là response từ OpenAI/Anthropic."}

$ curl -i http://localhost:8000/health
HTTP/1.1 404 Not Found

{"detail":"Not Found"}
```

Log của server lúc đó, có in nguyên secret (anti-pattern 2):

```text
INFO:     Uvicorn running on http://localhost:8000 (Press CTRL+C to quit)
INFO:     Started reloader process [19356] using WatchFiles
[DEBUG] Got question: Hello
[DEBUG] Using key: sk-hardcoded-fake-key-never-do-this
[DEBUG] Response: Đây là câu trả lời từ AI agent (mock). ...
INFO:     127.0.0.1:63874 - "POST /ask?question=Hello HTTP/1.1" 200 OK
INFO:     127.0.0.1:63876 - "GET /health HTTP/1.1" 404 Not Found
```

**Nhận xét:** app chạy được, nhưng chưa sẵn sàng cho production. Nó lộ key trong log, không có `/health`, và chỉ nghe trên `localhost:8000`.

### Exercise 1.3: Comparison table

Chạy bản production bằng `ENVIRONMENT=staging PORT=8000 python app.py`. App đọc cấu hình từ biến môi trường, `config.py` không tự đọc file `.env`:

```text
$ curl -s -X POST http://localhost:8000/ask -H Content-Type:application/json -d '{"question":"Hello"}'
{"question":"Hello","answer":"Tôi là AI agent được deploy lên cloud. Câu hỏi của bạn đã được nhận.","model":"gpt-4o-mini"}
$ curl -s -X POST http://localhost:8000/ask -H Content-Type:application/json -d '{}'
{"detail":"question field is required"}          # 422
$ curl -s http://localhost:8000/health
{"status":"ok","uptime_seconds":1.6,"version":"1.0.0","environment":"staging","timestamp":"2026-11-26T07:12:08.921038+00:00"}
$ curl -s http://localhost:8000/ready
{"ready":true}
```

| Feature | Develop | Production | Tại sao quan trọng? |
|---------|---------|------------|---------------------|
| Config | Hardcode trong code (`DEBUG`, `MAX_TOKENS`, key) | Biến môi trường qua `config.py` (`os.getenv`, có default an toàn) | Cùng một image chạy được ở dev, staging, prod, chỉ đổi biến môi trường. Đổi cấu hình không cần sửa code hay build lại. |
| Secrets | Key và mật khẩu DB nằm trong code, còn in ra log | Đọc từ env. `validate()` báo lỗi nếu thiếu `AGENT_API_KEY` khi `ENVIRONMENT=production`. Log không có secret. | Secret không vào git. Lộ thì chỉ cần đổi trên dashboard, không phải viết lại lịch sử commit. Thiếu config quan trọng thì app dừng ngay, thay vì chạy sai. |
| Health check | Không có (`/health` → 404) | `/health` (liveness, có uptime, version) và `/ready` (readiness, 503 khi chưa sẵn sàng) | Platform dùng `/health` để biết khi nào restart container. Load balancer dùng `/ready` để không gửi traffic vào instance đang khởi động hoặc đang tắt. |
| Logging | `print()`, in cả secret | Logger theo định dạng JSON, chỉ ghi độ dài câu hỏi và câu trả lời, không ghi nội dung hay secret | Log có cấu trúc thì Loki hay Datadog lọc và đếm được theo trường (`event`, `level`). Không ghi nội dung thì không lộ dữ liệu người dùng. |
| Shutdown | Đột ngột, không có hook | `lifespan`: tắt cờ `is_ready` rồi chờ request đang chạy xong. Có handler SIGTERM (dòng 180–189). | Khi platform deploy lại hoặc scale xuống, request đang xử lý không bị cắt, `/ready` báo 503 để không nhận thêm request mới. |
| Host / Port | `localhost:8000` cố định | `HOST=0.0.0.0`, `PORT` từ env | Container và PaaS cần bind mọi interface và dùng port do platform cấp. |
| Input | Query string, không kiểm tra | JSON body, thiếu `question` thì trả **422** | Câu hỏi không lọt vào URL và access log. Input sai bị từ chối rõ ràng. |
| Reload / Debug | `reload=True` luôn bật | Chỉ bật khi `DEBUG=true` | Production không cần theo dõi file, đỡ tốn CPU và đỡ lộ thông tin debug. |

**Điều mình tự phát hiện khi chạy bản production:** log của app **không ra dạng JSON**. Server chỉ in log mặc định của uvicorn, và các dòng `agent_request` / `agent_response` không xuất hiện:

```text
WARNING:root:OPENAI_API_KEY not set — using mock LLM
INFO:     Started server process [21476]
INFO:     127.0.0.1:63881 - "POST /ask HTTP/1.1" 200 OK
INFO:     127.0.0.1:63883 - "POST /ask HTTP/1.1" 422 Unprocessable Entity
```

Nguyên nhân là thứ tự import. `app.py` import `config` trước, và `Settings().validate()` gọi `logging.warning(...)` lúc import. Lệnh này tự gắn handler mặc định cho root logger. Khi `logging.basicConfig(format=...JSON...)` chạy sau đó thì không còn tác dụng, vì root logger đã có handler. Định dạng JSON và mức INFO đều không được áp dụng, nên `logger.info(...)` bị nuốt. Có hai cách sửa: gọi `basicConfig(..., force=True)`, hoặc cấu hình logging trước khi import `config`. Ở Part 6 mình sẽ cấu hình logging trước mọi lệnh ghi log.

## Part 2: Docker

> Chạy trong WSL2 (Ubuntu 26.04) + Docker Desktop 29.9.3, build từ gốc repo như README lưu ý số 4.

### Exercise 2.1: Dockerfile questions (`02-docker/develop/Dockerfile`)

1. **Base image:** `python:3.11`, bản Python đầy đủ (Debian kèm compiler và nhiều công cụ), nên image rất nặng.
2. **Working directory:** `WORKDIR /app`. Các lệnh `COPY`, `RUN` và `CMD` sau đó đều chạy trong `/app` của container.
3. **Vì sao COPY `requirements.txt` trước:** Docker cache theo từng layer. Nếu `requirements.txt` không đổi thì layer `RUN pip install` được dùng lại, và chỉ layer `COPY app.py` phía sau phải build lại. Nếu `COPY . .` đứng trước thì sửa một dòng code cũng làm mất cache, phải cài lại toàn bộ thư viện mỗi lần build.
4. **CMD khác ENTRYPOINT thế nào:**
   - `ENTRYPOINT` là chương trình luôn chạy. Tham số của `docker run image <args>` được nối vào sau nó.
   - `CMD` là lệnh hoặc tham số mặc định, và bị thay hẳn khi bạn gõ `docker run image <lệnh khác>`.
   - Dùng dạng exec (`["python", "app.py"]`) thì process là PID 1 và nhận được SIGTERM. Dạng shell (`CMD python app.py`) chạy qua `/bin/sh`, nên SIGTERM có thể không tới được app.

### Exercise 2.2: Build và run

```text
$ docker build -f 02-docker/develop/Dockerfile -t my-agent:develop .      # 1m05s
$ docker run -d --name p2dev -p 8000:8000 my-agent:develop
$ curl -i -X POST "http://localhost:8000/ask?question=What%20is%20Docker%3F"
HTTP/1.1 200 OK
{"answer":"Container là cách đóng gói app để chạy ở mọi nơi. Build once, run anywhere!"}
$ curl -s http://localhost:8000/health
{"status":"ok","uptime_seconds":0.8,"container":true}
$ docker logs p2dev
INFO:     Uvicorn running on http://0.0.0.0:8000 (Press CTRL+C to quit)
INFO:     172.17.0.1:59726 - "POST /ask?question=What%20is%20Docker%3F HTTP/1.1" 200 OK
INFO:     172.17.0.1:59738 - "GET /health HTTP/1.1" 200 OK
```

### Exercise 2.3: Multi-stage build và kích thước image

- **Stage 1 (`builder`):** `python:3.11-slim`, cài `gcc` và `libpq-dev`, rồi `pip install --user` vào `/root/.local`. Stage này chỉ dùng để build, không đem đi deploy.
- **Stage 2 (`runtime`):** một bản `python:3.11-slim` sạch. Stage này tạo user `appuser` không phải root, chỉ copy `/root/.local` (thư viện đã cài) cùng `main.py` và `utils/`, có `HEALTHCHECK`, rồi chạy `uvicorn --workers 2`.
- **Vì sao nhỏ hơn:** image cuối không có `gcc`, header, cache apt hay pip. Nó dùng bản slim thay vì bản đầy đủ, và chỉ chứa thứ cần để chạy. `docker history` cho thấy layer thư viện chỉ có **40,8 MB**, còn lại là base slim.

```text
$ docker images my-agent
IMAGE               ID             DISK USAGE   CONTENT SIZE
my-agent:advanced   98914214bc78        240MB         57.4MB
my-agent:develop    b4a3b144d7e6       1.67GB          426MB
$ docker image inspect my-agent:develop my-agent:advanced --format "{{.RepoTags}} {{.Size}}"
[my-agent:develop] 1667779861
[my-agent:advanced] 239811246
```

- Develop: **1.667,8 MB** (1,67 GB)
- Production: **239,8 MB**
- Chênh lệch: (1667779861 − 239811246) / 1667779861 = **85,6% nhỏ hơn**, tức nhỏ khoảng 6,95 lần.

### Exercise 2.4: Docker Compose stack

Lệnh chạy: `docker compose -p k5-day14-docker up -d --build` trong `02-docker/production/`, sau khi `touch .env.local`.

```text
           :80 / :443 (cổng mở ra ngoài, chỉ Nginx)
                  │
           ┌──────▼──────┐   limit_req 10 r/s, burst 20 → 429
           │    nginx    │   security headers, ẩn version
           └──────┬──────┘
                  │ proxy_pass http://agent_backend (agent:8000)
           ┌──────▼──────┐
           │    agent    │  (không mở cổng ra host, chỉ trong mạng "internal")
           └──┬───────┬──┘
   REDIS_URL  │       │  QDRANT_URL
       ┌──────▼─┐   ┌─▼────────┐
       │ redis  │   │  qdrant  │   (volume redis_data, qdrant_data)
       └────────┘   └──────────┘
```

- Có 4 service được bật: `redis` và `qdrant` lên trước. Khi cả hai báo healthy, `agent` mới khởi động (`depends_on: condition: service_healthy`), sau đó tới `nginx`.
- Các service nói chuyện qua network bridge `internal`, gọi nhau bằng tên service nhờ DNS của Docker (`agent:8000`, `redis:6379`, `qdrant:6333`). Chỉ Nginx mở cổng ra ngoài.

```text
SERVICE   IMAGE                   STATUS                            PORTS
agent     k5-day14-docker-agent   Up 2 seconds (health: starting)   8000/tcp
nginx     nginx:alpine            Up 2 seconds                      0.0.0.0:80->80/tcp, 0.0.0.0:443->443/tcp
qdrant    qdrant/qdrant:v1.9.0    Up 13 seconds (healthy)           6333-6334/tcp
redis     redis:7-alpine          Up 13 seconds (healthy)           6379/tcp

$ curl -i http://localhost/health
HTTP/1.1 200 OK
Server: nginx
X-Frame-Options: DENY
X-Content-Type-Options: nosniff
{"status":"ok","uptime_seconds":0.6,"version":"2.0.0","timestamp":"2026-11-26T07:43:22.664798"}

$ curl -i -X POST http://localhost/ask -H "Content-Type: application/json" -d '{"question": "Explain microservices"}'
HTTP/1.1 200 OK
Server: nginx
{"answer":"Agent đang hoạt động tốt! (mock response) Hỏi thêm câu hỏi đi nhé."}
```

Header `Server: nginx` và các security header cho thấy request đã đi qua Nginx.

**Điểm lệch mình thấy khi chạy:** comment đầu file nói agent chạy "2 replicas", nhưng file không khai báo `deploy.replicas`, nên chỉ có **1** container agent. `main.py` cũng không dùng `REDIS_URL` hay `QDRANT_URL`: Redis và Qdrant được bật nhưng chưa được agent dùng tới.

## Part 3: Cloud Deployment

### Exercise 3.1: Railway deployment

> Chờ đăng nhập Railway (`railway login`). URL sẽ được điền ở đây và trong `DEPLOYMENT.md`.

### Nền tảng còn lại: so sánh `railway.toml` với `render.yaml` (`06-lab-complete/`)

| | `railway.toml` | `render.yaml` |
|---|---|---|
| Định dạng | TOML, chỉ mô tả **một** service | YAML Blueprint, mô tả **nhiều** service một lúc (agent + Key Value) |
| Cách build | `builder = "DOCKERFILE"` | `runtime: docker`, `dockerfilePath`, `rootDir: 06-lab-complete` |
| Health check | `healthcheckPath = "/health"`, `healthcheckTimeout = 60` | `healthCheckPath: /health` |
| Redis | Không khai báo trong file. Phải tạo Redis riêng trong project rồi đặt `REDIS_URL` | Khai báo luôn service `type: keyvalue`, và `REDIS_URL` lấy bằng `fromService.property: connectionString` |
| Secret | Không nằm trong file, đặt bằng `railway variables` hoặc dashboard | `AGENT_API_KEY: generateValue: true` (Render tự sinh). Không ghi giá trị vào repo |
| Restart | `restartPolicyType = "ON_FAILURE"`, tối đa 3 lần | Render tự restart khi health check fail |
| PORT | Railway cấp `PORT`, `CMD` của Dockerfile đọc `${PORT:-8000}` | Giống Railway |

**Vì sao khác nhau:** Railway coi file config là phần cài đặt **build và deploy** của một service, còn hạ tầng (Redis, biến môi trường) quản lý trên dashboard. Render Blueprint là **hạ tầng dạng code** cho cả hệ thống, nên một file tạo được cả web service, Redis và cách nối hai service với nhau. Chính vì vậy, với Render phải tự khai báo Redis (README lưu ý số 8), còn Railway thì thêm Redis bằng dashboard.

### Exercise 3.3: Cloud Run CI/CD (`03-cloud-deployment/production-cloud-run/`)

`cloudbuild.yaml` chạy 4 bước nối tiếp nhau, mỗi bước chờ bước trước qua `waitFor`:

1. **test:** trong `python:3.11-slim`, cài requirements rồi chạy `pytest tests/`. Test fail thì pipeline dừng, không build.
2. **build:** `docker build` với 2 tag là `:$COMMIT_SHA` và `:latest`, dùng `--cache-from :latest` để tận dụng layer cũ.
3. **push:** đẩy cả 2 tag lên Container Registry `gcr.io/$PROJECT_ID/ai-agent`.
4. **deploy:** `gcloud run deploy` image theo đúng `$COMMIT_SHA` (không dùng `latest`, nên deploy lại hay rollback đều đúng phiên bản) ở `asia-southeast1`. Cấu hình kèm theo:
   - Scale từ 1 đến 10 instance (1 instance tối thiểu để tránh cold start).
   - Mỗi instance 512Mi RAM và 1 CPU.
   - Secret lấy từ Secret Manager (`--set-secrets`).

`service.yaml` mô tả cùng service đó theo dạng khai báo Knative:
- Mỗi instance nhận tối đa 80 request đồng thời (`containerConcurrency: 80`).
- `livenessProbe` gọi `/health`, `startupProbe` gọi `/ready`.
- `AGENT_API_KEY` lấy từ secret, không ghi giá trị vào file.

## Part 4: API Security

### Exercise 4.1: API Key authentication (`04-api-gateway/develop`)

- **Key được kiểm tra ở đâu:** trong dependency `verify_api_key` (dòng 39–54). Hàm này đọc header `X-API-Key` qua `APIKeyHeader(name="X-API-Key", auto_error=False)` (dòng 36), và được gắn vào `/ask` bằng `Depends(verify_api_key)` (dòng 70). `/` và `/health` để public.
- **Sai key thì sao:** thiếu header thì trả **401** "Missing API key". Có header nhưng sai thì trả **403** "Invalid API key". Request bị chặn trước khi gọi LLM.
- **Rotate key thế nào:** key đọc từ biến môi trường `AGENT_API_KEY` (dòng 35). Muốn đổi key thì đặt giá trị mới trên platform rồi restart hoặc deploy lại, không sửa code. Code chỉ nhận **một** key, nên lúc đổi thì client cũ bị từ chối ngay. Muốn đổi không gián đoạn thì phải cho phép hai key (cũ và mới) trong một khoảng thời gian, ví dụ `AGENT_API_KEYS=old,new`, rồi bỏ key cũ.
- **Điểm yếu thấy được:**
  - Có key mặc định `"demo-key-change-in-production"` khi thiếu env.
  - Lúc khởi động, app in key ra màn hình (dòng 91).
  - So sánh bằng `!=` chứ không dùng `hmac.compare_digest`, nên về lý thuyết có thể bị tấn công đo thời gian (timing attack).

Bật server bằng `AGENT_API_KEY=secret-key-123 python app.py`:

```text
# 1) Không có key
$ curl -i -X POST http://localhost:8000/ask -H "Content-Type: application/json" -d '{"question": "Hello"}'
HTTP/1.1 401 Unauthorized
content-type: application/json

{"detail":"Missing API key. Include header: X-API-Key: <your-key>"}

# 2) Sai key
$ curl -i -X POST http://localhost:8000/ask -H "X-API-Key: wrong-key" -H "Content-Type: application/json" -d '{"question": "Hello"}'
HTTP/1.1 403 Forbidden
content-type: application/json

{"detail":"Invalid API key."}

# 3) Đúng key
$ curl -i -X POST http://localhost:8000/ask -H "X-API-Key: secret-key-123" -H "Content-Type: application/json" -d '{"question": "Hello"}'
HTTP/1.1 200 OK
content-type: application/json

{"question":"Hello","answer":"Đây là câu trả lời từ AI agent (mock). Trong production, đây sẽ là response từ OpenAI/Anthropic."}
```

Ghi chú cho Part 6: script chấm yêu cầu **thiếu hoặc sai key đều trả 401**, khác bản mẫu này (sai key trả 403).

### Exercise 4.2: JWT authentication (`04-api-gateway/production`)

Luồng JWT trong `auth.py`:

1. `POST /auth/token` nhận username và password. `authenticate_user` so với `DEMO_USERS`, sai thì trả **401**.
2. `create_token` ký token HS256 bằng `JWT_SECRET`. Payload có `sub` (username), `role`, `iat` và `exp` (60 phút).
3. Client gửi `Authorization: Bearer <token>`. `verify_token` giải mã và kiểm tra chữ ký cùng hạn dùng:
   - Thiếu token: **401**.
   - Token hết hạn: **401**.
   - Token sai chữ ký hoặc sai định dạng: **403**.
4. Server lấy `username` và `role` ngay trong token, không cần tra database ở mỗi request (stateless). Nhờ vậy chạy nhiều instance được, miễn là các instance dùng chung `JWT_SECRET`.

Điểm cần sửa trước khi dùng thật:
- `JWT_SECRET` có giá trị mặc định nằm trong code (dòng 22).
- Mật khẩu demo lưu dạng plaintext.
- Token không thu hồi được trước khi hết hạn.

```text
# 4.2a) Lấy token
$ curl -i -X POST http://localhost:8000/auth/token -H "Content-Type: application/json" -d '{"username":"student","password":"demo123"}'
HTTP/1.1 200 OK
content-type: application/json
x-content-type-options: nosniff
x-frame-options: DENY
x-xss-protection: 1; mode=block
referrer-policy: strict-origin-when-cross-origin

{"access_token":"eyJ***(đã che)***","token_type":"bearer","expires_in_minutes":60,"hint":"Include in header: Authorization: Bearer eyJ***"}

# 4.2b) Sai mật khẩu
HTTP/1.1 401 Unauthorized
{"detail":"Invalid credentials"}

# 4.2c) /ask không có token
HTTP/1.1 401 Unauthorized
{"detail":"Authentication required. Include: Authorization: Bearer <token>"}

# 4.2d) /ask với token giả
HTTP/1.1 403 Forbidden
{"detail":"Invalid token."}

# 4.2e) /ask có token hợp lệ
$ curl -i -X POST http://localhost:8000/ask -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" -d '{"question":"Explain JWT"}'
HTTP/1.1 200 OK

{"question":"Explain JWT","answer":"Tôi là AI agent được deploy lên cloud. Câu hỏi của bạn đã được nhận.","usage":{"requests_remaining":9,"budget_remaining_usd":1.9e-05}}
```

### Exercise 4.3: Rate limiting

- **Thuật toán:** sliding window. Mỗi user có một `deque` lưu thời điểm các request. Mỗi lần kiểm tra, code bỏ các mốc cũ hơn 60 giây rồi đếm số còn lại. Docstring gọi là "Sliding Window Counter", nhưng code lưu từng timestamp nên đúng ra là **sliding window log**. Cách này chính xác, nhưng tốn bộ nhớ theo số request.
- **Giới hạn:** user (`student`) được **10 request/60 giây**. Admin (`teacher`) được **100 request/60 giây** (`rate_limiter.py` dòng 86–87).
- **Bypass cho admin:** `app.py` dòng 141 chọn limiter theo `role` trong JWT. `role == "admin"` thì dùng `rate_limiter_admin`. Admin không được bỏ hẳn giới hạn, chỉ được mức cao hơn. Role nằm trong token đã ký, nên user không tự nâng role được.
- **Khi vượt giới hạn:** trả **429**, kèm header `Retry-After`, `X-RateLimit-Limit` và `X-RateLimit-Remaining: 0`.

Mình gọi liên tục 20 lần bằng token `student`. Request ở 4.2e đã tính là lần thứ 1 trong cửa sổ 60 giây, nên lần **Test 10** là request thứ 11 và bị chặn:

```text
Test 1 -> 200  {"question":"Test 1",...,"usage":{"requests_remaining":8,...}}
Test 2 -> 200  ...requests_remaining":7
Test 3 -> 200
Test 4 -> 200
Test 5 -> 200
Test 6 -> 200
Test 7 -> 200  ...requests_remaining":2
Test 8 -> 200
Test 9 -> 200
Test 10 -> 429  {"detail":{"error":"Rate limit exceeded","limit":10,"window_seconds":60,"retry_after_seconds":56}}
Test 11 -> 429  {"detail":{"error":"Rate limit exceeded","limit":10,"window_seconds":60,"retry_after_seconds":55}}
...
Test 20 -> 429  {"detail":{"error":"Rate limit exceeded","limit":10,"window_seconds":60,"retry_after_seconds":52}}
```

Response 429 đầy đủ:

```text
HTTP/1.1 429 Too Many Requests
x-ratelimit-limit: 10
x-ratelimit-remaining: 0
x-ratelimit-reset: 1795677252
retry-after: 52
content-type: application/json

{"detail":{"error":"Rate limit exceeded","limit":10,"window_seconds":60,"retry_after_seconds":52}}
```

Cùng lúc đó, tài khoản admin `teacher` gửi 20 request thì cả 20 đều được trả 200:

```text
200 200 200 200 200 200 200 200 200 200 200 200 200 200 200 200 200 200 200 200
```

**Hạn chế:** bộ đếm nằm trong RAM của một process. Chạy 3 instance thì mỗi instance đếm riêng, user thực tế gửi được gấp 3 lần giới hạn. Restart thì bộ đếm mất. Vì vậy Part 6 chuyển rate limit sang Redis (sorted set: `ZREMRANGEBYSCORE` → `ZCARD` → `ZADD` → `EXPIRE`).

**Hai lỗi nhỏ thấy được khi chạy:**
- Middleware `security_headers` định xoá header `server`, nhưng response 200 vẫn có `server: uvicorn`. Lý do là uvicorn thêm header này sau khi middleware của app đã chạy xong.
- Trường `usage.budget_remaining_usd` (`app.py` dòng 160) đang trả `usage.total_cost_usd`, tức số tiền **đã dùng** (`1.9e-05`), không phải số tiền còn lại.

### Exercise 4.4: Cost guard

**Cách `cost_guard.py` hoạt động:**
- `check_budget(user)` chạy **trước** khi gọi LLM. Nếu tổng chi phí cả hệ thống ≥ $10/ngày thì trả **503**. Nếu chi phí của user ≥ $1/ngày thì trả **402**. Từ 80% ngân sách trở lên thì ghi cảnh báo vào log.
- `record_usage(...)` chạy **sau** khi gọi LLM. Hàm cộng số token vào và tính tiền theo giá gpt-4o-mini ($0,15/1M token đầu vào, $0,60/1M token đầu ra).

Số đo sau loạt request ở trên (`GET /me/usage`):

```text
{"user_id":"student","date":"2026-11-26","requests":10,"input_tokens":40,"output_tokens":300,"cost_usd":0.000186,"budget_usd":1.0,"budget_remaining_usd":0.999814,"budget_used_pct":0.0}
```

Kiểm tra tay: 40/1000 × 0,00015 + 300/1000 × 0,0006 = 0,000006 + 0,00018 = **$0,000186**, khớp với kết quả. Mỗi request tốn khoảng $0,0000186, nên phải chạy khoảng **53.763 request** mới hết $1. Trong khi đó rate limit chỉ cho tối đa 10 × 60 × 24 = **14.400 request/ngày**. Với mock này, rate limit sẽ chặn trước cost guard. Cost guard chỉ có tác dụng khi câu trả lời dài hoặc model đắt.

**Hạn chế của bản mẫu:**
- Dữ liệu nằm trong RAM: restart là mất, nhiều instance không dùng chung được.
- Bước kiểm tra và bước ghi tách rời, nên nhiều request đồng thời có thể cùng qua kiểm tra rồi vượt ngân sách.

**Cách mình implement theo đề Exercise 4.4** ($10/tháng mỗi user, lưu trong Redis, reset đầu tháng):

```python
from datetime import datetime, timezone

MONTHLY_BUDGET_USD = 10.0

def check_budget(user_id: str, estimated_cost: float) -> bool:
    """True nếu còn budget (và giữ chỗ luôn khoản này), False nếu vượt."""
    month = datetime.now(timezone.utc).strftime("%Y-%m")     # reset theo tháng UTC
    key = f"budget:{user_id}:{month}"
    new_total = r.incrbyfloat(key, estimated_cost)            # cộng nguyên tử, không bị race
    r.expire(key, 32 * 24 * 3600)                             # key tự hết hạn sau tháng
    if new_total > MONTHLY_BUDGET_USD:
        r.incrbyfloat(key, -estimated_cost)                   # trả lại phần vừa giữ chỗ
        return False
    return True
```

Khác lời giải mẫu ở hai điểm:
- **Cộng trước, kiểm tra sau.** `INCRBYFLOAT` là thao tác nguyên tử, nên hai request đồng thời không cùng đọc được số cũ. Lời giải mẫu dùng `GET` rồi mới `INCRBYFLOAT`, nên có thể vượt ngân sách khi nhiều request chạy cùng lúc.
- **Tính tháng theo UTC**, để mọi instance đổi tháng cùng một thời điểm.

Endpoint gọi hàm này trước khi gọi LLM, và trả **402** khi hàm trả `False`.

**Ở Part 6** (`06-lab-complete/app/cost_guard.py`), chi phí thật chỉ biết được **sau** khi gọi LLM, nên mình tách làm hai bước:
- `check_budget()` đọc tổng chi phí ngày và tháng (`MGET`). Chạm ngân sách thì trả **402**.
- `record_cost()` cộng chi phí vào Redis bằng `INCRBYFLOAT` trong một transaction, kèm `EXPIRE`. Key tính theo ngày và tháng UTC: `cost:daily:YYYY-MM-DD`, `cost:monthly:YYYY-MM`.

Cách này có thể vượt ngân sách tối đa bằng chi phí của những request đang chạy dở, nhưng không mất số liệu khi nhiều worker cùng ghi. Script chấm xác nhận cost guard hoạt động: "hết budget → 402".

## Part 5: Scaling & Reliability

> Chạy trong WSL2 (`os.name == "posix"`) để gửi được SIGTERM thật.

### Exercise 5.1: Health checks (`05-scaling-reliability/develop`)

`/health` (liveness) và `/ready` (readiness) đã có sẵn trong `app.py`:
- `/health` trả `status`, `uptime`, `version` và kết quả kiểm tra bộ nhớ (psutil, `degraded` khi RAM ≥ 90%).
- `/ready` trả **503** khi cờ `_is_ready` là False, tức là lúc đang khởi động hoặc đang tắt.

```text
$ curl -s localhost:8000/health
{"status":"ok","uptime_seconds":0.9,"version":"1.0.0","environment":"development","timestamp":"2026-11-26T07:44:01.743584+00:00","checks":{"memory":{"status":"ok","used_percent":12.4}}}
$ curl -s localhost:8000/ready
{"ready":true,"in_flight_requests":1}
```

**Liveness khác readiness:** liveness fail thì platform **restart** container, vì process bị treo. Readiness fail thì load balancer chỉ **ngừng gửi traffic** vào instance đó, không restart. Ví dụ: Redis chết thì nên báo not ready, chứ restart agent cũng không làm Redis sống lại. Vì vậy `/health` không được phụ thuộc Redis, còn `/ready` thì phải kiểm tra Redis (Part 6 làm đúng như vậy).

Chi tiết nhỏ: `/ready` báo `in_flight_requests: 1` khi không có request nào khác, vì middleware `track_requests` đếm luôn chính request `/ready`.

### Exercise 5.2: Graceful shutdown

Mình gửi một request mất 3 giây (mock LLM ở Part 5 có `delay=3.0`), rồi 0,58 giây sau gửi `kill -TERM` vào process:

```text
$ curl -X POST "localhost:8000/ask?question=Long%20task" &  ;  sleep 0.5 ; kill -TERM $PID
SIGTERM sent at +.578030508s
$ curl localhost:8000/health   (sau SIGTERM, trong lúc request cũ chưa xong)
 [HTTP 000](không kết nối được: server đã ngừng nhận kết nối mới)
Kết quả request đang chạy:
{"answer":"Đây là câu trả lời từ AI agent (mock). Trong production, đây sẽ là response từ OpenAI/Anthropic."}
[HTTP 200, 3.035363s]
process exit code: 0

--- server log ---
INFO:     Shutting down
INFO:     127.0.0.1:56132 - "POST /ask?question=Long%20task HTTP/1.1" 200 OK
INFO:     Waiting for application shutdown.
2026-11-26 14:44:05,019 INFO 🔄 Graceful shutdown initiated...
2026-11-26 14:44:05,020 INFO ✅ Shutdown complete
INFO:     Application shutdown complete.
INFO:     Finished server process [1546]
2026-11-26 14:44:05,020 INFO Received signal 15 — uvicorn will handle graceful shutdown
```

**Kết quả:**
- Request đang chạy vẫn hoàn thành với **200 sau 3,04 giây**.
- Sau SIGTERM, server **từ chối kết nối mới** ngay.
- Process thoát với **mã 0**.

Đúng 4 bước của graceful shutdown: ngừng nhận request mới, xử lý xong request đang chạy, dọn dẹp trong lifespan, rồi thoát.

**Điều thú vị trong log:** dòng `Received signal 15` của handler tự viết lại in ra **cuối cùng**, sau `Finished server process`. Uvicorn tạm thay các signal handler trong lúc chạy, xử lý SIGTERM trước (gọi graceful shutdown), xong mới gọi lại handler gốc. Vì vậy ở Part 6 mình không tự đăng ký handler SIGTERM, mà dọn dẹp trong `lifespan`. Tự đăng ký mà không gọi lại handler của uvicorn thì process sẽ không bao giờ tắt (README Part 6 có cảnh báo).

### Exercise 5.3: Stateless design (`05-scaling-reliability/production/app.py`)

Session lưu trong Redis: `save_session` dùng `SETEX session:{id}` với TTL 3600 giây, `load_session` dùng `GET`. History nằm trong chính session đó. Mỗi response trả về `served_by` (`INSTANCE_ID`) để thấy request đi tới instance nào.

Code vẫn còn đường lùi `_memory_store` khi không kết nối được Redis. Trong production, đường lùi này nguy hiểm, vì mỗi instance sẽ có một bản history khác nhau. Không có Redis thì nên báo `/ready` 503, thay vì âm thầm chuyển sang lưu trong RAM.

**Vì sao state trong RAM hỏng khi scale:** mỗi instance có bộ nhớ riêng. Câu 1 tới instance A thì history nằm ở A. Câu 2 bị load balancer gửi sang B thì B không biết câu 1, nên mất ngữ cảnh. Instance restart hay bị scale xuống cũng làm mất hết history trong RAM.

### Exercise 5.4: Load balancing

Lệnh: `docker compose -p k5-day14-scaling up -d --build --scale agent=3`. Stack mở cổng **8080**, endpoint là `POST /chat`.

```text
NAME                       STATUS                    PORTS
k5-day14-scaling-agent-1   Up 16 seconds (healthy)   8000/tcp
k5-day14-scaling-agent-2   Up 16 seconds (healthy)   8000/tcp
k5-day14-scaling-agent-3   Up 15 seconds (healthy)   8000/tcp
k5-day14-scaling-nginx-1   Up 15 seconds             0.0.0.0:8080->80/tcp
k5-day14-scaling-redis-1   Up 27 seconds (healthy)   6379/tcp

10 request qua Nginx:
Request 1 -> instance-0df9c3 | storage: redis
Request 2 -> instance-1cffa0 | storage: redis
Request 3 -> instance-0df9c3 | storage: redis
Request 4 -> instance-b460fa | storage: redis
Request 5 -> instance-1cffa0 | storage: redis
Request 6 -> instance-0df9c3 | storage: redis
Request 7 -> instance-b460fa | storage: redis
Request 8 -> instance-1cffa0 | storage: redis
Request 9 -> instance-0df9c3 | storage: redis
Request 10 -> instance-b460fa | storage: redis

$ docker compose -p k5-day14-scaling logs agent | grep "POST /chat" | đếm theo container
      3 agent-1
      4 agent-2
      3 agent-3
```

Nginx (`upstream agent_cluster { server agent:8000; }` cùng `resolver 127.0.0.11`) phân tải theo DNS của Docker: tên `agent` trỏ tới cả 3 container. Kết quả gần như chia đều, 3 / 4 / 3. `proxy_next_upstream error timeout http_503` cho phép Nginx thử instance khác khi một instance lỗi.

### Exercise 5.5: Test stateless

```text
$ python test_stateless.py
Session ID: fe52a108-67dc-441d-a338-5ed8e84b31d9
Request 1: [instance-1cffa0]   Q: What is Docker?
Request 2: [instance-0df9c3]   Q: Why do we need containers?
Request 3: [instance-b460fa]   Q: What is Kubernetes?
Request 4: [instance-1cffa0]   Q: How does load balancing work?
Request 5: [instance-0df9c3]   Q: What is Redis used for?
Total requests: 5
Instances used: {'instance-1cffa0', 'instance-b460fa', 'instance-0df9c3'}
✅ All requests served despite different instances!
--- Conversation History ---
Total messages: 10
✅ Session history preserved across all instances via Redis!
```

`test_stateless.py` không tự tắt instance nào (README lưu ý số 7), nên mình thử thêm: tạo session, **dừng hẳn** một container, rồi gửi tiếp vào cùng session.

```text
session: e572eab3-49d3-4140-9e54-f983b96b05dd
$ docker stop k5-day14-scaling-agent-1
instance-0df9c3 turn 3 [HTTP 200]
instance-1cffa0 turn 4 [HTTP 200]
instance-0df9c3 turn 5 [HTTP 200]
$ curl localhost:8080/chat/e572eab3-.../history
count = 8   (4 câu user + 4 câu assistant, đủ cả câu gửi trước khi tắt instance)
```

**Giải thích:** 5 câu đi qua cả 3 instance mà history vẫn đủ 10 tin, vì không instance nào giữ state riêng, tất cả đọc và ghi cùng key `session:{id}` trong Redis. Sau khi tắt một instance (`b460fa` không còn xuất hiện), hai instance còn lại vẫn trả lời tiếp đúng session đó với mã 200.

## Part 6: Final Project (`06-lab-complete/`)

Output của `python check_production_ready.py`, bản đầy đủ có Docker, chạy trong WSL2:

```text
  📋 Checklist Deliverable
     ✅ Dockerfile (multi-stage, < 500 MB)
     ✅ docker-compose.yml (agent + redis)
     ✅ .dockerignore
     ✅ Health check endpoint (GET /health)
     ✅ Readiness endpoint (GET /ready)
     ✅ API Key authentication
     ✅ Rate limiting
     ✅ Cost guard
     ✅ Config từ environment variables
     ✅ Structured logging
     ✅ Graceful shutdown
     ✅ Public URL ready (Railway / Render config)
----------------------------------------------------------------
  Result: 12/12 tiêu chí đạt · 43/43 checks passed
  🎉 PASS 12/12 — PRODUCTION READY! Deploy nào!
```

Một vài số đo trong lần chạy đó:
- Image **273 MB**.
- `docker stop` mất **1,1 giây**, mã thoát 0.
- Với `RATE_LIMIT_PER_MINUTE=5`, request thứ 6 bị **429**, và restart agent rồi vẫn bị 429 (state nằm trong Redis).
- Khi Redis mất kết nối: `/ready` trả **503**, `/health` vẫn **200**.

**Các quyết định thiết kế:**

| File | Cách làm |
|---|---|
| `config.py` | Mọi biến đọc từ env (`PORT`, `ENVIRONMENT`, `AGENT_API_KEY`, `REDIS_URL`, `RATE_LIMIT_PER_MINUTE`, `DAILY_BUDGET_USD`, `MONTHLY_BUDGET_USD`, `LOG_LEVEL`). `validate()` dừng app ngay nếu `ENVIRONMENT=production` mà thiếu key. |
| `auth.py` | `APIKeyHeader("X-API-Key")`, so sánh bằng `hmac.compare_digest`. Thiếu hoặc sai key đều trả **401**. Server chưa đặt key thì từ chối tất cả (không mở cửa cho mọi người). |
| `rate_limiter.py` | Sliding window trên Redis sorted set, key là hash SHA-256 của API key (không lưu key gốc). Trong một transaction: `ZREMRANGEBYSCORE` → `ZADD` → `ZCARD` → `EXPIRE`. Ghi trước rồi mới đếm, nên hai worker không thể cùng lọt qua. Vượt giới hạn thì `ZREM` request vừa ghi và trả **429** kèm `Retry-After`. |
| `cost_guard.py` | Xem Exercise 4.4. Trả **402** khi chạm ngân sách ngày hoặc tháng. |
| `redis_client.py` | `redis.from_url` với timeout ngắn, không kết nối lúc import, nên app khởi động được khi chưa có Redis. |
| `main.py` | Log JSON (một object mỗi dòng, có `request_id`), cấu hình log **trước** khi import module khác (bài học từ Part 1). Lỗi Redis trả **503** kèm `Retry-After`. Lỗi không lường trước trả **500** với `{"detail":"Internal server error"}`, không lộ stack trace. Lifespan đặt cờ `_shutting_down` để `/ready` trả 503 khi đang tắt. |
| `Dockerfile` | 2 stage (builder tạo venv, runtime chỉ copy venv và code), `python:3.11-slim`, user `app` (uid 10001), có `HEALTHCHECK`. `CMD ["sh","-c","exec uvicorn ... --port ${PORT:-8000} --workers ${WEB_CONCURRENCY:-2} --timeout-graceful-shutdown 8"]`, trong đó `exec` giúp uvicorn là PID 1. |
| `docker-compose.yml` | agent cùng `redis:7-alpine` (healthcheck, AOF, volume). `depends_on: condition: service_healthy`. `.env` là tuỳ chọn (`required: false`). |

**Kiểm tra tay bằng `docker compose`** (key đã che):

```text
POST /ask không key                → 401 {"detail":"Missing or invalid API key. Send header: X-API-Key: <your-key>"}
POST /ask có key                   → 200, x-ratelimit-limit: 10, x-ratelimit-remaining: 9
POST /ask question rỗng            → 422 {"detail":[{"type":"string_too_short","loc":["body","question"],...}]}
POST /ask JSON hỏng                → 422 {"detail":[{"type":"json_invalid",...}]}
12 request liên tiếp (giới hạn 10) → 200 ×9, 429 ×3
docker compose stop redis:
  /health                          → 200
  /ready                           → 503 {"ready":false,"reason":"redis unreachable"}
  POST /ask                        → 503 {"detail":"Service temporarily unavailable (state store)"}, retry-after: 5
docker compose start redis → /ready → 200
```

Một dòng log của app:

```json
{"ts": "2026-11-26T07:52:13.654+00:00", "lvl": "INFO", "logger": "agent", "event": "request", "request_id": "a55cc5f94b33", "method": "POST", "path": "/ask", "status": 429, "ms": 3.8}
```

**Lỗi mình tự phát hiện và sửa:** khi dừng container Redis, `/ready` mất **8.006 ms** mới trả 503. Lý do là tên `redis` không còn phân giải được, và `socket_connect_timeout` không bao gồm thời gian tra DNS. Mình chuyển phép ping sang chạy ở một thread riêng và chỉ chờ tối đa 1,5 giây (dùng lại lượt ping đang chạy dở để không sinh thêm thread). Sau khi sửa: Redis tắt thì `/ready` trả 503 trong **1,50 giây**, Redis bật lại thì trả 200 trong 8 ms. Script chấm chạy lại vẫn **PASS 12/12**.

## AI log

| # | Hỏi / nhờ AI (Claude Code) làm gì | AI đưa ra gì | Mình tự kiểm tra thế nào |
| --: | --- | --- | --- |
| 1 | Đọc đề Day 14, chuẩn bị môi trường (fork, venv, cài thư viện) | Lệnh fork, tạo `.venv`, cài `requirements.txt`. Chạy `check_production_ready.py --static-only` trên bản khung ra 0/12. | Mở repo fork trên GitHub. Chạy `pip check` không báo lỗi. Import thử từng app mẫu. |
| 2 | Chạy Part 1 (develop và production) và ghi lại output | Script bật server, gọi curl, tắt server. Gợi ý danh sách anti-pattern. | Đối chiếu từng anti-pattern với số dòng trong `develop/app.py`. Xem log server để thấy key bị in ra và `/health` trả 404. |
| 3 | Giải thích vì sao bản production không ra log JSON | Do `logging.warning` trong `config.py` chạy trước `basicConfig` | Đọc lại thứ tự import trong `app.py` và `config.py`, và thấy log thực tế không có dòng `agent_request`. |
| 4 | Chạy Part 4 (API key, JWT, rate limit) và che token | Vòng lặp curl 20 lần, lọc che chuỗi `eyJ...` | Đếm thấy lần thứ 11 trong cửa sổ bị 429. Kiểm tra file output không còn chuỗi JWT đầy đủ. Tự tính lại chi phí $0,000186. |
| 5 | Viết hàm `check_budget` cho Exercise 4.4 | Bản dùng `INCRBYFLOAT` trước rồi trả lại nếu vượt | So với lời giải mẫu để thấy lỗi race khi đọc rồi mới ghi. Ở Part 6 chuyển sang cách kiểm tra trước, cộng sau (vì chi phí chỉ biết sau khi gọi LLM). |
| 6 | Cài WSL2 Ubuntu và Docker Desktop, chuyển dữ liệu sang ổ D, tạo venv Python 3.12 trong WSL | Lệnh cài đặt. Dùng `uv` để có Python 3.12, vì Ubuntu 26.04 đi kèm 3.14 mà pydantic 2.9.0 chưa hỗ trợ. Dùng thư mục cấu hình Docker riêng để tránh lỗi `error getting credentials` | `python -c "import os; print(os.name)"` in `posix`. `docker run hello-world` chạy được. Ổ C không còn dữ liệu Docker. |
| 7 | Chạy Part 2 và Part 5, ghi số đo | Script build image, chạy compose, gửi SIGTERM, tắt một instance | Tự tính % giảm kích thước từ số byte của `docker image inspect`. Đối chiếu `served_by` với log của từng container. |
| 8 | Viết code Part 6 theo đúng các phép kiểm tra trong `check_production_ready.py` (đọc script, không sửa) | Code `config`, `auth`, `rate_limiter`, `cost_guard`, `redis_client`, `main`, Dockerfile, compose, `railway.toml`, `render.yaml` | Chạy script chấm bản đầy đủ: PASS 12/12. Thử tay bằng `docker compose` (422, 429, Redis chết). Tự phát hiện `/ready` mất 8 giây khi Redis chết, sửa xong còn 1,5 giây, chạy lại vẫn PASS. |
| 9 | Chạy Part 7: load test, eval, sửa `KNOWLEDGE_BASE`, stack Prometheus/Grafana/Jaeger, thí nghiệm A–E | Script tự động, đọc `missing_keywords`, đo thời gian firing qua `/api/v1/alerts` và lịch sử series `ALERTS`. Chụp ảnh bằng Edge headless và Playwright | Kiểm tra không câu golden nào khác chứa keyword mới (0 regression). Phát hiện lần chạy Locust đầu có 100% lỗi do lỗi Dockerfile của đề, nên xoá kết quả đó và chạy lại. Mọi số trong `BENCHMARK_REPORT.md` lấy từ file JSON/CSV. |
