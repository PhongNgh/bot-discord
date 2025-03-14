FROM python:3.9-slim

# Cài đặt unrar-free thay vì unrar
RUN apt-get update && apt-get install -y unrar-free

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

CMD ["python", "bot.py"]
