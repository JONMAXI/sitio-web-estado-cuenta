# db_queries.py
from db import get_connection

def obtener_datos_cliente(id_oferta: int):
    """
    Obtiene información del cliente y sus referencias desde la DB3
    usando el id_oferta (que corresponde al id_credito).
    """
    query = """
        SELECT 
            o.id_oferta, 
            CONCAT(p.primer_nombre, ' ', p.apellido_paterno, ' ', p.apellido_materno) AS nombre_completo,
            CONCAT(p2.nombre_referencia1, ' ', p2.apellido_paterno_referencia1, ' ', p2.apellido_materno_referencia1) AS nombre_completo_referencia1,
            p2.telefono_referencia1,
            CONCAT(p2.nombre_referencia2, ' ', p2.apellido_paterno_referencia2, ' ', p2.apellido_materno_referencia2) AS nombre_completo_referencia2,
            p2.telefono_referencia2, 
            '' as nombre_referencia_3, 
            '' as telefono_referencia_3
        FROM oferta o
        INNER JOIN persona p ON o.fk_persona = p.id_persona
        LEFT JOIN persona_adicionales p2 ON p2.fk_persona = p.id_persona
        WHERE o.id_oferta = %s
    """
    with get_connection(database="maxi-prod") as conn:  # DB3
        if not conn:
            return None
        cursor = conn.cursor(dictionary=True)
        cursor.execute(query, (id_oferta,))
        row = cursor.fetchone()
        cursor.close()
        return row
