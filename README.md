# AI News Intelligence API

Backend MVP cho hệ thống thu thập, phân loại, tóm tắt và theo dõi chủ đề tin AI.

## Chức năng hiện có

- Quản lý nguồn RSS.
- Thu thập bài viết và chống trùng theo URL.
- Phân loại chủ đề bằng bộ từ khóa offline.
- Tóm tắt extractive đơn giản, lưu confidence và trạng thái xử lý.
- Lọc/phân trang bài viết; thống kê các chủ đề nổi bật.
- OpenAPI tự động tại `/docs`.

## Chạy với PostgreSQL + Docker Compose

Xem [hướng dẫn database](docs/database.md) để cấu hình `.env`, chạy migration,
backup/restore và nâng cấp schema. Quick start nếu chưa có `.env`:

```powershell
Copy-Item .env.example .env
docker compose up -d --build
```

Compose gồm PostgreSQL 17, Alembic migration và API. Dữ liệu nằm trong named volume;
timestamp dùng UTC. Nếu đã có `.env` từ bản SQLite, cập nhật theo hướng dẫn trước.

## Chạy Python local (PostgreSQL chạy trong Compose)

```bash
python -m venv .venv
# Windows: .venv\Scripts\activate
# Linux/macOS: source .venv/bin/activate
pip install -r requirements-dev.txt
cp .env.example .env  # Windows có thể copy thủ công
docker compose up -d db
alembic upgrade head
uvicorn app.main:app --reload
```

Mở `http://127.0.0.1:8000/docs`. API không tự tạo bảng; schema do Alembic quản lý.
Dữ liệu SQLite cũ không tự động được import sang PostgreSQL.

### Hai cách chạy API, hai cổng khác nhau

| Cách chạy | Cổng | Swagger | Cấu hình DB |
| --- | --- | --- | --- |
| Docker Compose (`ainis_main`, `API_PORT=8001` trong `.env`) | 8001 | <http://127.0.0.1:8001/docs> | `POSTGRES_*`, migrate tự chạy |
| `uvicorn app.main:app --reload` trên host | 8000 | <http://127.0.0.1:8000/docs> | `DATABASE_URL` trong `.env` |

Hai tiến trình độc lập; chọn một cổng và dùng đúng Swagger của nó. Tiến trình trên host
không tự migrate: nếu `POST /api/v1/sources` trả `500 Internal Server Error` dù payload
hợp lệ, thường PostgreSQL chưa chạy (`docker compose up -d db`) hoặc database chưa có
bảng (`UndefinedTable: relation "sources" does not exist`). Chạy `alembic upgrade head`
với đúng `DATABASE_URL`, rồi thử lại; traceback nằm ở terminal chạy uvicorn.

## Luồng thử nhanh

1. `POST /api/v1/sources` với JSON:

```json
{
  "name": "MIT Technology Review - AI",
  "feed_url": "https://www.technologyreview.com/feed/",
  "language": "en"
}
```

2. `POST /api/v1/ingestion/run` để lấy RSS và phân tích bài mới.
3. Xem `GET /api/v1/articles` và `GET /api/v1/topics/trending`. Trending so sánh số bài
   trong `window_hours` gần nhất (mặc định 24) với mức bình thường của `baseline_days`
   ngày trước đó (mặc định 7); `trend_score` là số độ lệch chuẩn vượt mức bình thường.

### Loại nguồn: RSS/Atom và News API

`POST /api/v1/ingestion/run?source_id=ID` thu thập bài mới từ source đã lưu; bỏ `source_id`
sẽ chạy mọi nguồn active. Endpoint không nhận URL qua request body.

- `type: "rss"` (mặc định): đọc `feed_url`. `HttpUrl` chỉ kiểm tra cú pháp khi tạo source,
  không xác nhận nội dung là feed; trang HTML và URL bài viết đơn lẻ không được hỗ trợ.
