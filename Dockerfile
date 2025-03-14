# Sử dụng image Python slim làm base
FROM python:3.9-slim

# Cài đặt unrar (cần thiết cho rarfile)
RUN apt-get update && apt-get install -y unrar

# Tạo thư mục làm việc trong container
WORKDIR /app

# Copy requirements.txt và cài đặt dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy toàn bộ code vào container
COPY . .

# Chạy bot khi container khởi động
CMD ["python", "bot.py"]
