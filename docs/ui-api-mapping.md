# UI ↔ API mapping (Bước UI-0)

Trạng thái repo khi lập bảng: branch `main`, HEAD `a7d462a`, working tree sạch. Chưa sửa code, chưa commit, chưa copy ảnh vào repo.

Quy ước trạng thái: **CÓ SẴN** · **THIẾU TRƯỜNG** · **THIẾU ENDPOINT** · **KHÔNG CÓ DỮ LIỆU THẬT** (đề xuất bỏ) · **CẦN XÁC MINH**.
Mọi số liệu/chữ trong ảnh là dữ liệu mẫu. UI cuối viết bằng tiếng Anh.

---

## PHẦN A - Mockup (`C:\Users\Bangh\Downloads\AINIS UI-UX`)

| # | File | Dung lượng | Màn hình |
|---|------|-----------|----------|
| 1 | `Trang tìm kiếm 1.png` | 534,564 B | (1) Search hero, trạng thái rỗng (chưa tìm) |
| 2 | `Trang tìm kiếm 2.png` | 680,557 B | (2) Kết quả search + sidebar chủ đề nổi bật |
| 3 | `Chi tiết bài viết và điều hướng -.png` | 727,367 B | (3) Drawer chi tiết bài viết (overlay trên màn 2) |
| 4 | `Trang Khám Phá Chủ Đề AI -.png` | 611,719 B | (4) Chủ đề: xu hướng, cụm, outliers |
| 5 | `Quản trị nguồn và phân loại -.png` | 507,816 B | (5) Quản trị nguồn |

Đủ 5 màn dự kiến, không thiếu, không thừa. Màn 3 là overlay chứ không phải trang riêng.

### Thành phần chung (cả 5 ảnh)
- Header: logo AINIS + tagline "AI News Intelligence"; nav 3 mục (Search / Topics / Sources), mục active gạch chân xanh; avatar tròn chữ "AN".
- Hero nền xanh navy gradient.
- Footer: chữ trái, ghi chú phải ("Mockup data · No real API call" ở ảnh 1-2; "Topic model: BERTopic · HDBSCAN · c-TF-IDF" ở ảnh 4).
- Font sans hiện đại, thẻ trắng bo góc + shadow nhẹ, màu nhấn xanh dương, badge xanh lá/vàng/đỏ.

### Ảnh 1 - Search hero (rỗng)
- Badge pill "real-time updates" có chấm xanh lá.
- H1 hai dòng + subtitle.
- Ô search lớn (icon kính lúp, placeholder ví dụ, nút "Search →").
- Hàng chip "Trending:" 4 chip.
- Không có trạng thái loading/lỗi trong ảnh.

### Ảnh 2 - Kết quả search
- Hero như ảnh 1, ô search đã điền chữ.
- Thẻ "Smart summary" (icon sao): tiêu đề `Results for "<query>"`, đoạn tóm tắt, hàng chân: chấm xanh "N sources analyzed", "Updated N minutes ago", link "Read methodology".
- Tiêu đề "Related articles" + phụ đề "N best matching results"; dropdown sắp xếp ("Most relevant").
- Danh sách thẻ bài (đánh số 01/02/03): badge topic, ngày giờ, tiêu đề, đoạn trích, avatar chữ cái nguồn + tên nguồn, badge "Saved" (xanh lá) hoặc "Excerpt only" (vàng), mũi tên →.
- Sidebar phải: thẻ "Trending topics" (icon mũi tên, nhãn "24h"), 4 dòng xếp hạng (số thứ tự, tên, thanh tiến độ, "N articles", điểm "+x.xσ"), nút "View all topics →".
- Thẻ tối "AINIS Insight" (avatar "A", tagline + mô tả tĩnh).
- Không có ảnh loading/empty/error cho kết quả.

### Ảnh 3 - Drawer chi tiết bài
- Nền phía sau bị làm mờ; panel trượt từ phải.
- Header drawer: nhãn "ARTICLE DETAILS", badge "Analyzed" (chấm xanh), nút đóng (X).
- Badge topic, tiêu đề lớn, đoạn dẫn.
- Lưới metadata 2x2: Author, Source, Originally published (ngày giờ), Collected at (ngày giờ).
- Thẻ "AI analysis" ("Analyzed by AINIS"): icon sao, **Confidence 94%** + thanh tiến độ gradient, dòng Topic + giá trị (link-style), khối "Summary".
- Khối "Collected content" + badge "Feed · Full text"; 2 đoạn văn.
- Khối "Source & data history": timeline dọc 2 mốc (giờ + sự kiện + nguồn phụ).
- Footer drawer: link "Open original article" (icon external), mã mono `ainsi://article/...` bên phải.
- Không thấy trạng thái loading/lỗi (404) trong ảnh.

