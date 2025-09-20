from flask import Flask, render_template, request, redirect, session, Response, send_file
import mysql.connector
import requests
from datetime import datetime
import hashlib
import os
from io import BytesIO
from PIL import Image
import re

app = Flask(__name__)
app.secret_key = 'clave_super_secreta'

# ------------------ CONFIGURACIÓN BASE DE DATOS ------------------
db_config = {
    'user': os.environ.get('DB_USER'),
    'password': os.environ.get('DB_PASSWORD'),
    'database': os.environ.get('DB_NAME'),
    'unix_socket': f"/cloudsql/{os.environ.get('DB_CONNECTION_NAME')}"
}

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
    """Registra en auditoria_estado_cuenta"""
    try:
        conn = mysql.connector.connect(**db_config)
        cur = conn.cursor()
        cur.execute("""
            INSERT INTO auditoria_estado_cuenta (usuario, id_credito, fecha_corte, exito, mensaje_error)
            VALUES (%s, %s, %s, %s, %s)
        """, (usuario, id_credito, fecha_corte, exito, mensaje_error))
        conn.commit()
        cur.close()
        conn.close()
    except Exception as e:
        print(f"[AUDITORIA] Error registrando estado de cuenta: {e}")

def auditar_documento(usuario, documento_clave, documento_nombre, id_referencia, exito, mensaje_error=None):
    """Registra en auditoria_documentos"""
    try:
        conn = mysql.connector.connect(**db_config)
        cur = conn.cursor()
        cur.execute("""
            INSERT INTO auditoria_documentos (usuario, documento_clave, documento_nombre, id_referencia, exito, mensaje_error)
            VALUES (%s, %s, %s, %s, %s, %s)
        """, (usuario, documento_clave, documento_nombre, id_referencia, exito, mensaje_error))
        conn.commit()
        cur.close()
        conn.close()
    except Exception as e:
        print(f"[AUDITORIA] Error registrando documento: {e}")

# ------------------ PROCESAR ESTADO DE CUENTA ------------------
def procesar_estado_cuenta(estado_cuenta):
    try:
        cargos = estado_cuenta.get("datosCargos") or []
        if not isinstance(cargos, list):
            cargos = []
        pagos = estado_cuenta.get("datosPagos") or []
        if not isinstance(pagos, list):
            pagos = []

        pagos_list = []
        for p in pagos:
            monto_pago = safe_float(p.get("montoPago"), 0.0)
            cuotas = _parse_cuotas_field(p.get("numeroCuotaSemanal"))
            pagos_list.append({
                "idPago": p.get("idPago"),
                "remaining": monto_pago,
                "cuotas": cuotas,
                "fechaValor": p.get("fechaValor"),
                "fechaRegistro": p.get("fechaRegistro"),
                "montoPagoOriginal": monto_pago
            })

        cargos_sorted = sorted(cargos, key=lambda c: safe_int(c.get("idCargo"), 0))
        pagos_por_cuota_index = {}
        for pago in pagos_list:
            for cnum in pago["cuotas"]:
                pagos_por_cuota_index.setdefault(cnum, []).append(pago)

        tabla = []
        for cargo in cargos_sorted:
            concepto = cargo.get("concepto", "")
            cuota_num = _extraer_numero_cuota(concepto)
            if cuota_num is None:
                cuota_num = safe_int(cargo.get("idCargo"))

            monto_cargo = safe_float(cargo.get("monto"))
            capital = safe_float(cargo.get("capital"))
            interes = safe_float(cargo.get("interes"))
            seguro_total = sum(safe_float(cargo.get(k)) for k in ["seguroBienes","seguroVida","seguroDesempleo"])
            fecha_venc = cargo.get("fechaVencimiento")

            monto_restante_cargo = monto_cargo
            aplicados = []

            pagos_relacionados = pagos_por_cuota_index.get(cuota_num, [])
            pagos_relacionados_sorted = sorted(
                pagos_relacionados,
                key=lambda p: safe_date(p.get("fechaRegistro")) or datetime.min
            )

            for pago in pagos_relacionados_sorted:
                if monto_restante_cargo <= 0 or pago["remaining"] <= 0:
                    continue
                aplicar = min(pago["remaining"], monto_restante_cargo)
                aplicados.append({
                    "idPago": pago.get("idPago"),
                    "montoPago": round(pago["remaining"], 2),
                    "aplicado": round(aplicar, 2),
                    "fechaRegistro": pago.get("fechaRegistro"),
                    "fechaPago": fecha_venc,
                    "diasMora": None
                })
                pago["remaining"] = max(round(pago["remaining"] - aplicar, 2), 0)
                monto_restante_cargo = max(round(monto_restante_cargo - aplicar, 2), 0)

            total_aplicado = round(monto_cargo - monto_restante_cargo, 2)
            pendiente = round(max(monto_cargo - total_aplicado, 0.0), 2)
            excedente = max(round(total_aplicado - monto_cargo, 2), 0.0)

            tabla.append({
                "cuota": cuota_num,
                "fecha": fecha_venc,
                "monto_cargo": round(monto_cargo, 2),
                "capital": round(capital, 2),
                "interes": round(interes, 2),
                "seguro": round(seguro_total, 2),
                "aplicados": aplicados,
                "total_pagado": total_aplicado,
                "pendiente": pendiente,
                "excedente": excedente,
                "raw_cargo": cargo
            })

        return sorted(tabla, key=lambda x: safe_int(x["cuota"]))
    except Exception as e:
        print(f"[ERROR] procesar_estado_cuenta: {e}")
        return []

