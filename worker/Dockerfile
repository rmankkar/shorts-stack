FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1
ENV PYTHONDONTWRITEBYTECODE=1

RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        ffmpeg \
        bash \
        fontconfig \
        fonts-dejavu-core \
        coreutils \
    && rm -rf /var/lib/apt/lists/*

RUN python -m venv /opt/shorts-venv

RUN /opt/shorts-venv/bin/pip install --no-cache-dir \
    fastapi \
    uvicorn \
    edge-tts

RUN mkdir -p /data /opt/shorts-scripts

WORKDIR /app

COPY app.py /app/app.py

EXPOSE 8000

CMD ["/opt/shorts-venv/bin/uvicorn", "app:app", "--host", "0.0.0.0", "--port", "8000"]