- `type: "news_api"`: tìm bài theo `query` qua GNews (https://gnews.io). Cần đặt
  `NEWS_API_KEY` (gói miễn phí: tối đa 10 bài mỗi lần, khoảng 100 lần/ngày). Ví dụ:

```json
{
  "name": "Toyota news",
  "type": "news_api",
  "query": "toyota",
  "language": "en"
}
```

- Full-text: khi nguồn chỉ có đoạn trích ngắn hơn `FULL_TEXT_MIN_CHARS` (mặc định 800 ký tự),
  ingestion tải trang bài viết để lấy toàn văn; tải lỗi thì giữ đoạn trích. Tắt bằng
  `INGESTION_FULL_TEXT=false`. Bật tính năng này làm ingestion chậm hơn vì phải tải từng bài.

Ví dụ tạo source bằng `POST /api/v1/sources`:

```json
{
  "name": "MIT AI RSS",
  "feed_url": "https://news.mit.edu/topic/mitartificial-intelligence2-rss.xml",
  "language": "en"
}
```

`feed_url` phải là địa chỉ RSS/Atom của nhà xuất bản (thường kết thúc `.xml`/`/feed`/`/rss`,
hoặc lấy từ biểu tượng RSS của trang). Một URL bài viết như
`https://news.mit.edu/2026/craig-rowe-soars-to-new-heights-1001` là trang HTML: POST vẫn
trả 201 (chỉ kiểm tra cú pháp, không gọi mạng), nhưng ingestion báo `UnsupportedFeedError`
trong `errors` và không tạo bài. Sửa bằng cách tạo source mới với URL RSS đúng.

Lấy `id` trả về, gọi ingestion với ID đó. Dùng `GET /api/v1/sources` để kiểm tra
URL thực sự được lưu; nếu POST trả 409, tìm source đã tồn tại và dùng ID của nó.
Không cần xóa nguồn cũ để thử nguồn mới; xóa source sẽ xóa kèm các bài của nguồn.

HTTP 200 biểu thị batch đã trả kết quả, không bảo đảm mọi nguồn thành công.
HTML/non-feed trả `UnsupportedFeedError` trong `errors`, kèm HTTP status và
Content-Type của nguồn. Feed hợp lệ nhưng rỗng vẫn trả 0 bài và không có lỗi.
Entry thiếu title/link hợp lệ bị bỏ trước khi tăng `articles_seen`; log INFO của
`app.services.feed` ghi số entry, số được xét/nhận/bỏ. Content lấy từ feed,
không tải toàn văn URL bài. Nếu `articles_created=0` nhưng `articles_seen>0`
và `duplicates_skipped=articles_seen`, các bài đã tồn tại, không phải lỗi lấy RSS.

## Kiểm tra

```bash
ruff check .
pytest --cov=app
```

Test PostgreSQL (`tests/test_sources_regression.py`) chỉ chạy khi có máy chủ **thử**: đặt
`TEST_POSTGRES_ADMIN_URL` trỏ tới database `postgres` của máy chủ đó (ví dụ stack
`ainis_dockertest`, cổng 55432). Mỗi test tự tạo và xóa database `ainis_pytest_*` riêng,
không đụng database có sẵn; không đặt biến này trỏ vào máy chủ chính. Thiếu biến thì các
case PostgreSQL bị skip, phần SQLite vẫn chạy.

## AI API

- `POST /api/v1/ai/process` xếp một job chạy nền và trả `202` kèm `id` ngay. `409` nếu
  chưa đủ bài (`AI_MIN_DOCUMENTS`) hoặc đang có job khác chạy; `503` nếu không nạp được thư viện ML.
- `GET /api/v1/ai/process/{job_id}` trả `status` (`pending` → `running` → `succeeded` | `failed`),
  `error` khi thất bại và `result` khi thành công. `result` gồm số liệu batch,
  `confidence_method` (`hdbscan_soft` là điểm thật từ HDBSCAN; `fallback` là giá trị cố định 0.5)
  và `topic_coherence` (NPMI trung bình, -1..1, càng cao càng tốt — so sánh giữa các batch
  để biết đổi tham số có cải thiện không).
- `GET /api/v1/ai/topics` liệt kê topic: `size`, `keywords` kèm trọng số và
  `representative_articles` (bài gần tâm topic nhất).
- Embedding của bài được lưu trong bảng `articles` (cột `embedding`, khóa theo model + nội dung),
  nên chạy lại hoặc `force=true` chỉ encode bài mới hoặc bài đã đổi nội dung.
- Job chạy bằng FastAPI `BackgroundTasks` trong cùng tiến trình: không tự retry, và job bị
  gián đoạn khi server restart sẽ không chặn job mới sau `AI_JOB_TIMEOUT_SECONDS`.

## Tìm kiếm tin tức (Q&A)

Mở `http://localhost:8000/` để dùng trang tìm kiếm: nhập yêu cầu (ví dụ "EU AI Act") hoặc
dán link bài báo rồi bấm Search. API tương ứng: `POST /api/v1/ai/ask` với `{"input": "..."}`.

- Kết quả gồm danh sách bài nguồn (tiêu đề, link, nguồn, ngày, tóm tắt) và một đoạn tổng quan
  có trích dẫn `[1]`, `[2]`. Chỉ tìm trong các bài đã thu thập từ RSS.
- Link mới được tải về, lưu vào nguồn "User-submitted links" (không hoạt động, RSS bỏ qua) và
  hiển thị đầu tiên cùng các bài liên quan.
- LLM mặc định là Gemma chạy local qua Ollama (miễn phí): cài Ollama, chạy
  `ollama pull <model>` và đặt `LLM_MODEL` đúng tên model đã tải (kiểm tra bằng `ollama list`).
  Dùng OpenAI: đặt `LLM_BASE_URL=https://api.openai.com/v1`, `LLM_MODEL`, `LLM_API_KEY`.
- Tóm tắt AI được lưu vào cột `articles.ai_summary` và dùng lại. Khi LLM không chạy, hệ thống
  vẫn trả kết quả với đoạn trích (`summary_method: "extractive"`) và không có tổng quan.

## Windows: lỗi DLL khi khởi động

Nếu traceback kết thúc bằng `An Application Control policy has blocked this file`
khi import scikit-learn/BERTopic, Windows đã chặn một thư viện native (.pyd/DLL).
Kiểm tra Event Viewer → Applications and Services Logs → Microsoft → Windows →
CodeIntegrity → Operational, đặc biệt event 3077, để tìm file và policy liên quan.
Không thể kết luận thiếu DLL hoặc sai phiên bản Python chỉ từ thông báo này.

Route AI chỉ nạp thư viện ML khi gọi `POST /api/v1/ai/process`. Nếu dependency
không nạp được, route trả 503; health, sources, RSS và baseline không cần BERTopic
để khởi động. Đây là cô lập lỗi AI, không phải sửa chính sách Windows.

Để khôi phục AI, cần môi trường Python và các gói native được chính sách máy cho
phép; nhờ quản trị viên kiểm tra file/publisher và policy nếu máy được quản lý.
Không tắt App Control để khắc phục. Python 3.12 là phiên bản mục tiêu trong Dockerfile;
đổi phiên bản không bảo đảm giải quyết policy block. Sau khi môi trường được sửa:

```powershell
.\.venv\Scripts\python.exe -c "from sklearn.preprocessing import PolynomialFeatures; from bertopic import BERTopic; print('AI imports OK')"
.\.venv\Scripts\python.exe -m uvicorn app.main:app --reload
```

Kiểm thử hồi quy trên DB test tách biệt:

```powershell
$env:DATABASE_URL = 'sqlite://'
.\.venv\Scripts\python.exe -m pytest -q tests/test_ai_availability.py
Remove-Item Env:DATABASE_URL
```

## Giới hạn của baseline

Analyzer hiện là heuristic để toàn hệ thống chạy không cần API key. Giai đoạn tiếp theo có thể
thay `HeuristicAnalyzer` bằng BERTopic/embedding/LLM qua cùng interface, thêm
background worker, full-text/vector search, authentication và monitoring.

