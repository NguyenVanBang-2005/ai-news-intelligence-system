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
3. Xem `GET /api/v1/articles` và `GET /api/v1/topics/trending`.

### Ingestion chỉ hỗ trợ RSS/Atom

`POST /api/v1/ingestion/run?source_id=ID` đọc `feed_url` của source đã lưu trong DB.
Endpoint không nhận URL qua request body; bỏ `source_id` sẽ chạy mọi nguồn active.
`HttpUrl` chỉ kiểm tra cú pháp URL khi tạo source, không xác nhận nội dung là feed.
Trang danh sách HTML và URL bài viết đơn lẻ không được crawl. Class
`ArticleContentExtractor` chưa được tích hợp vào ingestion.

Ví dụ tạo source bằng `POST /api/v1/sources`:

```json
{
  "name": "MIT AI RSS",
  "feed_url": "https://news.mit.edu/topic/mitartificial-intelligence2-rss.xml",
  "language": "en"
}
```

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

