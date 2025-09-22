# db.py
import os
import mysql.connector
from mysql.connector import Error

def get_connection():
    """Retorna una conexión a la base de datos usando variables de entorno."""
    db_config = {
        'user': os.environ.get('DB_USER'),
        'password': os.environ.get('DB_PASSWORD'),
        'database': os.environ.get('DB_NAME'),
        'unix_socket': f"/cloudsql/{os.environ.get('DB_CONNECTION_NAME')}"
    }
    try:
        conn = mysql.connector.connect(**db_config)
        return conn
    except Error as e:
        print(f"[DB ERROR] No se pudo conectar a la base de datos: {e}")
        return None
