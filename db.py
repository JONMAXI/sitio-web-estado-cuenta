# db.py
import os
import mysql.connector
from mysql.connector import Error

def get_connection(database=None):
    """
    Retorna una conexión a la base de datos usando variables de entorno
    y ajusta la zona horaria a America/Mexico_City.
    
    Parámetros:
        database (str): nombre de la base de datos a usar. Si es None, usa la principal.
    """
    db_config = {
        'user': os.environ.get('DB_USER'),
        'password': os.environ.get('DB_PASSWORD'),
        'database': database if database else os.environ.get('DB_NAME'),
        'unix_socket': f"/cloudsql/{os.environ.get('DB_CONNECTION_NAME')}"
    }
    try:
        conn = mysql.connector.connect(**db_config)
        cursor = conn.cursor()
        cursor.execute("SET time_zone = 'America/Mexico_City';")
        cursor.close()
        return conn
    except Error as e:
        print(f"[DB ERROR] No se pudo conectar a la base de datos {db_config['database']}: {e}")
        return None
