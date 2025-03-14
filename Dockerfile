FROM python:3.9

# Thiết lập thư mục làm việc
WORKDIR /app

# Cập nhật hệ thống và cài đặt các phần mềm cần thiết
RUN apt-get update && \
    apt-get install -y unrar-free fonts-liberation && \
    rm -rf /var/lib/apt/lists/* && \
    echo "Installed unrar-free at: $(which unrar-free)" > /app/unrar_install.log

# Sao chép requirements.txt và cài đặt các thư viện Python
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Sao chép toàn bộ mã nguồn vào container
COPY . .

# Chạy bot
CMD ["python", "bot.py"]
