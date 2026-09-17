# Works on Oracle Cloud, Northflank, Koyeb, Cloud Run, Fly, or any Docker host.
FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1
WORKDIR /app

COPY requirements.txt .
RUN pip install -r requirements.txt

COPY . .

# Non-root, and a writable place for state.json
RUN useradd -m tracker && mkdir -p /data && chown tracker /data
USER tracker
ENV STATE_FILE=/data/state.json

CMD ["python", "main.py"]
