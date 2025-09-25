# ----------------------------
# Etapa builder: instalar dependencias
# ----------------------------
FROM python:3.11-slim-bullseye AS builder

ENV PYTHONUNBUFFERED=1
ENV PORT=8080

WORKDIR /app

COPY requirements.txt .
RUN pip install --prefix=/install --no-cache-dir -r requirements.txt

COPY . .

# ----------------------------
# Etapa final: contenedor distroless para producción
# ----------------------------
FROM gcr.io/distroless/python3:python3.11

# Puerto para Cloud Run
ENV PORT=8080
WORKDIR /app

# Copiamos dependencias y código
COPY --from=builder /install /usr/local
COPY --from=builder /app /app

# Comando de inicio
CMD ["app.py"]
