# PostgreSQL, migrations và backup

## Khởi động bằng Docker Compose

Yêu cầu Docker Engine/Desktop đang chạy và Docker Compose v2.
Từ thư mục project (PowerShell):

```powershell
# Copy-Item ghi đè file có sẵn; chỉ copy khi chưa có .env.
if (-not (Test-Path .env)) { Copy-Item .env.example .env }
New-Item -ItemType Directory -Force backups
docker compose up -d --build
docker compose ps -a
docker compose logs migrate api
```

Nếu đã có `.env`, thêm các biến `POSTGRES_*`, `API_PORT`, `TZ` từ `.env.example`
và đổi `DATABASE_URL` sang PostgreSQL. Mật khẩu `news` chỉ dành cho local.
Trong container, app tự dựng connection URL từ `POSTGRES_HOST=db`, `POSTGRES_USER`,
`POSTGRES_PASSWORD`, `POSTGRES_DB` và tự escape ký tự đặc biệt (`@ : / # %`) trong
mật khẩu. Ràng buộc còn lại là cú pháp `.env` của Compose: tránh `$` (bị nội suy) và
đặt mật khẩu có khoảng trắng hoặc `#` trong dấu nháy. `DATABASE_URL` trong `.env`
chỉ dùng cho Python chạy trên host và phải tự URL-encode mật khẩu.
Dùng mật khẩu ngẫu nhiên dài cho môi trường triển khai. Không commit `.env`.

Database lưu trong named volume `postgres_data`. `docker compose down` giữ dữ liệu;
`docker compose down -v` xóa volume và dữ liệu. Không dùng `-v` khi cần giữ DB.
Các biến khởi tạo PostgreSQL chỉ có hiệu lực khi volume còn trống; đổi password
trong `.env` không đổi password của role trong volume đã tồn tại.

Compose chờ DB healthy, chạy `alembic upgrade head` trong service `migrate`, rồi
mới chạy API. Migrate kết thúc với mã 0 là bình thường. API tại
<http://localhost:8000/docs>. Cổng API và DB chỉ bind loopback của máy host.
Khi cập nhật schema ở các lần triển khai tiếp theo:

```powershell
docker compose stop api
docker compose build
docker compose run --rm migrate
# Chỉ chạy tiếp nếu migration thành công.
docker compose up -d api
```

## Chạy Python trên host

```powershell
docker compose up -d db
.\.venv\Scripts\python.exe -m pip install -r requirements-dev.txt
.\.venv\Scripts\python.exe -m alembic upgrade head
.\.venv\Scripts\python.exe -m uvicorn app.main:app --reload
```

`DATABASE_URL` trên host dùng `localhost` và port `POSTGRES_PORT`; trong container
Compose đặt `POSTGRES_HOST=db`, biến này được ưu tiên hơn `DATABASE_URL`. Nếu đổi user/password/database/port, cập
nhật URL trên host tương ứng. API không tự tạo hay sửa bảng lúc khởi động.

Sau khi sửa model, tạo và kiểm tra migration trước khi áp dụng:

```powershell
.\.venv\Scripts\python.exe -m alembic revision --autogenerate -m "describe change"
.\.venv\Scripts\python.exe -m alembic upgrade head
.\.venv\Scripts\python.exe -m alembic check
.\.venv\Scripts\python.exe -m alembic current
```

Migration đầu tiên dành cho database rỗng. Nó không tự chuyển dữ liệu từ
`data/news.db`: giữ bản SQLite cũ để đối chiếu và lên kế hoạch import riêng nếu cần
giữ các bài đã thu thập. Không `stamp head` để bỏ qua migration trên schema chưa
được kiểm chứng. Downgrade về `base` xóa hai bảng ứng dụng.

## UTC

PostgreSQL và kết nối ứng dụng dùng timezone UTC. Các cột thời gian dùng
`TIMESTAMP WITH TIME ZONE`; giá trị đọc ra và ngày RSS được chuẩn hóa UTC.
Ngày không có timezone được hiểu là UTC. API trả ISO 8601 có `Z` hoặc `+00:00`.
SQLite chỉ còn phục vụ test; kiểu `UTCDateTime` khôi phục timezone khi đọc SQLite.
Bài không có `published_at` nằm cuối danh sách.

## Backup

Lệnh sau chạy `pg_dump` trong container và ghi file trực tiếp vào thư mục
`backups` trên host. Cách này tránh làm hỏng dữ liệu nhị phân qua redirect của
Windows PowerShell. Đổi tên file cho mỗi lần backup, không ghi đè bản cần giữ.

```powershell
docker compose exec -T db sh /ops/database.sh backup news-20260929.dump
docker compose exec -T db pg_restore --list /backups/news-20260929.dump
```

Backup gồm dữ liệu, schema và `alembic_version`; không gồm role/password của
cluster. `pg_dump` tạo snapshot nhất quán khi API đang chạy. Kiểm tra exit code
`$LASTEXITCODE -eq 0`, dung lượng file và lưu bản sao ở nơi khác với máy chạy DB.
Thư mục backups bị loại khỏi Git và Docker build context.

## Restore thử vào database riêng

Giữ nguyên DB đang dùng. Tạo DB mới với tên chưa tồn tại, rồi restore trong một
transaction; nếu lỗi, không có restore dở dang. Chạy với cùng PostgreSQL major
version như bản backup (Compose dùng PostgreSQL 17).

```powershell
docker compose exec -T db sh /ops/database.sh restore news-20260929.dump news_restore_check
```

Script từ chối ghi đè backup và từ chối restore vào DB đang dùng hoặc DB đã tồn tại.
Nếu restore thất bại sau bước tạo DB, DB mới rỗng còn lại để kiểm tra; lần thử tiếp
theo dùng tên mới. Script in số nguồn, số bài và phiên bản Alembic sau restore.

Để đưa DB đã restore vào sử dụng: dừng API, đặt `POSTGRES_DB=news_restore_check`
trong `.env`, cập nhật `DATABASE_URL` trên host, chạy `docker compose run --rm migrate`,
rồi `docker compose up -d`. Kiểm tra API và dữ liệu trước khi xóa DB cũ.
Không restore đè DB đang được API ghi. `pg_restore --list` chỉ kiểm tra archive;
restore thử và đọc dữ liệu mới xác nhận backup dùng được.

Tham khảo: [Compose startup order](https://docs.docker.com/compose/how-tos/startup-order/),
[Alembic](https://alembic.sqlalchemy.org/en/latest/tutorial.html).
