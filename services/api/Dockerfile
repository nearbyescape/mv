FROM python:3.14-slim-bookworm@sha256:c8137f4c460908c8763f281c8f22c431eb5c538514ba9553fc3a89c06b7cfb88
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PYTHONUTF8=1
WORKDIR /app
COPY services/api/requirements.txt /app/services/api/requirements.txt
RUN pip install --no-cache-dir -r services/api/requirements.txt
COPY packages/strategy /app/packages/strategy
RUN pip install --no-cache-dir /app/packages/strategy
COPY packages/contracts /app/packages/contracts
COPY services/api /app/services/api
RUN useradd --uid 10001 --create-home mv && chown -R mv:mv /app
USER mv
WORKDIR /app/services/api
CMD ["python", "-m", "uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--no-access-log", "--no-proxy-headers"]
