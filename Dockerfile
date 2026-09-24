FROM python:3.13-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1
RUN groupadd --gid 10001 portal \
    && useradd --uid 10001 --gid 10001 --no-create-home --home-dir /app portal
WORKDIR /app
COPY requirements.txt .
RUN pip install --upgrade pip && pip install -r requirements.txt
COPY . .
RUN chmod +x /app/docker/entrypoint.sh && chown -R 10001:10001 /app
USER 10001:10001
ENTRYPOINT ["/app/docker/entrypoint.sh"]
CMD ["gunicorn","--workers=4","--threads=2","--bind=0.0.0.0:8000","--access-logfile=-","--error-logfile=-","--timeout=60","wsgi:app"]
