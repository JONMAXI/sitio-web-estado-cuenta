# ----------------------------
# Etapa builder: instalar dependencias con pip
# ----------------------------
FROM python:3.11-slim-bullseye AS builder

# Variables de entorno
ENV PYTHONUNBUFFERED=1
ENV PORT=8080

WORKDIR /app

# Copiamos requirements y las instalamos
COPY requirements.txt .
RUN pip install --prefix=/install --no-cache-dir -r requirements.txt

# Copiamos el resto del código
COPY . .

# ----------------------------
# Etapa final: contenedor ligero y seguro (distroless)
# ----------------------------
FROM gcr.io/distroless/python3:python3.11-debian11

# Variables de entorno necesarias para Cloud Run
ENV PORT=8080
WORKDIR /app

# Copiamos dependencias y código desde la etapa builder
COPY --from=builder /install /usr/local
COPY --from=builder /app /app

# Comando de inicio (distroless no tiene shell)
CMD ["app.py"]
