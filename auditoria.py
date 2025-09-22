import mysql.connector
from config import DB_CONFIG

def auditar_estado_cuenta(usuario, id_credito, fecha_corte, exito, mensaje_error=None):
    try:
        conn = mysql.connector.connect(**DB_CONFIG)
        cur = conn.cursor()
        cur.execute("""
            INSERT INTO auditoria_estado_cuenta (usuario, id_credito, fecha_corte, exito, mensaje_error)
            VALUES (%s, %s, %s, %s, %s)
        """, (usuario, id_credito, fecha_corte, exito, mensaje_error))
        conn.commit()
        cur.close()
        conn.close()
    except Exception as e:
        print(f"[AUDITORIA] Error: {e}")

def auditar_documento(usuario, documento_clave, documento_nombre, id_referencia, exito, mensaje_error=None):
    try:
        conn = mysql.connector.connect(**DB_CONFIG)
        cur = conn.cursor()
        cur.execute("""
            INSERT INTO auditoria_documentos (usuario, documento_clave, documento_nombre, id_referencia, exito, mensaje_error)
            VALUES (%s, %s, %s, %s, %s, %s)
        """, (usuario, documento_clave, documento_nombre, id_referencia, exito, mensaje_error))
        conn.commit()
        cur.close()
        conn.close()
    except Exception as e:
        print(f"[AUDITORIA] Error: {e}")
