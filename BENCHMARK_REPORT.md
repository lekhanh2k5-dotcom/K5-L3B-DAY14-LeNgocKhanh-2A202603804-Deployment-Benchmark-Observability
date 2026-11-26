# Benchmark & Observability Report — Day 14

> Mọi con số lấy từ file trong `reports/` (JSON của `load_test.py`, `run_eval.py`), `benchmark-results/` (CSV của Locust),
> truy vấn Prometheus và trace Jaeger lúc chạy. Không có số ước lượng.

**Họ tên:** Lê Ngọc Khánh — 2A202603804
**Ngày chạy:** 26/11/2026
**Môi trường:** Laptop Windows 11, Intel Core 5 210H (12 luồng), 16 GB RAM. Docker Desktop 29.9.3 chạy qua WSL2 (12 CPU / 7,6 GB cho Docker). Python 3.12 trong WSL2 (Ubuntu 26.04). Load generator và agent chạy chung một máy.

---

## 1. SLO của agent

| SLI | SLO | Lý do chọn ngưỡng này |
|---|---|---|
| p95 latency `/ask` | < 500 ms | Lúc không tải, `/ask` mất khoảng 200 ms (p50 196,7 ms ở concurrency 1). 500 ms chừa khoảng 2,5 lần để chịu tải, và vẫn đủ nhanh cho chat. Mình đặt theo p95 chứ không theo trung bình, vì 3% request chậm 1,5 giây bị trung bình che mất (xem 2.2). Cũng là ngưỡng mặc định của `load_test.py`. |
| Error rate `/ask` | < 2% | Mock LLM có khoảng 1% lỗi upstream, nên 2% chừa đủ biên để không báo động vô cớ. Alert `AgentHighErrorRate` (> 5% trong 1 phút) là ngưỡng **khẩn cấp**, còn 2% là mục tiêu hằng ngày. |
| Accuracy trên golden dataset | ≥ 80% (và không regression) | Đây là quality gate mặc định của `run_eval.py`. v2 đạt 91,3% trước khi sửa và 100% sau khi sửa. Mình giữ 80% làm ngưỡng chặn merge, kèm điều kiện **không có câu nào từ đúng thành sai**, vì regression là tín hiệu rõ hơn con số tổng. |

---

## 2. Benchmark hiệu năng (develop, `load_test.py`)

### 2.1 Concurrency vs latency (agent v2, 300 request mỗi mức)

| Concurrency | RPS | p50 (ms) | p95 (ms) | p99 (ms) | Error rate | SLO |
|---|---|---|---|---|---|---|
| 1 | 4,35 | 196,7 | 224,2 | 1.692,7 | 1,67% (5×503) | ✅ PASS |
| 10 | 34,83 | 198,0 | 233,8 | 1.713,4 | 0,00% | ✅ PASS |
| 50 | 81,81 | 393,2 | 632,0 | 1.773,4 | 0,33% (1×503) | ❌ FAIL (p95) |
| 100 | 50,50 | 1.051,2 | 3.680,8 | 4.254,8 | 1,67% (5×503) | ❌ FAIL (p95) |

Nguồn: `reports/load_v2_c1.json`, `load_v2_c10.json`, `load_v2_c50.json`, `load_v2_c100.json`.

**Nhận xét:** RPS **không** tăng tuyến tính theo concurrency.
- Từ 1 lên 10, RPS tăng gần đúng 8 lần (4,35 → 34,83) và p50 gần như giữ nguyên (khoảng 197 ms). Lúc này agent còn rảnh: mỗi request chủ yếu là `await asyncio.sleep` của mock LLM, nên event loop xử lý chồng lên nhau được.
- Từ 10 lên 50, RPS chỉ tăng thêm 2,3 lần (lên 81,81), còn p50 tăng gấp đôi (393 ms). Request bắt đầu phải **xếp hàng**.
- Ở 100, RPS còn **giảm** xuống 50,5, p95 lên 3,7 giây. Agent chạy 1 process uvicorn với 1 event loop, nên CPU dành cho phần đồng bộ (parse JSON, middleware, đo metrics, ghi log) bão hoà. Thêm vào đó, load generator chạy chung máy cũng tranh CPU với agent.
- Theo định luật Little: throughput = concurrency / latency. Khi latency tăng nhanh hơn concurrency thì throughput đi ngang rồi giảm. Điểm "gãy" nằm trong khoảng từ 10 tới 50 request đồng thời cho một instance, nên muốn tải cao hơn thì phải scale ngang.