### Ảnh 4 - Chủ đề
- Hero căn giữa: badge "Topic discovery with BERTopic", H1, subtitle.
- Thẻ "Trend detection" / "Trends over time": phụ đề "spike vs baseline volume"; toggle segmented **7 days / 30 days**; biểu đồ vùng/đường 3 series + 1 điểm đánh dấu; trục ngày; legend phải 3 dòng (chấm màu, tên, "+x.xσ", thanh, nhãn "Spike / Rising fast / Stable").
- Tiêu đề "Featured topic clusters" + phụ đề "N clusters found by BERTopic from M articles"; dropdown "Sort: Growth".
- Lưới 2x2 thẻ cụm: số thứ tự, tên, badge σ, gạch màu, 3 chip keyword, mô tả, "N articles", link "View cluster →".
- Thẻ đường nét đứt "Unclustered / Outliers" (ô "-1", badge "TOPIC -1", mô tả "N articles below HDBSCAN density threshold, x% of data"), toggle "Show".
- Không thấy empty/loading/error.

### Ảnh 5 - Quản trị nguồn
- Hero trái: badge "Source management center", H1 "Source & Classification Management", subtitle; nút trắng "Rescan sources" (icon refresh).
- 4 thẻ thống kê (số thứ tự 01-04, nhãn, số lớn, tên trường mono, chú thích xanh): `sources_processed`, `articles_seen`, `articles_created`, `duplicates_skipped`.
- Form "Add RSS/Atom source": ô Name, ô Feed URL, select Language, nút "Add new source"; mô tả "system validates the format before collecting".
- Bảng "Source list": phụ đề "N sources · M active", badge "AUTO SYNC"; cột Source (tên + URL), Language, Status (badge Stable xanh / Warning vàng / Source error đỏ + dòng phụ: "Synced 2 min ago", "Slow response · 1 warning", "Link returns HTML, not RSS/Atom"), Active (toggle), nút thùng rác.
- Thẻ "Recently classified articles" (nhãn "LABEL REVIEW"): filter pill (All + 3 topic), danh sách dòng: số thứ tự, badge topic, tên nguồn, tiêu đề, đoạn tóm tắt, "Confidence xx%" + thanh, mũi tên →.
- Không thấy empty/loading trong ảnh; có trạng thái lỗi nguồn (dòng đỏ).

---

## PHẦN B1 - Endpoint thật

Prefix `/api/v1` (`settings.api_v1_prefix`, app/main.py:15). Auth admin = header `X-Admin-Token` (`require_admin`, app/api/deps.py:20; 503 nếu chưa cấu hình token, 401 nếu sai).

| Method | Path | Auth | Request | Response (tên trường: kiểu) | File |
|---|---|---|---|---|---|
| GET | `/` | public | - | HTML (`app/static/index.html`) | app/main.py:27 |
| GET | `/health` | public | - | `{status: str}` | app/api/routes/health.py:6 |
| GET | `/api/v1/sources` | public | - | `list[SourceRead]`: id:int, name:str, type:str, feed_url:str\|None, query:str\|None, language:str, is_active:bool, created_at:datetime | routes/sources.py:27; schemas/source.py:45 |
| POST | `/api/v1/sources` | admin | `SourceCreate`: name(2-120), type: "rss"\|"news_api" (def. rss), feed_url: HttpUrl\|None, query(2-200)\|None, language(2-10, def. "en") | 201 `SourceRead`; 409 trùng name/feed_url | routes/sources.py:11; schemas/source.py:7 |
| DELETE | `/api/v1/sources/{source_id}` | admin | - | 204; 404 | routes/sources.py:32 |
| POST | `/api/v1/ingestion/run` | admin | query `source_id: int\|None (>=1)` | `IngestionResult`: sources_processed:int, articles_seen:int, articles_created:int, duplicates_skipped:int, errors:list[str] | routes/ingestion.py:10; schemas/ingestion.py:4 |
| GET | `/api/v1/articles` | public | query `topic:str\|None`, `status:str\|None`, `limit` (1-100, def. 20), `offset` (>=0) | `ArticlePage`: items:list[ArticleRead], total:int, limit:int, offset:int | routes/articles.py:10; schemas/article.py:23 |
| GET | `/api/v1/articles/{article_id}` | public | - | `ArticleRead`: id, source_id, title, url, author:str\|None, content:str, summary:str\|None, topic:str\|None, confidence:float\|None, status:str, published_at:datetime\|None, created_at:datetime; 404 | routes/articles.py:24; schemas/article.py:6 |
| GET | `/api/v1/topics/trending` | public | query `window_hours` (1-168, def. 24), `baseline_days` (1-30, def. 7), `min_articles` (1-50, def. 2), `limit` (1-50, def. 10) | `list[TrendingTopic]`: topic:str, article_count:int, expected_count:float, trend_score:float | routes/topics.py:10; schemas/article.py:30 |
| GET | `/api/v1/ai/topics` | public | - | `list[TopicRead]`: id:int, label:str, size:int, keywords:list[{word:str, weight:float}], representative_articles:list[{id,title,url}], updated_at:datetime | routes/ai.py:106; schemas/ai.py:62 |
| POST | `/api/v1/ai/search` | public, rate limit theo IP (`ai_search_rate_per_minute`=30), body <= `ai_search_max_body_bytes`=4096 | `AiSearchRequest`: input:str (2-500; link bị từ chối 422) | `AiSearchResponse`: sources:list[AskSource]; AskSource: id:int, title:str, url:str, source_name:str, published_at:datetime\|None, similarity:float, summary:str, summary_method: "ai"\|"cached"\|"extractive" (public chỉ trả "cached"/"extractive") | routes/ask.py:63; schemas/ask.py |
| POST | `/api/v1/ai/ask` | admin | `AskRequest`: input:str (2-1500; nhận link) | `AskResponse`: answer:str\|None, sources:list[AskSource] | routes/ask.py:23; schemas/ask.py:36 |
| POST | `/api/v1/ai/process` | admin | `AIProcessRequest`: limit, duplicate_threshold (0.70-1.0), force:bool | 202 `AIJobRead`: id:str, status: pending\|running\|succeeded\|failed, result: AIProcessResult\|None, error:str\|None, created_at, started_at, finished_at | routes/ai.py:27; schemas/ai.py:9,39 |
| GET | `/api/v1/ai/process/{job_id}` | **public** | - | `AIJobRead`; 404 | routes/ai.py:90 |

