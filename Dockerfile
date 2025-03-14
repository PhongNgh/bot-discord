FROM python:3.11-slim-bookworm

RUN apt-get update && apt-get install -y \
    p7zip-full \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY . .

RUN pip install -r requirements.txt

CMD ["python", "bot.py"]
