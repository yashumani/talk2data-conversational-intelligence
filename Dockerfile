FROM node:24-bookworm-slim AS workspace

WORKDIR /web
COPY apps/web/package.json apps/web/package-lock.json ./
RUN npm ci --ignore-scripts
COPY apps/web/ ./
RUN npm run build

FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    T2D_WEB_DIRECTORY=/app/web

WORKDIR /app

COPY pyproject.toml README.md ./
COPY requirements ./requirements
COPY scripts/dependencies.py ./scripts/dependencies.py
COPY src ./src
COPY --from=workspace /web/dist ./web

RUN PIP_NO_CACHE_DIR=1 python scripts/dependencies.py install runtime

RUN useradd --create-home --uid 10001 talk2data \
    && mkdir -p /app/.talk2data /app/workspace-state \
    && chown -R talk2data:talk2data /app

USER talk2data

EXPOSE 8000

CMD ["uvicorn", "talk2data.main:app", "--host", "0.0.0.0", "--port", "8000"]