`AIProcessResult` (schemas/ai.py:25): documents_received, unique_documents, semantic_duplicates, topics_created, articles_updated, confidence_method ("hdbscan_soft"\|"fallback"), topic_coherence:float\|None.

Models: `Source` (app/models/source.py: id, name, type, feed_url, query, language, is_active, created_at) · `Article` (app/models/article.py: id, source_id, title, url, author, content, summary, ai_summary, topic, confidence, status, embedding, embedding_key, published_at, created_at) · `Topic` (app/models/topic.py: id, label, centroid, article_count, keywords, representative_article_ids, updated_at) · `AIJob` (app/models/ai_job.py). Migrations `alembic/versions/0001`-`0006` khớp các cột trên; không có cột `last_synced_at`, `last_error`, `classified_at`, `is_full_text`.

Giá trị `Article.status` thật (code): `pending` (default model), `analyzed`, `missing_content` (app/services/ingestion.py:20-21), `ai_analyzed` (repositories/article.py:303).

---

## PHẦN B2 - Map thành phần UI → API

### Màn 1-2: Search

| Thành phần UI | Endpoint / trường | Trạng thái | Ghi chú |
|---|---|---|---|
| Ô search + nút | `POST /ai/search` `input` | CÓ SẴN | 2-500 ký tự; link → 422; 429 khi quá rate (`Retry-After`); 503 khi thiếu model. UI phải xử lý 422/429/503 |
| Tóm tắt từng bài | `AskSource.summary`, `summary_method` | CÓ SẴN | Public chỉ "cached" (LLM đã lưu) hoặc "extractive" (news_search.py:349-355) |
| Thẻ "Smart summary" tổng quan | `AskResponse.answer` chỉ ở `POST /ai/ask` (admin) | KHÔNG CÓ DỮ LIỆU THẬT (public) | `/ai/search` không có `answer`. Rẻ nhất: bỏ thẻ, hoặc dùng summary của kết quả top-1. Không gọi /ai/ask từ UI public (cần token, gọi LLM) |
| Danh sách: tiêu đề, nguồn, thời điểm | `title`, `source_name`, `published_at`, `url` | CÓ SẴN | `published_at` có thể null → UI fallback "date unknown" |
| Badge topic từng bài | - | THIẾU TRƯỜNG | `AskSource` không có `topic`. S: thêm `topic: str\|None` vào AskSource + `_ask_source` (ask.py:96) (`source.article.topic` sẵn có) |
| Badge "Saved" / "Excerpt only" | - | THIẾU TRƯỜNG | Không có cờ. Có `Article.status` (`analyzed` vs `missing_content`) nhưng không biết snippet hay full text (ngưỡng `full_text_min_chars`=800 chỉ dùng lúc ingest, ingestion.py:147). S: thêm cờ suy ra từ `status`/độ dài content. Rẻ nhất: bỏ badge |
| "N best matching results" | `len(sources)` | CÓ SẴN | Không có `total`; cap bởi `ask_max_sources` |
| Điểm liên quan | `similarity` (0-1) | CÓ SẴN | Không có trong mockup; tùy chọn |
| Dropdown sort "Most relevant" | - | THIẾU ENDPOINT (không có tham số sort) | Rẻ nhất: server đã sắp theo score; sort client theo `published_at` nếu cần, hoặc bỏ dropdown |
| "N sources analyzed" | đếm distinct `source_name` client-side | CÓ SẴN (tính) | |
| "Updated N minutes ago" | - | KHÔNG CÓ DỮ LIỆU THẬT | Không có timestamp tổng hợp. Thay: dùng `created_at` bài mới nhất (`GET /articles?limit=1`) làm "Last article collected", hoặc bỏ |
| Link "Read methodology" | - | KHÔNG CÓ DỮ LIỆU THẬT | Bỏ |
| Badge "real-time updates" | - | KHÔNG CÓ DỮ LIỆU THẬT | Không có realtime/scheduler (không tìm thấy apscheduler/celery/lifespan trong app/). Đổi chữ trung tính hoặc bỏ |
| Chip "Trending:" | `GET /topics/trending` `topic` | CÓ SẴN | Là tên topic/nhãn, không phải từ khóa người dùng; click nhét vào ô search |
| Avatar "AN" | - | KHÔNG CÓ DỮ LIỆU THẬT | Không có user/auth. Bỏ |
| Thẻ "AINIS Insight" | - | KHÔNG CÓ DỮ LIỆU THẬT | Copy tĩnh, tùy chọn |
| Trạng thái rỗng/lỗi/loading | HTTP 200 với `sources: []`; 422/429/503 | CÓ SẴN | Mockup không vẽ, cần tự thiết kế |

