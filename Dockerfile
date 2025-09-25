# Etapa builder: instalar dependencias
FROM python:3.11-slim-bullseye AS builder

WORKDIR /app
COPY requirements.txt .
RUN pip install --prefix=/install --no-cache-dir -r requirements.txt
COPY . .

# Etapa final: usar python oficial de GCP
FROM gcr.io/distroless/python3:python3.11-debian11

WORKDIR /app
ENV PORT=8080

COPY --from=builder /install /usr/local
COPY --from=builder /app /app

CMD ["app.py"]