### 2.2 Tail latency (300 request, concurrency 20)

| `MOCK_SLOW_RATE` | avg (ms) | p95 (ms) | p99 (ms) |
|---|---|---|---|
| 0 | 270,6 | 346,2 | 396,6 |
| 0.03 (mặc định) | 251,1 | 311,5 | 1.679,0 |
| 0.1 | 376,7 | 1.705,8 | 1.732,8 |

Nguồn: `reports/load_v2_slow_0.json`, `load_v2_slow_0.03.json`, `load_v2_slow_0.1.json`.

**Nhận xét:**
- **p99 nhạy nhất.** Chỉ cần 3% request chậm (cộng thêm 1,5 giây) là p99 nhảy từ 397 lên 1.679 ms (gấp khoảng 4,2 lần), trong khi avg gần như không đổi (270,6 → 251,1 ms, chênh lệch nằm trong độ dao động ngẫu nhiên).
- Khi tỉ lệ chậm lên 10%, tức vượt quá 5%, thì **p95** cũng vọt lên 1.706 ms. Lúc đó avg mới tăng khoảng 106 ms (lên 376,7 ms).
- **Không nên đặt SLO theo trung bình**, vì trung bình bị số đông request nhanh kéo xuống. 10% người dùng phải chờ 1,7 giây mà avg vẫn trông "ổn". SLO theo p95/p99 đo đúng trải nghiệm của nhóm người dùng tệ nhất. Mỗi người dùng gửi nhiều request, nên phần lớn người dùng sẽ gặp ít nhất một request rơi vào nhóm p99.

---

## 3. Benchmark chất lượng (develop, `eval/run_eval.py`, 23 câu)

| Chỉ số | Agent v1 | Agent v2 | Agent v2 (sau khi sửa KB) |
|---|---|---|---|
| Accuracy | 4,35% (1/23) | 91,30% (21/23) | 100% (23/23) |
| Avg tokens / câu | 57,1 | 108,7 | 118,1 |
| Tổng cost (USD) | 0,000404 | 0,000756 | 0,000829 |
| Cost / câu đúng (USD) | 0,00040395 | 0,00003599 | 0,00003605 |
| Latency p50 / p95 (ms) | 166,4 / 186,4 | 202,9 / 225,8 | 194,6 / 1.519,5 |
| Quality gate | FAIL (accuracy < 80%) | PASS (≥ 80%, 0 regression so với v1) | PASS (`--min-accuracy 1.0`, 0 regression so với v2) |

Nguồn: `reports/eval_v1.json`, `eval_v2.json`, `eval_v2_fixed.json`.

**Những câu v2 trả lời sai ban đầu và cách sửa:**

| ID | Keyword bị thiếu | Bạn đã sửa gì |
|---|---|---|
| `security-02` (JWT khác gì API key?) | `token`, `hết hạn`, `chữ ký` | Không có tài liệu nào trong KB khớp câu hỏi, nên v2 trả câu chung chung. Mình thêm vào `KNOWLEDGE_BASE` một entry với keyword `["jwt", "api key"]`, nội dung giải thích JWT là **token** tự chứa thông tin, có thời điểm **hết hạn** (`exp`) và được **ký** bằng secret, server chỉ cần kiểm tra **chữ ký**. |
| `scaling-03` (Kubernetes HPA dựa trên chỉ số nào?) | `cpu`, `memory`, `custom metrics` | Thêm entry với keyword `["kubernetes", "hpa", "autoscal"]`: HPA scale theo **CPU** và **memory** utilization, hoặc **custom metrics** (request/giây, độ dài hàng đợi). |