### Màn 2 sidebar: Trending

| Thành phần | Endpoint / trường | Trạng thái | Ghi chú |
|---|---|---|---|
| Tên chủ đề | `TrendingTopic.topic` | CÓ SẴN | |
| "N articles" | `article_count` | CÓ SẴN | Số bài trong cửa sổ gần nhất, không phải tổng |
| Điểm σ | `trend_score` | CÓ SẴN | Công thức thật (app/services/trending.py:10, :37-39): `(recent − expected) / sqrt(expected + 1)`. `expected = baseline_count / windows_in_baseline`, `windows_in_baseline = baseline_days*24/window_hours` (trending.py:63). Mặc định cửa sổ 24 h, baseline 7 ngày **trước** cửa sổ (routes/topics.py:13-18). Đây là xấp xỉ z-score Poisson, có +1 nên không phải z-score thuần |
| Nhãn "24h" | `window_hours` (client truyền) | CÓ SẴN | |
| Lọc | - | CÓ SẴN | Bỏ nhãn "Other", "Other / Outlier" (`CATCH_ALL_TOPICS`, trending.py:26); chỉ giữ `score > 0` và `recent >= min_articles`. Có thể trả rỗng khi dữ liệu ít → cần empty state |
| Thời gian của bài | `coalesce(published_at, created_at)` | CÓ SẴN | repositories/article.py:196 |
| Thanh tiến độ | tính client từ `trend_score` / max | CÓ SẴN (tính) | |
| "View all topics" | điều hướng sang màn 4 | CÓ SẴN | |
| Lưu ý nhãn | `Article.topic` trộn nhãn heuristic ("Generative AI", "AI Policy"... analyzer.py:15-21) và nhãn BERTopic | CẦN XÁC MINH | Dữ liệu thật quyết định trending hiện nhãn nào |

### Màn 3: Chi tiết bài (`GET /articles/{id}`, id lấy từ `AskSource.id`)

| Thành phần | Trường | Trạng thái | Ghi chú |
|---|---|---|---|
| Tiêu đề, link gốc | `title`, `url` | CÓ SẴN | `url` đã lọc http(s), không credential (feed.py:46-62) |
| Đoạn dẫn | `summary` | CÓ SẴN | Là summary heuristic 2 câu (analyzer.py `_summarize`); `ai_summary` không có trong `ArticleRead` → THIẾU TRƯỜNG nếu muốn bản LLM (S) |
| Tác giả | `author` (nullable) | CÓ SẴN | Nhiều feed không có → "Unknown" |
| Nguồn | `source_id` only | THIẾU TRƯỜNG | Không có tên nguồn. Rẻ nhất: client join với `GET /sources`; hoặc từ `AskSource.source_name` khi mở từ search. S nếu thêm `source_name` vào ArticleRead |
| Xuất bản gốc | `published_at` | CÓ SẴN | nullable |
| Thu thập lúc | `created_at` | CÓ SẴN | |
| Badge topic | `topic` | CÓ SẴN | nullable |
| Confidence % | `confidence` (float) | CÓ SẴN, CẦN XÁC MINH ngữ nghĩa | 0-1 → nhân 100. Hai nguồn khác nhau: heuristic (analyzer.py: 0.3 hoặc 0.45+0.1*score, tối đa 0.95) lúc ingest, HDBSCAN soft prob sau `/ai/process` (topic_model.py:202; có chế độ "fallback" hằng số). Không phải độ chính xác thật; nên gắn nhãn "classification confidence" |
| Badge "Analyzed" | `status` | CÓ SẴN | Map `ai_analyzed`/`analyzed`/`missing_content`/`pending` sang nhãn tiếng Anh |
| "Collected content" | `content` | CÓ SẴN | Có thể rất dài (cap `max_article_content_chars`); hiển thị bằng `textContent` |
| Badge "Feed · Full text" | - | THIẾU TRƯỜNG | Như màn 2; không có cờ. Rẻ nhất: bỏ, hoặc suy ra `status == "missing_content"` → "Title only" |
| Timeline nguồn & lịch sử | `published_at`, `created_at` | CÓ SẴN (2 mốc) | Chỉ có 2 sự kiện thật: "Published" và "Collected". Dòng "Collected from RSS feed" cần biết `Source.type` ("rss"/"news_api") qua source_id → client join. Không có lịch sử phân loại, không có `classified_at` |
| Mã `ainsi://article/...` | - | KHÔNG CÓ DỮ LIỆU THẬT | Bỏ (hoặc hiện `#id`) |
| 404 / loading | HTTP 404 "Article not found" | CÓ SẴN | |

