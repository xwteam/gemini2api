FROM mcr.microsoft.com/playwright/python:v1.44.0-jammy

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends fonts-wqy-zenhei curl \
    && rm -rf /var/lib/apt/lists/*

RUN pip install --no-cache-dir playwright==1.44.0 requests

COPY refresher.py .

CMD ["python", "refresher.py"]