Trước khi thêm, mình đã kiểm tra rằng không câu nào khác trong golden dataset chứa `jwt`, `api key`, `kubernetes`, `hpa`. Nhờ vậy hai entry mới không giành mất kết quả retrieval của câu đang đúng, và eval cuối báo **0 regression**. Phần sửa cũng được chép sang `production/utils/mock_llm.py` (README lưu ý số 10). Không sửa `golden_dataset.jsonl`.

**Quality gate trong CI:** `run_eval.py` thoát với **mã 1** khi không đạt gate (accuracy thấp hơn `--min-accuracy` hoặc có regression so với `--baseline`). Mình đã thử chạy v1 với `--baseline reports/eval_v2.json` và nhận **exit code 1**. Một bước GitHub Actions chỉ cần chạy lệnh này: exit code khác 0 thì job fail, và branch protection yêu cầu job này xanh nên PR không merge được:

```yaml
# .github/workflows/eval.yml
name: quality-gate
on: [pull_request]
jobs:
  eval:
    runs-on: ubuntu-latest
    defaults: { run: { working-directory: 06-lab-complete/benchmark-observability/develop } }
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with: { python-version: "3.11" }
      - run: pip install -r requirements.txt
      - run: AGENT_VERSION=v2 MOCK_ERROR_RATE=0 python app.py & sleep 3
      - run: python eval/run_eval.py --url http://localhost:8000 --min-accuracy 0.85 --baseline reports/eval_v2.json
```

**Trade-off chất lượng, chi phí và latency giữa v1 và v2:**
- v2 tốn khoảng **1,9 lần token** mỗi câu (108,7 so với 57,1) vì prompt có thêm context, và tổng chi phí gấp khoảng 1,9 lần.
- Đổi lại, accuracy tăng từ 4,35% lên 91,3%, nên **chi phí trên mỗi câu đúng giảm khoảng 11,2 lần** (0,000404 → 0,000036 USD).
- Latency p50 tăng thêm khoảng 36 ms (retrieval cộng với prompt dài hơn), không đáng kể so với SLO 500 ms.
- Kết luận: v2 đáng tiền. So hai phiên bản bằng "cost / câu" thì v1 rẻ hơn, nhưng v1 gần như luôn trả lời sai, nên "cost / câu đúng" mới phản ánh giá trị thật.
- p95 = 1.519,5 ms của lần eval cuối là do 1 trong 23 câu rơi vào nhóm 3% bị làm chậm 1,5 giây. Với chỉ 23 mẫu, p95 thực chất là câu chậm thứ hai, nên rất nhiễu. Đây là lý do latency phải đo bằng load test (300 request) chứ không đọc từ eval.

---

## 4. Observability stack (production)

Lệnh bật stack: `docker compose -p k5-day14-observability up -d --build`. Locust headless chạy nền 30 user để tạo tải.

**Lỗi trong code đề mình phải sửa trước khi chạy được:** container agent khởi động lại liên tục với lỗi `ModuleNotFoundError: No module named 'uvicorn'`. Nguyên nhân là `production/Dockerfile` tạo user bằng `useradd -d /app`, nên `HOME=/app` và Python tìm user site ở `/app/.local`, trong khi thư viện được copy vào `/home/agent/.local`. Mình thêm `ENV PYTHONUSERBASE=/home/agent/.local`. Lần chạy Locust đầu tiên (trước khi sửa) cho ra 100% lỗi nên mình đã xoá và chạy lại. Unit test alert vẫn đạt: `promtool test rules` → `SUCCESS`.

### 4.1 Screenshot

