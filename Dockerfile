# Dockerfile (fixed)
FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PORT=8080 \
    WORK_DIR=/work

RUN apt-get update \
 && apt-get install -y --no-install-recommends git ca-certificates zip \
 && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

COPY app.py ./
EXPOSE 8080
VOLUME ["/work"]
CMD ["python", "app.py"]
