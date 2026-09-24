FROM node:22-alpine AS frontend-build
WORKDIR /build
COPY frontend/package.json frontend/package-lock.json ./frontend/
RUN npm ci --prefix frontend
COPY frontend/index.html frontend/vite.config.js ./frontend/
COPY frontend/src ./frontend/src
RUN npm run build --prefix frontend

FROM python:3.14-slim
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    MPLBACKEND=Agg
WORKDIR /app
COPY requirements-web.txt ./
RUN pip install --no-cache-dir -r requirements-web.txt
COPY gerador_sc ./gerador_sc
COPY geodados ./geodados
COPY webapp ./webapp
COPY --from=frontend-build /build/frontend/dist ./frontend/dist
EXPOSE 8000
CMD ["sh", "-c", "exec uvicorn webapp.api:app --host 0.0.0.0 --port ${PORT:-8000}"]
