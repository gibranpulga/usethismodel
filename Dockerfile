FROM python:3.12-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PORT=8000 DATABASE_PATH=/data/usethismodel.sqlite3 PUBLIC_BASE_URL=https://usethismodel.com
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY . .
RUN mkdir -p /data && chown -R 10001:10001 /app /data
USER 10001
EXPOSE 8000
HEALTHCHECK --interval=15s --timeout=10s --start-period=15s --retries=5 CMD ["python", "/app/healthcheck.py"]
CMD ["sh", "-c", "exec gunicorn --preload --bind 0.0.0.0:${PORT} --workers 2 --worker-class uvicorn.workers.UvicornWorker --access-logfile - --error-logfile - asgi:app"]
