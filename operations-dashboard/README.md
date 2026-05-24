# Operations Dashboard Framework

A generic, reusable dashboard template for backend systems.

## Features
- **Frontend**: React + Vite + TypeScript + TailwindCSS
- **Backend**: FastAPI (Python)
- **Deployment**: Single Docker container (multi-stage build)
- **Real-time**: WebSocket integration for health status
- **Components**: Reusable DataTables, MetricCards, StatusBadges, etc.

## Setup
### Local Development
**Frontend**:
```sh
cd frontend
npm install
npm run dev
```

**Backend**:
```sh
cd backend
pip install -r requirements.txt
uvicorn main:app --reload --port 8700
```

### Docker Deployment
```sh
docker-compose up --build -d
```