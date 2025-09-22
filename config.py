import os
from google.cloud import storage

# ------------------ CONFIGURACIÓN BASE DE DATOS ------------------
DB_CONFIG = {
    'user': os.environ.get('DB_USER'),
    'password': os.environ.get('DB_PASSWORD'),
    'database': os.environ.get('DB_NAME'),
    'unix_socket': f"/cloudsql/{os.environ.get('DB_CONNECTION_NAME')}"
}

# ------------------ CONFIGURACIÓN API EXTERNA ------------------
TOKEN = "3oJVoAHtwWn7oBT4o340gFkvq9uWRRmpFo7p"
ENDPOINT = "https://servicios.s2movil.net/s2maxikash/estadocuenta"

# ------------------ CONFIGURACIÓN GOOGLE CLOUD STORAGE ------------------
GCS_BUCKET_NAME = "bucket_documentos"
GCS_CLIENT = storage.Client()
GCS_BUCKET = GCS_CLIENT.bucket(GCS_BUCKET_NAME)
