# ----------------------------
# Etapa builder
# ----------------------------
FROM python:3.11-slim-bullseye AS builder

ENV PYTHONUNBUFFERED=1
ENV PORT=8080
WORKDIR /app

COPY requirements.txt .
RUN pip install --prefix=/install --no-cache-dir -r requirements.txt
COPY . .

# ----------------------------
# Etapa final (distroless)
# ----------------------------
FROM gcr.io/distroless/python3:3.11

ENV PORT=8080
WORKDIR /app

COPY --from=builder /install /usr/local
COPY --from=builder /app /app

CMD ["app.py"]