# ------------------ LOGIN ------------------
@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        username = request.form['username']
        password = hashlib.sha256(request.form['password'].encode()).hexdigest()
        try:
            conn = mysql.connector.connect(**db_config)
            cur = conn.cursor(dictionary=True)
            cur.execute(
                "SELECT * FROM usuarios WHERE username = %s AND password = %s",
                (username, password)
            )
            user = cur.fetchone()
            cur.close()
            conn.close()
        except mysql.connector.Error as err:
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

# ------------------ CONSULTA ESTADO DE CUENTA ------------------
@app.route('/', methods=['GET', 'POST'])
def index():
    if 'usuario' not in session:
        return redirect('/login')

    if request.method == 'POST':
        id_credito = request.form['idCredito']
        fecha_corte = request.form['fechaCorte'].strip()
        try:
            datetime.strptime(fecha_corte, "%Y-%m-%d")
        except ValueError:
            return render_template("index.html", error="Fecha inválida. Usa formato AAAA-MM-DD.", fecha_actual_iso=fecha_corte)

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

        if (
            not estado_cuenta.get("idCredito")
            and not estado_cuenta.get("datosCliente")
            and not estado_cuenta.get("datosCargos")
            and not estado_cuenta.get("datosPagos")
        ):
            auditar_estado_cuenta(session['usuario']['username'], id_credito, fecha_corte, 0, "Crédito vacío")
            return render_template("resultado.html", usuario_no_existe=True)

        auditar_estado_cuenta(session['usuario']['username'], id_credito, fecha_corte, 1, None)
        tabla = procesar_estado_cuenta(estado_cuenta)
        return render_template("resultado.html", datos=estado_cuenta, resultado=tabla)

    fecha_actual_iso = datetime.now().strftime("%Y-%m-%d")
    return render_template("index.html", fecha_actual_iso=fecha_actual_iso)

# ------------------ DESCARGA / VISUALIZADOR ------------------
@app.route('/descargar/<id>')
def descargar(id):
    if 'usuario' not in session:
        return "No autorizado", 403

    # 🔹 Ejemplo: archivo dummy para descarga (reemplazar por tu lógica real)
    try:
        # Crear archivo en memoria
        buffer = BytesIO()
        buffer.write(b"Contenido de ejemplo del archivo para id: %s" % id.encode())
        buffer.seek(0)
        return send_file(buffer, as_attachment=True, download_name=f"archivo_{id}.txt", mimetype="text/plain")
    except Exception as e:
        return f"Error al generar el archivo: {e}", 500

# ------------------ CONSULTA DOCUMENTOS ------------------
@app.route('/documentos', methods=['GET', 'POST'])
def documentos():
    if 'usuario' not in session:
        return redirect('/login')

    if request.method == 'POST':
        documento_clave = request.form.get("documento_clave")
        documento_nombre = request.form.get("documento_nombre")
        id_referencia = request.form.get("id_referencia")

        # 🔹 Simulación de búsqueda de documento (reemplazar por tu lógica real)
        encontrado = False
        if encontrado:
            auditar_documento(session['usuario']['username'], documento_clave, documento_nombre, id_referencia, 1, None)
            return render_template("consulta_documentos.html", exito=True)
        else:
            auditar_documento(session['usuario']['username'], documento_clave, documento_nombre, id_referencia, 0, "Documento no encontrado")
            return render_template("consulta_documentos.html", error="Documento no encontrado")

    return render_template("consulta_documentos.html")

# ------------------ INICIO ------------------
if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8080))
    app.run(host="0.0.0.0", port=port)