- [x] Dashboard Grafana khi đang có tải (thấy rõ Golden Signals): `screenshots/grafana-dashboard.png`
- [x] Một trace chậm trong Jaeger (thấy span nào chiếm thời gian): `screenshots/jaeger-slow-trace.png`
- [x] Một trace lỗi trong Jaeger (có event `exception`): `screenshots/jaeger-error-trace.png`
- [x] Trang Alerts của Prometheus với ít nhất 1 alert đang **firing**: `screenshots/prometheus-alert-firing.png` (`AgentHighErrorRate`, `AgentInstanceDown` và `LLMCostBurnRateHigh` cùng firing)

**Trả lời Exercise 7.4** (số đọc từ Prometheus lúc 15:20:44, 2 instance, Locust 30 user):

1. **p95 = 295,9 ms, avg = 242,2 ms** (p50 = 178,8 ms, p99 = 1.851,6 ms). p95 và avg gần nhau, nhưng **p99 cao gấp khoảng 7,6 lần avg**. Phần lớn request nhanh và đều, chỉ một nhóm nhỏ khoảng 3% bị chậm khoảng 1,5 giây (tail latency do `MOCK_SLOW_RATE=0.03`). Nhìn avg hay p95 sẽ không thấy nhóm này.
2. **Có, chia khá đều:** `172.18.0.4` = 9,04 req/s, `172.18.0.8` = 9,31 req/s (chênh khoảng 3%). Nginx dùng round-robin qua DNS `agent` có `resolve`.
3. **Input tokens/s (1.447,7) lớn hơn output tokens/s (776,3)**, khoảng 1,9 lần, vì prompt gồm system prompt, context lấy từ retrieval (v2) và câu hỏi. Câu trả lời thì chỉ là một đoạn ngắn. Với RAG, prompt luôn dài hơn câu trả lời.
4. `curl http://localhost:8080/metrics` trả về **404 Not Found** của Nginx (`location = /metrics { return 404; }`). `/metrics` chỉ dành cho Prometheus, vốn scrape thẳng từng container trong mạng nội bộ. Mở ra ngoài sẽ lộ thông tin nội bộ (số request, chi phí, phiên bản), và người ngoài có thể gọi liên tục để làm agent tốn tài nguyên.

### 4.2 Thí nghiệm "phá hệ thống"

Tải nền: Locust 30 user, 2 instance. Thời gian tính từ lúc lệnh `docker compose up -d` (hoặc `docker pause`) chạy xong, cho tới lúc `/api/v1/alerts` báo `firing` (kiểm tra mỗi 5 giây).

| # | Thay đổi | Alert nào firing | Thời gian từ lúc đổi → firing | Panel nào phản ánh rõ nhất |
|---|---|---|---|---|
| A | `MOCK_ERROR_RATE=0.2` | `AgentHighErrorRate` (error rate đo được 21,1%) | pending sau 25 s, **firing sau 86 s** | Error rate (đỏ), Requests/s theo status code (đường 503 tăng), LLM calls theo kết quả (error) |
| B | `MOCK_SLOW_RATE=0.3` | `AgentHighLatencyP95` (p95 = 1,92 s, p99 = 1,98 s, avg chỉ 0,68 s) | pending sau 15 s, **firing sau 138 s** | Latency p50/p95/p99 (p95 và p99 vọt lên, avg tăng ít hơn nhiều), ô Latency p95 chuyển đỏ |
| C | `LLM_MODEL=mock-llm-large` | `LLMCostBurnRateHigh` (trước khi đổi: inactive, $1,997/giờ) | pending sau 25 s, **firing sau 145 s** (lấy từ lịch sử series `ALERTS`) | Cost burn rate: theo `rate[1m]` lên **$35,67/giờ**, gấp khoảng 18 lần, còn `rate[5m]` sau 150 s là $17,68/giờ. p95 tăng lên 706 ms nhưng chưa vượt 1 s |
| D | `docker pause` 1 instance | `AgentInstanceDown` | pending sau 10 s, **firing sau 41 s** | Instances up (2 → 1), Requests/s theo instance (một đường về 0) |
| E | `AGENT_VERSION=v1` | **Không có alert mới** trong 180 s. `LLMCostBurnRateHigh` vẫn hiện firing, nhưng đó là dư âm của C: `rate[5m]` giảm dần từ $17,89 xuống $7,99/giờ khi dữ liệu của model lớn trôi ra khỏi cửa sổ | — | Tokens/s giảm khoảng 44% (input 1.188,7 → 670,9; output 635,8 → 364,5). Retrieval hit ratio mất dữ liệu (v1 không retrieval). Bảng "Phiên bản đang chạy" đổi sang `v1` (2 instance) |

