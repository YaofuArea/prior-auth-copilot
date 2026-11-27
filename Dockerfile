# Stage 1: build the React front end into static files (web/dist).
FROM node:22.20-slim AS web
WORKDIR /web
COPY web/package.json web/package-lock.json ./
RUN npm ci
COPY web/ ./
RUN npm run build

# Stage 2: the Python app, which serves the API and the built front end.
FROM python:3.14.4-slim
COPY --from=ghcr.io/astral-sh/uv:0.13.7 /uv /usr/local/bin/uv
WORKDIR /app

# Dependencies first, so they are cached when only the code changes.
COPY pyproject.toml uv.lock .python-version ./
RUN uv sync --frozen --no-dev --no-install-project

COPY *.py ./
COPY data/ data/
COPY results/ results/
COPY --from=web /web/dist web/dist

# Run as an unprivileged user.
RUN useradd --create-home app
USER app

EXPOSE 8000
CMD ["/app/.venv/bin/uvicorn", "api:app", "--host", "0.0.0.0", "--port", "8000"]
