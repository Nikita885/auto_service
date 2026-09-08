FROM python:3.12-slim AS base

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
        build-essential libpq5 curl \
    && rm -rf /var/lib/apt/lists/*

COPY requirements/ /app/requirements/
ARG REQUIREMENTS=dev
RUN pip install -r /app/requirements/${REQUIREMENTS}.txt

COPY . /app/

RUN adduser --disabled-password --gecos "" appuser \
    && mkdir -p /app/static /app/media \
    && chown -R appuser:appuser /app \
    # Бит исполнения ставим здесь, а не полагаемся на права из репозитория:
    # Windows их не отслеживает, и после клона на Linux ENTRYPOINT падал бы
    # с «permission denied».
    && chmod +x /app/docker/entrypoint.sh
USER appuser

ENTRYPOINT ["/app/docker/entrypoint.sh"]
CMD ["api"]