Ghi chú về thời gian:
- `AgentHighErrorRate` có `for: 1m`, `AgentHighLatencyP95` có `for: 2m`. Thời gian firing bằng khoảng thời gian để `rate[1m]` vượt ngưỡng (khoảng 15–25 s), cộng thời gian `for`, cộng chu kỳ đánh giá 5 s.
- `AgentInstanceDown` nhanh nhất (41 s) vì chỉ cần một lần scrape fail và `for: 30s`.

**Ngưỡng cost cần chỉnh:** ngay ở tải nền 30 user với model nhỏ, burn rate đã dao động quanh ngưỡng $2/giờ: $4,11/giờ lúc 15:20:44 (truy vấn của bài 7.4, `rate[5m]` vẫn còn chứa dữ liệu của đợt benchmark 100 user), $2,21/giờ lúc kiểm tra alert ngay sau đó, và $1,997/giờ ngay trước thí nghiệm C. Alert này đã firing từ lúc chạy benchmark scale, trước mọi thí nghiệm (xem góc trên của ảnh Alerts). Một alert lúc nào cũng firing thì sẽ bị lờ đi, nên ngưỡng phải đặt theo ngân sách và lưu lượng thật, hoặc chuyển sang alert theo tốc độ tiêu ngân sách ngày.

**Phân tích D (vì sao lỗi 504 không hiện trên dashboard):** trong lúc một instance bị pause, log Nginx ghi **31 response 504** trong 2 phút, trong khi error rate tính từ metric của agent vẫn khoảng 21,8%, đúng bằng phần lỗi do A gây ra, không thêm gì. Các request bị gửi tới instance đang pause phải chờ hết `proxy_read_timeout` (10 giây) rồi Nginx trả 504. Agent chưa bao giờ xử lý xong các request này, nên metric của agent không đếm chúng. Metric chỉ phản ánh những gì *chính service đó* nhìn thấy, vì vậy cần thêm giám sát ở tầng load balancer (metric hoặc log của Nginx) hoặc synthetic check từ bên ngoài.

Pause chứ không stop là vì Prometheus tìm target qua DNS (`dns_sd_configs`). Container bị stop sẽ biến khỏi DNS, Prometheus coi như target không còn tồn tại chứ không phải `up == 0`, nên sẽ không có alert.

**Thí nghiệm E không làm alert nào firing. Bạn sẽ phát hiện loại sự cố này trong production bằng cách nào?**

Đổi sang v1 làm accuracy giảm từ 91,3% xuống 4,35% (mục 3). Nhưng hạ tầng vẫn "khoẻ": latency, error rate và số instance đều bình thường, còn token và chi phí thậm chí **giảm**. Alert hạ tầng chỉ đo agent có trả lời hay không, không đo trả lời có đúng không. Cách phát hiện:

