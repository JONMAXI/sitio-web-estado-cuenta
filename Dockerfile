# Usamos una imagen oficial de Python que evita problemas de pull de Docker Hub
FROM python:3.11-slim-bullseye

# Variables de entorno
ENV PYTHONUNBUFFERED=1
ENV PORT=8080

# Directorio de trabajo
WORKDIR /app

# Copiamos y instalamos dependencias
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copiamos el resto del código
COPY . .

# Exponemos el puerto
EXPOSE 8080

# Comando por defecto
CMD ["python", "app.py"]
