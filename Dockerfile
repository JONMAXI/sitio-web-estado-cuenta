# Usa una imagen ligera de Python
FROM python:3.11-slim

# Evita buffering de logs
ENV PYTHONUNBUFFERED=1
ENV PORT=8080

# Carpeta de trabajo
WORKDIR /app

# Copia requirements y instala dependencias
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copia el código fuente
COPY . .

# Ejecuta Flask
CMD ["python", "app.py"]