1. **Quality gate trước khi deploy:** chạy `run_eval.py --baseline` trong CI. Bản v1 bị chặn ngay vì exit code 1, như đã thử ở mục 3.
2. **Eval định kỳ trên production:** mỗi 15 phút gửi vài câu golden tới agent thật, đẩy accuracy thành metric (vd `agent_eval_accuracy`) và alert khi giảm dưới 80%.
3. **Metric hành vi làm tín hiệu sớm:** `agent_retrieval_total{result="miss"}` tăng hoặc hit ratio mất, `llm_tokens_total{type="input"}` giảm đột ngột khoảng 44%, bảng `agent_info` đổi version không theo lịch deploy. Alert theo kiểu "hit ratio < 50% trong 10 phút" sẽ bắt được thí nghiệm E.
4. **Tín hiệu từ người dùng:** tỉ lệ thumbs-down, hỏi lại cùng câu, chuyển sang người thật.

### 4.3 Debug bằng trace

Trace chậm nhất tìm được (lấy `trace_id` từ log có `ms` lớn nhất, xem trên Jaeger):

- `trace_id`: `b332c0a4fd0979766f2c7497ae3f4fef`
- Tổng thời gian: **2.243,7 ms** (span gốc `POST /ask`, HTTP 200)
- Span chiếm nhiều thời gian nhất: **`chat mock-llm-small`** (**1.641,8 ms, 73,2%**). Model `mock-llm-small`, 74 token input và 37 token output. Đây là LLM chậm (một request rơi vào nhóm 3% bị chậm), không phải code của agent.
- Các span khác: `agent.run` 1.732,3 ms (77,2%, bao trọn retrieval và LLM), `agent.retrieve_context` 90,2 ms (4,0%).
- Khoảng **510 ms** còn lại (từ lúc bắt đầu `POST /ask` tới lúc bắt đầu `agent.run`) là thời gian request chờ trong agent. Trace này nằm trong đợt benchmark 100 user với 1 instance bị giới hạn 0,5 CPU, nên event loop đang bận.
- Dòng log tương ứng (grep theo `trace_id`):

```json
{"ts": "2026-11-26T08:16:50.085738+00:00", "level": "INFO", "service": "observable-agent", "instance": "7241b6ef5823", "event": "llm_call", "trace_id": "b332c0a4fd0979766f2c7497ae3f4fef", "span_id": "7298e59b1a9ca5d8", "request_id": "24bc593867f8", "model": "mock-llm-small", "agent_version": "v2", "input_tokens": 74, "output_tokens": 37, "cost_usd": 3.3e-05, "llm_ms": 1641.7}
{"ts": "2026-11-26T08:16:50.086589+00:00", "level": "INFO", "service": "observable-agent", "instance": "7241b6ef5823", "event": "http_request", "trace_id": "b332c0a4fd0979766f2c7497ae3f4fef", "span_id": "7298e59b1a9ca5d8", "request_id": "24bc593867f8", "method": "POST", "route": "/ask", "status": 200, "ms": 2242.5}
```

Trace lỗi (`screenshots/jaeger-error-trace.png`):
- `trace_id`: `1b0b95a5914603d1b48c4ec234625e3d`, tổng 103,5 ms, HTTP 503.
- Span `chat mock-llm-small` (80,3 ms) có `error.type = upstream_unavailable` và event `exception` với nội dung `utils.mock_llm.LLMError: Upstream LLM error: 503 Service Unavailable (mock)`.
- Dòng log `llm_error` có cùng `trace_id`:

```json
{"ts": "2026-11-26T08:21:18.623034+00:00", "level": "INFO", "service": "observable-agent", "instance": "b23031735323", "event": "llm_error", "trace_id": "1b0b95a5914603d1b48c4ec234625e3d", "span_id": "c4bf228440808a08", "request_id": "731c599f3595", "error": "Upstream LLM error: 503 Service Unavailable (mock)"}
```

---

## 5. Benchmark scaling (production, Locust headless, 100 users, 2 phút)

| Số instance | RPS | p50 (ms) | p95 (ms) | p99 (ms) | Failures |
|---|---|---|---|---|---|
| 1 | 58,58 | 200 | 570 | 1.700 | 86 / 7.010 (1,23%) |
| 3 | 58,56 | 210 | 480 | 1.700 | 92 / 6.953 (1,32%) |

