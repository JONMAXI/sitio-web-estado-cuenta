FROM gcr.io/distroless/python3:3.11
WORKDIR /app

# Copiamos dependencias y código
COPY requirements.txt .
COPY . .

# Instalación de dependencias (con pip, usando un builder temporal)
# Si quieres mantener pip, usamos multi-stage build:

# Etapa builder
FROM python:3.11-slim-bullseye AS builder
WORKDIR /app
COPY requirements.txt .
RUN pip install --prefix=/install --no-cache-dir -r requirements.txt

# Etapa final distroless
FROM gcr.io/distroless/python3:3.11
WORKDIR /app
COPY --from=builder /install /usr/local
COPY . .

CMD ["app.py"]