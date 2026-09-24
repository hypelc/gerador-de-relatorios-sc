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
EXPOSE 8000
CMD ["sh", "-c", "exec uvicorn webapp.api:app --host 0.0.0.0 --port ${PORT:-8000}"]
