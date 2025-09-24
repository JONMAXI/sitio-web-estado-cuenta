from flask import Flask, render_template, request, redirect, session, Response
import requests
from datetime import datetime
import hashlib
import os
from io import BytesIO
from PIL import Image
import re
from db import get_connection  # <-- Importamos la conexión centralizada

app = Flask(__name__)
app.secret_key = 'clave_super_secreta'

# ------------------ CONFIGURACIÓN API EXTERNA ------------------
TOKEN = "3oJVoAHtwWn7oBT4o340gFkvq9uWRRmpFo7p"
ENDPOINT = "https://servicios.s2movil.net/s2maxikash/estadocuenta"

# ------------------ UTILIDADES ------------------
def _extraer_numero_cuota(concepto):
    if not concepto:
        return None
    m = re.search(r'CUOTA.*?(\d+)\s+DE', concepto, re.IGNORECASE)
    if m:
        return int(m.group(1))
    m2 = re.search(r'(\d+)', concepto)
    if m2:
        return int(m2.group(1))
    return None

def _parse_cuotas_field(value):
    if value is None:
        return []
    if isinstance(value, (int, float)):
        return [int(value)]
    if isinstance(value, str):
        parts = [p.strip() for p in value.split(',') if p.strip()]
        out = []
        for p in parts:
            try:
                out.append(int(p))
            except:
                pass
        return out
    return []

def safe_float(value, default=0.0):
    try:
        return float(value)
    except (ValueError, TypeError):
        return default

def safe_int(value, default=0):
    try:
        return int(value)
    except (ValueError, TypeError):
        return default

def safe_date(date_str, fmt="%Y-%m-%d %H:%M:%S"):
    try:
        return datetime.strptime(date_str, fmt)
    except (ValueError, TypeError):
        return None

# ------------------ FUNCIONES DE AUDITORÍA ------------------
def auditar_estado_cuenta(usuario, id_credito, fecha_corte, exito, mensaje_error=None):
    try:
        with get_connection() as conn:
            if not conn:
                return
            cur = conn.cursor()
            cur.execute("""
                INSERT INTO auditoria_estado_cuenta (usuario, id_credito, fecha_corte, exito, mensaje_error)
                VALUES (%s, %s, %s, %s, %s)
            """, (usuario, id_credito, fecha_corte, exito, mensaje_error))
            conn.commit()
            cur.close()
    except Exception as e:
        print(f"[AUDITORIA] Error registrando estado de cuenta: {e}")

def auditar_documento(usuario, documento_clave, documento_nombre, id_referencia, exito, mensaje_error=None):
    try:
        with get_connection() as conn:
            if not conn:
                return
            cur = conn.cursor()
            cur.execute("""
                INSERT INTO auditoria_documentos (usuario, documento_clave, documento_nombre, id_referencia, exito, mensaje_error)
                VALUES (%s, %s, %s, %s, %s, %s)
            """, (usuario, documento_clave, documento_nombre, id_referencia, exito, mensaje_error))
            conn.commit()
            cur.close()
    except Exception as e:
        print(f"[AUDITORIA] Error registrando documento: {e}")

# ------------------ FUNCIONES DE PROCESAMIENTO ------------------
def procesar_estado_cuenta(estado_cuenta):
    """
    Función mínima para procesar estado de cuenta.
    Retorna los datos tal cual (puedes adaptar luego).
    """
    return estado_cuenta

def buscar_credito_por_nombre(nombre):
    """
    Busca créditos por nombre en la base definida en la variable DB_NAME_CLIENTES.
    Retorna una lista de diccionarios con id_credito y nombre completo.
    """
    db_clientes = os.environ.get('DB_NAME_CLIENTES')
    if not db_clientes:
        print("[DB ERROR] Variable de entorno DB_NAME_CLIENTES no definida")
        return []

    query = """
        SELECT id_credito, id_cliente, Nombre_cliente, Fecha_inicio
        FROM lista_cliente
        WHERE Nombre_cliente LIKE %s
        LIMIT 1000
    """
    resultados = []
    with get_connection(db_clientes) as conn:
        if conn:
            cursor = conn.cursor(dictionary=True)
            cursor.execute(query, (f"%{nombre}%",))
            resultados = cursor.fetchall()
            cursor.close()
    return resultados

