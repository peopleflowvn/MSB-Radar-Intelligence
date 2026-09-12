# Python 3.11: chỉ Hub dùng. Edge vẫn ở 3.9 vì phụ thuộc vào pywebview/pythonnet
# trên Windows — hai runtime tách rời nhau một cách có chủ đích.
FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

# libpq5 cho psycopg2; curl cho healthcheck. Không cài build-essential vì
# psycopg2-binary đã là wheel biên dịch sẵn.
RUN apt-get update \
    && apt-get install -y --no-install-recommends libpq5 curl \
    && rm -rf /var/lib/apt/lists/*

# Copy requirements trước để layer cài đặt được cache lại khi chỉ đổi code.
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# collectstatic cần SECRET_KEY nhưng không cần khoá thật — chỉ ghi file ra đĩa.
RUN SECRET_KEY=build-time-khong-dung-that DEBUG=True \
    python manage.py collectstatic --no-input --clear

RUN adduser --disabled-password --gecos "" --uid 10001 hub \
    && chown -R hub:hub /app
USER hub

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
    CMD curl -fsS http://127.0.0.1:8000/api/v1/health/ || exit 1

# migrate chạy ở entrypoint chứ không ở build: build không có CSDL, và
# migration phải chạy đúng một lần mỗi lần triển khai.
#
# ASGI qua UvicornWorker (Master Plan §3.2): endpoint SSE của luồng Thinking cần
# async. Các view đồng bộ vẫn chạy bình thường. `--timeout` với worker async là
# thời gian chờ tắt/khởi động lại worker, không cắt request đang stream.
CMD ["sh", "-c", "python manage.py migrate --no-input && exec gunicorn config.asgi:application -k uvicorn.workers.UvicornWorker --bind 0.0.0.0:8000 --workers 3 --timeout 120 --access-logfile -"]
