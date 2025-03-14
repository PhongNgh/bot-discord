FROM python:3.9

# Cài đặt unrar (phiên bản đầy đủ) và font
RUN apt-get update && apt-get install -y \
    unrar \
    fonts-liberation \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

CMD ["python", "bot.py"]
