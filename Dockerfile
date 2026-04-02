FROM python:3.12-slim AS base

# Security: non-root user
RUN groupadd --gid 1000 appuser && \
    useradd --uid 1000 --gid 1000 --create-home appuser

WORKDIR /app

# Install dependencies first (layer caching)
COPY requirements.txt .
RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir -r requirements.txt

# Copy application code
COPY . .

# Security: drop privileges
USER appuser

EXPOSE 8000

# ---- API target ----
FROM base AS api
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]

# ---- Worker target ----
FROM base AS worker
CMD ["celery", "-A", "app.workers.celery_app", "worker", "--loglevel=info", "--concurrency=4"]
