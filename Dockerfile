FROM python:3.9

WORKDIR /app

RUN apt-get update && apt-get install -y \
    unrar-free \
    fonts-liberation \
    && rm -rf /var/lib/apt/lists/* \
    && echo "Installed unrar-free at: $(which unrar-free)" > /app/unrar_install.log

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

CMD ["python", "bot.py"]
