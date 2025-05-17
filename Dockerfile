FROM python:3.11-slim-bookworm

# Thiết lập thư mục làm việc
WORKDIR /app

# Copy mã nguồn vào container
COPY . .

# Cài đặt các thư viện Python từ requirements.txt
RUN pip install --no-cache-dir -r requirements.txt

# Chạy bot
CMD ["python", "bot.py"]