### Màn 4: Chủ đề

| Thành phần | Endpoint / trường | Trạng thái | Ghi chú |
|---|---|---|---|
| Danh sách cụm | `GET /ai/topics`: `id`, `label`, `size`, `keywords[].word/weight`, `updated_at` | CÓ SẴN | Sắp theo size giảm dần (repositories/topic.py:324). `size` = số bài có `Article.topic == label` |
| Keyword chips | `keywords` (top N, `KEYWORD_COUNT`) | CÓ SẴN | Của batch gần nhất chạm cụm đó |
| Mô tả cụm (1 câu) | - | KHÔNG CÓ DỮ LIỆU THẬT | Thay bằng tiêu đề `representative_articles[0].title` hoặc bỏ |
| Số bài "N articles" | `size` | CÓ SẴN | |
| "View cluster →" lọc bài | `GET /articles?topic=<label>` | CÓ SẴN | So khớp chính xác theo nhãn; `limit<=100` + phân trang |
| Bài tiêu biểu | `representative_articles` (id,title,url) | CÓ SẴN | Không có trong mockup; tùy chọn |
| Badge σ trên cụm | join `trending.topic == label` | CÓ SẴN (join client), một phần | Chỉ có nếu cụm nằm trong top trending (score>0, >=`min_articles`); cụm khác không có σ → ẩn |
| Sort "Growth" | client sort theo σ / size | CÓ SẴN (tính) | |
| "N clusters from M articles" | `len(topics)`; M = `ArticlePage.total` của `GET /articles?limit=1` | CÓ SẴN (tính) | M gồm cả bài chưa qua `/ai/process` |
| Outlier: số bài | `GET /articles?topic=Other / Outlier&limit=1` → `total` | CÓ SẴN (nhãn `OUTLIER_LABEL = "Other / Outlier"`, topic_model.py:37) | Outlier không nằm trong bảng `topics`/`/ai/topics` (nhãn -1 chỉ gán ở topic_model.py:396). Lưu ý nhãn `"Other"` của analyzer heuristic là khác |
| Outlier: % | outlier_total / total (2 call) | CÓ SẴN (tính) | Mẫu số là toàn bộ bài; mockup nói "% of data" → CẦN XÁC MINH mẫu số mong muốn (bài đã qua model hay tất cả) |
| Toggle "Show" outliers | - | CÓ SẴN (UI state) | |
| Biểu đồ xu hướng 7/30 ngày | - | THIẾU ENDPOINT | Không có chuỗi thời gian theo ngày. Xem mục 3 |
| Legend σ + nhãn Spike/Rising/Stable | `trend_score` | CÓ SẴN (tính) | Ngưỡng nhãn là quy ước UI, backend không có; phải tự đặt và ghi rõ |
| Toggle 7d/30d | `window_hours`/`baseline_days` | THIẾU ENDPOINT cho chart; CÓ SẴN cho σ | `trending` cho phép `window_hours` đến 168 (7 ngày) nhưng không có 30 ngày (`baseline_days` tối đa 30 là baseline, không phải cửa sổ) |
| Thời điểm chạy model gần nhất | `max(TopicRead.updated_at)` | CÓ SẴN, CẦN XÁC MINH | `updated_at` chỉ cập nhật khi cụm được batch chạm tới (repositories/topic.py:367). `AIJobRead.finished_at` chính xác hơn nhưng chỉ lấy được theo `job_id`, không có endpoint "latest job" → THIẾU ENDPOINT |
| Footer "BERTopic · HDBSCAN · c-TF-IDF" | - | CẦN XÁC MINH | BERTopic/HDBSCAN có trong topic_model.py; "c-TF-IDF" chưa xác nhận trong code. Viết copy chung chung hoặc xác minh trước |
| Badge "Topic discovery with BERTopic" | - | CÓ SẴN (copy tĩnh) | |
| Empty state | `/ai/topics` trả `[]` khi chưa chạy `/ai/process` | CÓ SẴN | Cần thiết kế |

