# dockerfile
FROM python:3.12-slim

WORKDIR /app

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1
# Prevent Python from allocating large memory arenas on a 1 GB server
ENV MALLOC_TRIM_THRESHOLD_=65536
ENV PYTHONMALLOC=malloc

COPY requirements.txt .

RUN pip install --no-cache-dir -r requirements.txt

COPY . .

EXPOSE 8000

# 1 worker (1 CPU), limit concurrent requests to 20 so the process
# doesn't queue more work than the 1 GB RAM can handle simultaneously.
CMD ["uvicorn", "main:app", \
    "--host", "0.0.0.0", \
    "--port", "8000", \
    "--workers", "1", \
    "--limit-concurrency", "20", \
    "--backlog", "64", \
    "--timeout-keep-alive", "10"]