# ------------------ RUTAS ------------------
@app.route('/', methods=['GET', 'POST'])
def index():
    if 'usuario' not in session:
        return redirect('/login')

    fecha_actual_iso = datetime.now().strftime("%Y-%m-%d")

    if request.method == 'POST':
        nombre_busqueda = request.form.get('nombre', '').strip()
        id_credito_form = request.form.get('idCredito', '').strip()
        fecha_corte = request.form.get('fechaCorte', fecha_actual_iso).strip()

        try:
            datetime.strptime(fecha_corte, "%Y-%m-%d")
        except ValueError:
            return render_template("index.html", error="Fecha inválida", fecha_actual_iso=fecha_corte)

        resultados = []
        if nombre_busqueda:
            resultados = buscar_credito_por_nombre(nombre_busqueda)
            if not resultados:
                return render_template("index.html", error="No se encontraron créditos con ese nombre", fecha_actual_iso=fecha_corte)
            if len(resultados) == 1:
                id_credito = resultados[0]['id_credito']
            else:
                return render_template("index.html", resultados=resultados, fecha_actual_iso=fecha_corte)
        elif id_credito_form:
            id_credito = int(id_credito_form)
        else:
            return render_template("index.html", error="Debes proporcionar nombre o ID de crédito", fecha_actual_iso=fecha_corte)

        # Consulta al API externa
        payload = {"idCredito": int(id_credito), "fechaCorte": fecha_corte}
        headers = {"Token": TOKEN, "Content-Type": "application/json"}
        try:
            res = requests.post(ENDPOINT, json=payload, headers=headers, timeout=15)
            data = res.json()
        except Exception:
            auditar_estado_cuenta(session['usuario']['username'], id_credito, fecha_corte, 0, "Respuesta no válida del servidor")
            return render_template("resultado.html", error="Respuesta no válida del servidor")

        if res.status_code != 200 or "estadoCuenta" not in data:
            mensaje = data.get("mensaje", ["Error desconocido"])[0] if data else "No se encontraron datos para este crédito"
            auditar_estado_cuenta(session['usuario']['username'], id_credito, fecha_corte, 0, mensaje)
            return render_template("resultado.html", error=mensaje)

        estado_cuenta = data["estadoCuenta"]
        if not any([estado_cuenta.get("idCredito"), estado_cuenta.get("datosCliente"), estado_cuenta.get("datosCargos"), estado_cuenta.get("datosPagos")]):
            auditar_estado_cuenta(session['usuario']['username'], id_credito, fecha_corte, 0, "Crédito vacío")
            return render_template("resultado.html", usuario_no_existe=True)

        auditar_estado_cuenta(session['usuario']['username'], id_credito, fecha_corte, 1, None)
        tabla = procesar_estado_cuenta(estado_cuenta)
        return render_template("resultado.html", datos=estado_cuenta, resultado=tabla)

    return render_template("index.html", fecha_actual_iso=fecha_actual_iso)

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        username = request.form['username']
        password = hashlib.sha256(request.form['password'].encode()).hexdigest()
        try:
            with get_connection() as conn:
                if not conn:
                    return "Error de conexión a la base de datos", 500
                cur = conn.cursor(dictionary=True)
                cur.execute("SELECT * FROM usuarios WHERE username = %s AND password = %s", (username, password))
                user = cur.fetchone()
                cur.close()
        except Exception as err:
            return f"Error de conexión a MySQL: {err}"

        if user:
            session['usuario'] = {
                'username': user['username'],
                'nombre_completo': user['nombre_completo'],
                'puesto': user['puesto'],
                'grupo': user['grupo']
            }
            return redirect('/')
        else:
            return render_template("login.html", error="Credenciales inválidas")
    return render_template("login.html")

@app.route('/logout')
def logout():
    session.pop('usuario', None)
    return redirect('/login')

@app.route('/documentos', methods=['GET', 'POST'])
def documentos():
    if 'usuario' not in session:
        return redirect('/login')
    return render_template("consulta_documentos.html")

# ------------------ DESCARGA DE DOCUMENTOS ------------------
@app.route('/descargar/<id>')
def descargar(id):
    if 'usuario' not in session:
        return "No autorizado", 403

    tipo = request.args.get('tipo', 'INE')
    usuario = session['usuario']['username']

    try:
        if tipo == 'INE':
            fecha_corte = datetime.now().strftime("%Y-%m-%d")
            payload = {"idCredito": int(id), "fechaCorte": fecha_corte}
            headers = {"Token": TOKEN, "Content-Type": "application/json"}
            res = requests.post(ENDPOINT, json=payload, headers=headers)
            data = res.json() if res.ok else None

            if not data or "estadoCuenta" not in data:
                auditar_documento(usuario, "INE", "INE completo", id, 0, "Crédito no encontrado o sin datosCliente")
                return "Crédito no encontrado o sin datosCliente", 404

            idCliente = data["estadoCuenta"].get("datosCliente", {}).get("idCliente")
            if not idCliente:
                auditar_documento(usuario, "INE", "INE completo", id, 0, "No se encontró idCliente")
                return "No se encontró idCliente para este crédito", 404

            url_frente = f"http://54.167.121.148:8081/s3/downloadS3File?fileName=INE/{idCliente}_frente.jpeg"
            url_reverso = f"http://54.167.121.148:8081/s3/downloadS3File?fileName=INE/{idCliente}_reverso.jpeg"
            r1 = requests.get(url_frente)
            r2 = requests.get(url_reverso)

            faltantes = []
            if r1.status_code != 200:
                faltantes.append("Frente")
            if r2.status_code != 200:
                faltantes.append("Reverso")
            if faltantes:
                auditar_documento(usuario, "INE", "INE completo", id, 0, f"No se encontraron los archivos: {', '.join(faltantes)}")
                return f"No se encontraron los archivos: {', '.join(faltantes)}", 404

            img1 = Image.open(BytesIO(r1.content)).convert("RGB")
            img2 = Image.open(BytesIO(r2.content)).convert("RGB")
            img1.info['dpi'] = (150, 150)
            img2.info['dpi'] = (150, 150)
            pdf_bytes = BytesIO()
            img1.save(pdf_bytes, format='PDF', save_all=True, append_images=[img2])
            pdf_bytes.seek(0)

            auditar_documento(usuario, "INE", "INE completo", id, 1, None)
            return Response(
                pdf_bytes.read(),
                mimetype='application/pdf',
                headers={"Content-Disposition": f"inline; filename={id}_INE.pdf"}
            )
        else:
            auditar_documento(usuario, tipo, tipo, id, 0, "Tipo de documento no válido")
            return "Tipo de documento no válido", 400
    except Exception as e:
        auditar_documento(usuario, tipo, tipo, id, 0, f"Error interno: {e}")
        return "Cliente no encontrado en la Base de Datos", 500

# ------------------ INICIO ------------------
if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8080))
    app.run(host="0.0.0.0", port=port)