### Màn 5: Quản trị nguồn (tất cả thao tác ghi cần `X-Admin-Token`)

| Thành phần | Endpoint / trường | Trạng thái | Ghi chú |
|---|---|---|---|
| Danh sách nguồn: tên, URL, ngôn ngữ | `GET /sources`: `name`, `feed_url`, `language`, `type`, `query` | CÓ SẴN | `language` là chuỗi tự do ("en"/"vi"...) → hiển thị bằng map client. Nguồn `news_api` có `feed_url = null`, dùng `query` |
| "N sources · M active" | đếm `is_active` client | CÓ SẴN (tính) | |
| Toggle Active | `Source.is_active` (đọc) | CÓ SẴN (đọc) / **THIẾU ENDPOINT (ghi)** | Không có `PATCH`/`PUT /sources/{id}`; `SourceCreate` không có `is_active`. S: thêm `PATCH /sources/{id}` (admin) body `{is_active: bool}`, không cần migration |
| Xóa nguồn | `DELETE /sources/{id}` | CÓ SẴN | **Cascade xóa toàn bộ bài của nguồn** (`cascade="all, delete-orphan"`, models/source.py:30). UI phải có confirm nêu rõ. Nguồn "User-submitted links" (repositories/source.py:375) cũng xóa được |
| Thêm nguồn | `POST /sources` (`name`, `feed_url`, `language`, `type="rss"`) | CÓ SẴN | 409 khi trùng tên/URL. Mockup chỉ có RSS; `news_api` (cần `query`, `NEWS_API_KEY`) không nằm trong mockup |
| "System validates format before collecting" | - | KHÔNG CÓ DỮ LIỆU THẬT / sai sự thật | POST không kiểm tra feed; chỉ `HttpUrl` (schemas/source.py:13). Việc kiểm tra RSS/SSRF xảy ra lúc ingest (feed.py:79-96, safe_http.py:18). Hoặc đổi copy, hoặc thêm validate-on-create (M) |
| Trạng thái Stable/Warning/Error | - | THIẾU TRƯỜNG + THIẾU ENDPOINT | Không có cột nào lưu kết quả lần sync. Xem mục 3 |
| Lý do lỗi ("Link returns HTML, not RSS/Atom") | `IngestionResult.errors[]` dạng `"<name>: <ExceptionType>: <msg>"` (ingestion.py:113) | Chỉ trong response của lần chạy đó, không lưu | Thông điệp thật `UnsupportedFeedError` ở feed.py:91-98. Parse chuỗi `"<name>: "` dễ vỡ |
| "Synced 2 min ago" | - | THIẾU TRƯỜNG | Không có `last_synced_at`. Gần đúng: `max(Article.created_at)` theo source (chỉ phản ánh lần có bài mới) |
| Badge "AUTO SYNC" | - | KHÔNG CÓ DỮ LIỆU THẬT | Không có scheduler trong app. Bỏ hoặc ghi "Manual sync" |
| Nút "Rescan sources" | `POST /ingestion/run` (`source_id` tùy chọn) | CÓ SẴN | **Đồng bộ, có thể lâu** (tải feed + full-text từng bài, ingestion.py:141-162); cần timeout/spinner, chặn double-click. Có thể tạo job song song: không có khóa như AI job (CẦN XÁC MINH) |
| 4 thẻ thống kê | `IngestionResult.sources_processed/articles_seen/articles_created/duplicates_skipped` | CÓ SẴN **chỉ sau khi chạy**, không lưu | Không có endpoint lấy lần chạy gần nhất → lúc tải trang chưa có số. Rẻ nhất: hiện "-" đến khi bấm Rescan, hoặc lưu vào `sessionStorage` |
| Chú thích "+3 today", "+12.6%", "+38" | - | KHÔNG CÓ DỮ LIỆU THẬT | Bỏ. "6.8% of total" = `duplicates_skipped / articles_seen` tính được |
| Bài vừa phân loại: tiêu đề, topic, summary | `GET /articles?status=ai_analyzed&limit=N`: `title`, `topic`, `summary` | CÓ SẴN | Sắp theo `published_at desc` (repositories/article.py:169), **không** theo thời điểm phân loại (không có `classified_at`) → tên "recently classified" hơi sai; đổi thành "Latest classified articles" |
| Tên nguồn mỗi dòng | `source_id` | THIẾU TRƯỜNG | Client join với `GET /sources` |
| Confidence % + thanh | `confidence` | CÓ SẴN | Ngữ nghĩa như màn 3 |
| Filter pill (All + topic) | `GET /articles?topic=<label>` | CÓ SẴN | Danh sách pill phải sinh động từ `/ai/topics` (nhãn thật), không dùng "Policy/Models/Business" của mockup |
| Mũi tên → | mở drawer màn 3 | CÓ SẴN | |
| Trạng thái đăng nhập admin | `X-Admin-Token` | CÓ SẴN | UI phải có ô nhập token lúc chạy; không nhúng vào bundle. 401/503 cần thông báo |

