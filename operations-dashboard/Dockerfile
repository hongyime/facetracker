# Stage 1: Build Frontend
FROM node:20-alpine as frontend-build
WORKDIR /app/frontend
COPY frontend/package*.json ./
RUN npm install
COPY frontend/ ./
RUN npm run build

# Stage 2: Build Backend and serve Frontend
FROM python:3.12-slim
WORKDIR /app

# System dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    && rm -rf /var/lib/apt/lists/*

# Python dependencies
COPY backend/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy backend code
COPY backend/ ./backend/

# Copy frontend build to static folder
RUN mkdir -p /app/backend/static
COPY --from=frontend-build /app/frontend/dist /app/backend/static

# Mount static files in main.py by modifying it if necessary, or just serve it.
# Assuming we will serve the static files in the backend.

EXPOSE 8700

# Create non-root user
RUN useradd -m opsuser && chown -R opsuser:opsuser /app
USER opsuser

WORKDIR /app/backend
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8700"]