FROM python:3.12-slim

LABEL org.opencontainers.image.source="https://github.com/yashumani/talk2data-conversational-intelligence" \
      org.opencontainers.image.title="Talk2Data Conversational Intelligence" \
      org.opencontainers.image.description="Governed conversational intelligence runtime for enterprise data"

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

COPY pyproject.toml README.md ./
COPY src ./src

RUN python -m pip install --no-cache-dir --upgrade pip \
    && python -m pip install --no-cache-dir .

RUN useradd --create-home --uid 10001 talk2data \
    && mkdir -p /app/.talk2data \
    && chown -R talk2data:talk2data /app

USER talk2data

EXPOSE 8000

CMD ["uvicorn", "talk2data.main:app", "--host", "0.0.0.0", "--port", "8000"]
