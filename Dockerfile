FROM node:26-bookworm-slim AS workspace

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

# Package installers are build-time tools, not runtime dependencies. Removing them also removes
# their vendored libraries and the base image's obsolete ensurepip wheels from the attack surface.
RUN python -m pip uninstall -y pip setuptools wheel \
    && rm -rf /usr/local/lib/python3.12/ensurepip /root/.cache

RUN useradd --create-home --uid 10001 talk2data \
    && mkdir -p /app/.talk2data /app/workspace-state \
    && chown -R talk2data:talk2data /app

USER talk2data

EXPOSE 8000

CMD ["uvicorn", "talk2data.main:app", "--host", "0.0.0.0", "--port", "8000"]
