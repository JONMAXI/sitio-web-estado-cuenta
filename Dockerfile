# Usa una imagen base oficial con Python
FROM python:3.11-slim

# Establece el directorio de trabajo
WORKDIR /app

# Copia los archivos del proyecto al contenedor
COPY . /app

# Instala dependencias
RUN pip install --no-cache-dir -r requirements.txt

# Expone el puerto usado por Flask
ENV PORT=8080
EXPOSE 8080

# Comando para correr la app
CMD ["python", "app.py"]