Nguồn: dòng `POST /ask` trong `benchmark-results/scale_1_stats.csv` và `scale_3_stats.csv`. Lỗi là 503 từ mock LLM (`MOCK_ERROR_RATE=0.01`).

**Giải thích kết quả:**
- **RPS gần như không đổi** (58,58 so với 58,56). Locust là hệ thống "đóng": 100 user, mỗi user chờ 0,5–2 giây (trung bình 1,25 giây) giữa hai lần gọi. Tải tối đa vì vậy chỉ khoảng 100 / (1,25 + 0,27) ≈ 66 req/s cho mọi endpoint, khớp với 64,5 req/s tổng đo được. Thêm instance không tạo thêm tải, vì **giới hạn nằm ở phía người dùng**, không phải phía agent.
- **p95 có cải thiện** (570 → 480 ms, giảm khoảng 16%). Với 1 instance (giới hạn 0,5 CPU), khoảng 60 req/s bắt đầu làm request phải xếp hàng trong event loop, như trace chậm ở 4.3 có 510 ms chờ. Chia ra 3 instance thì hàng đợi ngắn lại.
- **p50 và p99 không đổi.** p50 khoảng 200 ms chính là latency của mock LLM (khoảng 120 ms cộng jitter cộng retrieval). p99 1.700 ms là 3% request bị LLM làm chậm thêm 1,5 giây. Scale ngang **không thể** làm LLM nhanh hơn.
- **Nút thắt nằm ở LLM upstream.** Panel "LLM latency p95 theo model" gần như trùng latency của `/ask`. Muốn giảm tail latency phải xử lý phía LLM: timeout và retry hedging, cache câu trả lời, model nhanh hơn, hoặc streaming để người dùng thấy token đầu sớm.

---

## 6. Kết luận

- 3 điều mình học được về benchmark và observability:
  1. **Trung bình nói dối.** Ở 2.2, 10% request chậm làm p95 tăng khoảng 5 lần mà avg chỉ tăng 39%. SLO và alert phải đặt theo percentile, đo bằng histogram (`histogram_quantile`), và cần đủ mẫu: p95 trên 23 câu eval chỉ là nhiễu.
  2. **Metric của một service chỉ thấy những gì chính service đó xử lý.** Lỗi 504 ở Nginx (thí nghiệm D) và lỗi chất lượng (thí nghiệm E) đều không làm dashboard của agent đỏ. Cần giám sát nhiều tầng (load balancer, synthetic check) và **eval chất lượng** chạy định kỳ, không chỉ giám sát hạ tầng.
  3. **Log, trace và metric phải nối được với nhau.** Có `trace_id` trong log nên từ một dòng `llm_error` mở thẳng được trace trong Jaeger và thấy span `chat` chiếm 73% thời gian. Không có liên kết này thì chỉ biết "chậm" chứ không biết chậm ở bước nào.
- Nếu đưa agent này lên production thật, mình sẽ thêm:
  - Alert **cost burn rate theo ngưỡng phù hợp với tải thật**: ngưỡng $2/giờ hiện tại bật tắt liên tục ở tải nền 30 user (đo được $1,997–4,11/giờ), tức là đang báo động giả, nên phải chỉnh theo ngân sách.
  - **Synthetic eval** định kỳ trên production (mỗi 15 phút chạy vài câu golden), alert khi accuracy giảm, và theo dõi `agent_retrieval_total{result="miss"}`.
  - Metric và alert **5xx/504 ở Nginx**, cùng p95 đo từ phía load balancer.
  - **Error budget burn rate** nhiều cửa sổ (1 giờ / 6 giờ) thay cho ngưỡng cứng `for: 1m`.
  - Metric **thời gian chờ trong hàng đợi** (khoảng cách giữa lúc nhận request và lúc gọi LLM) để phát hiện bão hoà trước khi p95 vỡ.
