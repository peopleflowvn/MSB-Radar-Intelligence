# Agent cho GreenNode AgentBase.
#
# Hai ràng buộc của hợp đồng Runtime được đáp ứng ngay ở đây:
#   - EXPOSE/bind cổng 8080
#   - GET /health (định nghĩa trong app.py)
#
# KIẾN TRÚC ĐÍCH LÀ amd64 (AgentBase Runtime chạy amd64), nhưng KHÔNG hardcode
# `--platform` ở đây: khoá cứng thì `docker build` legacy trên máy ARM (runner
# CI self-hosted, Apple Silicon) hỏng ngay ở FROM. Thay vào đó truyền
# `--platform linux/amd64` cho `docker buildx build` — xem ci.yml và
# deploy-agent.yml. buildx + QEMU dựng đúng amd64 từ máy ARM; build thường trên
# máy amd64 vẫn ra amd64.
FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY app.py .

# Chạy bằng tài khoản thường, không phải root.
RUN adduser --disabled-password --gecos "" --uid 10001 agent \
    && chown -R agent:agent /app
USER agent

EXPOSE 8080

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD python -c "import httpx,sys; sys.exit(0 if httpx.get('http://127.0.0.1:8080/health', timeout=3).status_code==200 else 1)"

CMD ["python", "-m", "uvicorn", "app:app", "--host", "0.0.0.0", "--port", "8080"]
