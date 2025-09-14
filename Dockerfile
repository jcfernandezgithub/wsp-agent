FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1       PYTHONUNBUFFERED=1

WORKDIR /app

# Sistema base
RUN apt-get update && apt-get install -y --no-install-recommends       build-essential     && rm -rf /var/lib/apt/lists/*

# Dependencias
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

# Código
COPY . .

# Puerto (Railway/Render establecen $PORT)
ENV PORT=8000
EXPOSE 8000

# Gunicorn (WSGI)
CMD gunicorn -w 2 -k gthread -t 60 -b 0.0.0.0:$PORT server:app
