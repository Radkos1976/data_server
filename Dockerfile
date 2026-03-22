FROM python:3.12-slim

WORKDIR /app

# Instalacja systemowych zależności
RUN apt-get update && apt-get install -y \
    postgresql-client \
    && rm -rf /var/lib/apt/lists/*

# Kopiowanie requirements
COPY requirements.txt .

# Instalacja Python dependencies
RUN pip install --no-cache-dir -r requirements.txt

# Kopiowanie całej aplikacji
COPY . .

# Port na którym słucha aplikacja
EXPOSE 8000

# Domyślna komenda (może być nadpisana w docker-compose)
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]
