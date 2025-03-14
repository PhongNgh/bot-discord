FROM python:3.9

# Thiết lập thư mục làm việc
WORKDIR /app

# Cập nhật hệ thống và thêm khóa công khai
RUN apt-get update && \
    apt-get install -y gnupg software-properties-common && \
    apt-key adv --keyserver keyserver.ubuntu.com --recv-keys 3B4FE6ACC0B21F32 871920D1991BC93C && \
    echo "deb http://archive.ubuntu.com/ubuntu focal main universe" >> /etc/apt/sources.list && \
    apt-get update && \
    apt-get install -y \
        unrar \
        fonts-liberation \
    && rm -rf /var/lib/apt/lists/* \
    && echo "Installed unrar at: $(which unrar)" > /app/unrar_install.log

# Sao chép requirements.txt và cài đặt các thư viện Python
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Sao chép toàn bộ mã nguồn vào container
COPY . .

# Chạy bot
CMD ["python", "bot.py"]
