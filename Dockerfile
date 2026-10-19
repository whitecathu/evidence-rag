FROM node:22-alpine AS frontend
WORKDIR /web
COPY web/package*.json ./
RUN npm ci
COPY web/ ./
RUN npm run build
FROM python:3.11-slim
WORKDIR /app
RUN pip install --no-cache-dir uv==0.11.18
COPY . .
RUN uv sync --frozen --no-dev
COPY --from=frontend /web/dist ./web/dist
EXPOSE 8000
CMD ["uv", "run", "--no-sync", "uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
