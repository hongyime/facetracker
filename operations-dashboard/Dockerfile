FROM node:22-alpine AS frontend-dependencies
WORKDIR /app/frontend
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci

FROM frontend-dependencies AS frontend-dev
RUN chown -R node:node /app/frontend
USER node
EXPOSE 3000
CMD ["npm", "run", "dev", "--", "--host", "0.0.0.0"]

FROM frontend-dependencies AS frontend-build
COPY frontend/ ./
RUN npm run build

FROM python:3.12-slim AS backend-builder
RUN apt-get update && apt-get install -y --no-install-recommends gcc \
    && rm -rf /var/lib/apt/lists/*
COPY backend/requirements.txt /tmp/requirements.txt
RUN python -m venv /opt/venv \
    && /opt/venv/bin/pip install --no-cache-dir -r /tmp/requirements.txt

FROM python:3.12-slim AS dependencies
ENV PATH="/opt/venv/bin:${PATH}" PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
COPY --from=backend-builder /opt/venv /opt/venv
WORKDIR /app/backend
RUN useradd -u 1001 -m opsuser && chown -R opsuser:opsuser /app

FROM dependencies AS dev
RUN pip install --no-cache-dir watchfiles==1.3.0
USER opsuser
EXPOSE 8700
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8700", "--reload", "--reload-dir", "/app/backend"]

FROM dependencies AS production
COPY backend/ /app/backend/
COPY --from=frontend-build /app/frontend/dist /app/backend/static
USER opsuser
EXPOSE 8700
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8700"]
