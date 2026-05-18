FROM python:3.11-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

EXPOSE 8080

CMD exec gunicorn --bind :8080 --workers 2 --threads 1 --worker-class sync --timeout 600 --graceful-timeout 30 --chdir src reisekosten_backend:app