---

## PHẦN B3 - Mục THIẾU: ước lượng

| # | Mục thiếu | Cần gì | Độ khó | Cách rẻ nhất |
|---|---|---|---|---|
| 1 | Toggle bật/tắt nguồn | `PATCH /sources/{id}` admin, schema `SourceUpdate{is_active}`; không migration | **S** | Bắt buộc nếu giữ toggle; nếu không, hiện read-only |
| 2 | Trạng thái nguồn + lý do lỗi + last sync | Migration: `sources.last_synced_at`, `last_status`, `last_error` (nullable); ghi trong `IngestionService.run` (ingestion.py:66-113); thêm vào `SourceRead`. Đo "warning" cần định nghĩa (CẦN XÁC MINH) | **M** | Chỉ 2 trạng thái Active/Inactive + "last collected" = `max(articles.created_at)` theo source (query, không migration, **S**). Hoặc lưu lỗi lần Rescan hiện tại trên client |
| 3 | Chuỗi thời gian theo chủ đề (chart 7/30 ngày) | `GET /topics/timeseries?days=7\|30&limit=3` → `[{topic, points:[{date,count}]}]`; query `group by date(coalesce(published_at, created_at)), topic`. Không migration. Cần xử lý SQLite vs Postgres | **M** | Bỏ chart, giữ legend σ + thanh (từ trending). Hoặc dựng bucket ngày phía Python từ `GET /articles` (không khuyến nghị: tối đa 100/trang) |
| 4 | `topic` trong kết quả search | Thêm `topic` vào `AskSource` + `_ask_source` | **S** | Bỏ badge topic ở thẻ kết quả |
| 5 | Cờ "Saved"/"Excerpt only"/"Full text" | Thêm `content_kind` suy từ `status`/độ dài (CẦN XÁC MINH ngưỡng) vào `AskSource` và `ArticleRead` | **S** | Bỏ badge |
| 6 | Tên nguồn trong `ArticleRead` | Thêm `source_name` (join) | **S** | Client join `GET /sources` |
| 7 | Tổng quan "Smart summary" public | Cần LLM → chỉ có ở `/ai/ask` (admin, tốn chi phí) | **L** (an toàn/chi phí/rate limit) | Bỏ thẻ; hoặc dùng summary top-1 |
| 8 | Số liệu lần ingest gần nhất khi tải trang | Bảng `ingestion_runs` (migration) + `GET /ingestion/last` | **M** | "-" đến khi bấm Rescan |
| 9 | "Latest model run" chính xác | `GET /ai/process?latest=1` hoặc thêm vào `/ai/topics` | **S** | `max(updated_at)` từ `/ai/topics` |
| 10 | Validate feed khi thêm nguồn | Gọi `FeedClient.fetch` trong POST /sources (hoặc endpoint `POST /sources/validate`); bắt `UnsafeFeedUrlError`/`UnsupportedFeedError` → 422 | **M** (có độ trễ mạng trong request) | Bỏ dòng copy "validates", để lỗi hiện ở lần Rescan |
| 11 | Sort dropdown search | Tham số sort | **S** | Bỏ hoặc sort client |
| 12 | `Updated N minutes ago` | - | **S** | Dùng `created_at` bài mới nhất, hoặc bỏ |
| 13 | Mô tả cụm | Cột/LLM | **L** | Bỏ, dùng bài tiêu biểu |

### Tổng hợp

Đếm theo thành phần ở các bảng map màn 1-5 (mỗi dòng = 1 thành phần, gộp trạng thái chính):

- **CÓ SẴN** (kể cả loại "tính client" và "join client"): ~46
- **THIẾU TRƯỜNG / THIẾU ENDPOINT** (cần code backend để đúng mockup): ~13 (topic trong search, cờ content, source_name, toggle ghi, trạng thái nguồn, last sync, last-run stats, time series, latest-run, validate, sort, và 2 biến thể)
- **KHÔNG CÓ DỮ LIỆU THẬT → bỏ**: ~11 (overview summary public, "updated X ago" nguyên bản, methodology, real-time badge, avatar, AINIS Insight, `ainsi://`, mô tả cụm, auto sync, deltas +%, validates-copy)
- **CẦN XÁC MINH**: 7 (ngữ nghĩa confidence, mẫu số outlier %, "c-TF-IDF", job song song khi Rescan, ngưỡng full-text, nhãn trending thực tế, định nghĩa "warning")

