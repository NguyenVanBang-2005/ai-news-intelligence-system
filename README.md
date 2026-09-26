# AI News Intelligence API

Backend MVP cho hệ thống thu thập, phân loại, tóm tắt và theo dõi chủ đề tin AI.

## Chức năng hiện có

- Quản lý nguồn RSS.
- Thu thập bài viết và chống trùng theo URL.
- Phân loại chủ đề bằng bộ từ khóa offline.
- Tóm tắt extractive đơn giản, lưu confidence và trạng thái xử lý.
- Lọc/phân trang bài viết; thống kê các chủ đề nổi bật.
- OpenAPI tự động tại `/docs`.

## Chạy local

```bash
python -m venv .venv
# Windows: .venv\Scripts\activate
# Linux/macOS: source .venv/bin/activate
pip install -r requirements-dev.txt
cp .env.example .env  # Windows có thể copy thủ công
uvicorn app.main:app --reload
```

Mở `http://127.0.0.1:8000/docs`. Database SQLite được tạo ở `data/news.db`.

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

## Kiểm tra

```bash
ruff check .
pytest --cov=app
```

## Giới hạn có chủ đích của MVP

Analyzer hiện là heuristic để toàn hệ thống chạy không cần API key. Giai đoạn tiếp theo có thể
thay `HeuristicAnalyzer` bằng BERTopic/embedding/LLM qua cùng interface, thêm PostgreSQL,
background worker, full-text/vector search, authentication và monitoring.