(Con số là đếm tay theo bảng; sai lệch ±2 do một số dòng gộp.)

### Endpoint / migration mới đề xuất

| Ưu tiên | Việc | Độ khó |
|---|---|---|
| Cần để UI chạy | `PATCH /sources/{id}` `{is_active}` | S |
| Cần để UI chạy | Thêm `topic` vào `AskSource` | S |
| Nên có | `source_name` vào `ArticleRead` (hoặc client join) | S |
| Nên có | `GET /topics/timeseries` | M |
| Nên có | Migration `0007` (`sources.last_synced_at/last_status/last_error`) + ghi trong ingestion | M |
| Tùy chọn | `content_kind` cờ | S |
| Tùy chọn | `GET /ingestion/last` + bảng `ingestion_runs` | M |
| Tùy chọn | validate feed lúc tạo | M |
| Tùy chọn | latest AI job | S |

---

## PHẦN B4 - Bảo mật

1. **Endpoint public trả dữ liệu từ RSS** (nội dung do bên thứ ba kiểm soát → coi là không tin cậy):
   - `GET /articles`, `GET /articles/{id}`: `title`, `author`, `content`, `summary`, `url`.
   - `POST /ai/search`: `title`, `url`, `source_name`, `summary`.
   - `GET /ai/topics`: tiêu đề/URL bài tiêu biểu, keyword.
   - `GET /topics/trending`: nhãn topic.
   - `GET /sources`: **`feed_url` công khai**; nếu URL feed chứa token/khóa trong query string thì bị lộ (CẦN XÁC MINH dữ liệu thật) và `query` của nguồn news_api.
   - `GET /ai/process/{job_id}`: **public**, trả `error` (text lỗi nội bộ) và `result`. Job id là UUID khó đoán nhưng nên cân nhắc đưa sau admin.
   - `GET /articles*`, `/ai/topics`, `/topics/trending`, `GET /sources` **không có rate limit** (chỉ `/ai/search` có, app/api/deps.py:52). `limit<=100`.
   - UI bắt buộc render bằng `textContent` (như static/index.html:157); không dùng `innerHTML` với dữ liệu bài. `url` đã lọc http(s) (feed.py:46) nên dùng `href` được, thêm `rel="noopener noreferrer"`.
2. **CORS**: không có `CORSMiddleware` (grep toàn `app/`). Chỉ chạy được same-origin; nếu UI phục vụ chung app thì không cần CORS. Không nên bật `*`.
3. **CSP / header bảo mật**: `app/main.py` không đặt header nào (không CSP, X-Frame-Options, X-Content-Type-Options, Referrer-Policy); `index.html` không có `<meta http-equiv>` CSP. Cần thêm middleware header khi làm UI; UI dùng inline script/style hiện tại thì CSP phải cho phép (hoặc tách file + nonce).
4. **Static**: app chỉ phục vụ một file `GET /` → `app/static/index.html` (main.py:24-30). **Không có `StaticFiles` mount**, không có route cho css/js/ảnh/font. UI nhiều trang/asset cần: mount `/static`, hoặc inline hết, hoặc đổi routing (`/`, `/topics`, `/sources` hiện chưa có). Font hiện dùng `system-ui`. Ảnh logo cần copy vào repo sau (chưa làm). `/docs`, `/openapi.json` đang public.
5. **SSRF khi thêm nguồn**:
   - Lúc `POST /sources` **không có kiểm tra** SSRF (chỉ `HttpUrl`, admin-only).
   - Lúc ingest: `resolve_public_addresses` (safe_http.py:18) từ chối scheme không phải http(s), host phân giải ra IP không `is_global`; `PinnedTransport` kết nối đúng IP đã kiểm (chống DNS rebinding), `open_stream` kiểm lại từng redirect (safe_http.py:83-98), có giới hạn kích thước (`read_limited`), `trust_env=False`. Full-text extractor dùng cùng `make_client` (content_extractor.py:8). Commit `a7d462a` là bản vá này.
   - Rủi ro còn lại: nguồn bị chấp nhận rồi mới fail lúc Rescan (UX, không phải lỗ hổng); thông báo lỗi chi tiết (`IngestionResult.errors`) trả về admin có thể lộ hostname nội bộ nào resolve được (admin-only, chấp nhận được).
   - Rescan là đồng bộ trong request: một nguồn chậm treo worker (DoS nội bộ, admin-only).
6. **Token admin trong trình duyệt**: UI quản trị phải lấy token từ người dùng khi chạy (ưu tiên `sessionStorage`), không hardcode; mọi POST/PATCH/DELETE gửi `X-Admin-Token`. Token gửi qua HTTP thường là rủi ro nếu không có TLS (CẦN XÁC MINH cách deploy).
7. DELETE nguồn cascade xóa bài (mục 5), cần confirm ở UI.
