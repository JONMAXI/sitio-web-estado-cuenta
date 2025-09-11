from flask import Flask, render_template, request, redirect, session, Response
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

# ------------------ UTIL / PROCESAMIENTO DE PAGOS ------------------
def _extraer_numero_cuota(concepto):
    """
    Intenta extraer el número de cuota desde el texto de concepto.
    Ej: "CUOTA SEMANAL 5 DE 156" -> 5
    """
    if not concepto:
        return None
    # Buscar primer número que represente la cuota (antes de 'DE' si existe)
    m = re.search(r'CUOTA.*?(\d+)\s+DE', concepto, re.IGNORECASE)
    if m:
        return int(m.group(1))
    # si no coincide, buscar cualquier número aislado
    m2 = re.search(r'(\d+)', concepto)
    if m2:
        return int(m2.group(1))
    return None

def _parse_cuotas_field(value):
    """Convierte '1,2' o 3 o '3' en lista de ints [1,2]"""
    if value is None:
        return []
    if isinstance(value, (int, float)):
        try:
            return [int(value)]
        except Exception:
            return []
    if isinstance(value, str):
        parts = [p.strip() for p in value.split(',') if p.strip() != ""]
        out = []
        for p in parts:
            try:
                out.append(int(p))
            except:
                pass
        return out
    return []

def procesar_estado_cuenta(estado_cuenta):
    """
    Devuelve una lista (tabla) con cada cuota (cargo) y sus pagos aplicados,
    pendiente y excedente.
    """
    cargos = estado_cuenta.get("datosCargos", []) or []
    pagos = estado_cuenta.get("datosPagos", []) or []

    # Normalizar y preparar pagos: calcular lista de cuotas que cada pago menciona,
    # y campo 'remaining' para distribuir el monto entre múltiples cuotas.
    pagos_list = []
    for p in pagos:
        try:
            monto_pago = float(p.get("montoPago", 0) or 0)
        except:
            monto_pago = 0.0
        cuotas = _parse_cuotas_field(p.get("numeroCuotaSemanal"))
        # parse fechas si existen
        fecha_valor = p.get("fechaValor")
        fecha_registro = p.get("fechaRegistro")
        pagos_list.append({
            "idPago": p.get("idPago"),
            "montoPagoOriginal": monto_pago,
            "remaining": monto_pago,
            "cuotas": cuotas,
            "fechaValor": fecha_valor,
            "fechaRegistro": fecha_registro,
            "raw": p  # guardamos original si hace falta en template
        })

    # Ordenamos cargos por idCargo o por fecha de vencimiento (si existe)
    def cargo_sort_key(c):
        # preferir idCargo si existe
        try:
            return int(c.get("idCargo", 0))
        except:
            # fallback a fecha
            return c.get("fechaVencimiento", "")
    cargos_sorted = sorted(cargos, key=cargo_sort_key)

    tabla = []
    # Para acelerar búsqueda, también construimos index de pagos por cuota (pero
    # usaremos la lista 'pagos_list' para respetar remaining)
    pagos_por_cuota_index = {}
    for pago in pagos_list:
        for cnum in pago["cuotas"]:
            pagos_por_cuota_index.setdefault(cnum, []).append(pago)

    # Iteramos cada cargo y distribuimos pagos que mencionen esa cuota
    for cargo in cargos_sorted:
        concepto = cargo.get("concepto", "")
        cuota_num = _extraer_numero_cuota(concepto)
        # Si no pudimos extraer cuota, intentamos con idCargo o saltamos
        if cuota_num is None:
            try:
                cuota_num = int(cargo.get("idCargo"))
            except:
                # si no hay numero, saltar el cargo
                continue

        monto_cargo = float(cargo.get("monto", 0) or 0)
        capital = float(cargo.get("capital", 0) or 0)
        interes = float(cargo.get("interes", 0) or 0)
        # sumar seguros (si vienen separados)
        seguro_bienes = float(cargo.get("seguroBienes", 0) or 0)
        seguro_vida = float(cargo.get("seguroVida", 0) or 0)
        seguro_desempleo = float(cargo.get("seguroDesempleo", 0) or 0)
        seguro_total = seguro_bienes + seguro_vida + seguro_desempleo
        fecha_venc = cargo.get("fechaVencimiento", "")

        monto_restante_cargo = monto_cargo
        aplicados = []  # lista de dicts {idPago, montoAplicado, montoPagoOriginal, fechaRegistro}

        # Tomar pagos que mencionen esta cuota, ordenarlos por fechaRegistro asc (si posible)
        pagos_relacionados = pagos_por_cuota_index.get(cuota_num, [])
        # Orden por fechaRegistro (fallback por idPago)
        def pago_key(p):
            fr = p.get("fechaRegistro")
            if fr:
                try:
                    return datetime.strptime(fr, "%Y-%m-%d %H:%M:%S")
                except:
                    pass
            return p.get("idPago", 0)
        pagos_relacionados_sorted = sorted(pagos_relacionados, key=pago_key)

        # Distribuir montos desde cada pago al cargo hasta completar
        for pago in pagos_relacionados_sorted:
            if monto_restante_cargo <= 0:
                break
            if pago["remaining"] <= 0:
                continue
            aplicar = min(pago["remaining"], monto_restante_cargo)
            if aplicar <= 0:
                continue
            # Registrar aplicación
            aplicados.append({
                "idPago": pago["idPago"],
                "montoAplicado": round(aplicar, 2),
                "montoPagoOriginal": round(pago["montoPagoOriginal"], 2),
                "fechaRegistro": pago.get("fechaRegistro"),
                "fechaValor": pago.get("fechaValor")
            })
            pago["remaining"] = round(pago["remaining"] - aplicar, 2)
            monto_restante_cargo = round(monto_restante_cargo - aplicar, 2)

        total_aplicado = round(monto_cargo - monto_restante_cargo, 2)
        pendiente = round(max(monto_cargo - total_aplicado, 0.0), 2)
        excedente = 0.0
        # Si por alguna razón total_aplicado > monto_cargo (no debería con esta lógica)
        if total_aplicado > monto_cargo:
            excedente = round(total_aplicado - monto_cargo, 2)

        tabla.append({
            "cuota": cuota_num,
            "fecha": fecha_venc,
            "monto_cargo": round(monto_cargo, 2),
            "capital": round(capital, 2),
            "interes": round(interes, 2),
            "seguro": round(seguro_total, 2),
            "aplicados": aplicados,            # lista de aplicaciones (posibles varios pagos)
            "total_pagado": total_aplicado,
            "pendiente": pendiente,
            "excedente": excedente,
            "raw_cargo": cargo
        })

    # opcional: ordenar tabla por cuota asc
    tabla = sorted(tabla, key=lambda x: x["cuota"])
    return tabla

# ------------------ LOGIN ------------------
@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        username = request.form['username']
        password = hashlib.sha256(request.form['password'].encode()).hexdigest()
        try:
            conn = mysql.connector.connect(**db_config)
            cur = conn.cursor(dictionary=True)
            cur.execute("SELECT * FROM usuarios WHERE username = %s AND password = %s", (username, password))
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

# ------------------ CONSULTA ------------------
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
        res = requests.post(ENDPOINT, json=payload, headers=headers)

        try:
            data = res.json()
        except Exception:
            return render_template("resultado.html", error="Respuesta no válida del servidor", http=res.status_code)

        if res.status_code == 200 and "estadoCuenta" in data:
            estado_cuenta = data["estadoCuenta"]

            # ------------------ PROCESAR PAGOS ------------------
            # Ahora usamos la función procesar_estado_cuenta para cruzar cargos y pagos
            tabla = procesar_estado_cuenta(estado_cuenta)

            # ------------------ FILTRAR NOTAS DE CARGOS (si aplica) ------------------
            cargos_pagados = []
            for nota in estado_cuenta.get("datosNotasCargos", []):
                if float(nota.get("montoAplicado", 0) or 0) > 0:
                    cargos_pagados.append(nota)

            return render_template(
                "resultado.html",
                datos=estado_cuenta,
                tabla=tabla,
                cargos_pagados=cargos_pagados
            )

        else:
            mensaje = data.get("mensaje", ["Error desconocido"])[0]
            return render_template("resultado.html", error=mensaje, http=res.status_code)

    fecha_actual_iso = datetime.now().strftime("%Y-%m-%d")
    return render_template("index.html", fecha_actual_iso=fecha_actual_iso)

# ------------------ DESCARGA / VISUALIZADOR ------------------
@app.route('/descargar/<id>')
def descargar(id):
    if 'usuario' not in session:
        return "No autorizado", 403

    tipo = request.args.get('tipo', 'INE')

    try:
        if tipo == 'INE':
            fecha_corte = datetime.now().strftime("%Y-%m-%d")
            payload = {"idCredito": int(id), "fechaCorte": fecha_corte}
            headers = {"Token": TOKEN, "Content-Type": "application/json"}
            res = requests.post(ENDPOINT, json=payload, headers=headers)
            data = res.json()

            if res.status_code != 200 or "estadoCuenta" not in data:
                return "Crédito no encontrado o sin datosCliente", 404

            idCliente = data["estadoCuenta"].get("datosCliente", {}).get("idCliente")
            if not idCliente:
                return "No se encontró idCliente para este crédito", 404

            url_frente = f"http://54.167.121.148:8081/s3/downloadS3File?fileName=INE/{idCliente}_frente.jpeg"
            url_reverso = f"http://54.167.121.148:8081/s3/downloadS3File?fileName=INE/{idCliente}_reverso.jpeg"

            r1 = requests.get(url_frente)
            r2 = requests.get(url_reverso)

            faltantes = []
            if r1.status_code != 200: faltantes.append("Frente")
            if r2.status_code != 200: faltantes.append("Reverso")
            if faltantes:
                return f"No se encontraron los archivos: {', '.join(faltantes)}", 404

            img1 = Image.open(BytesIO(r1.content)).convert("RGB")
            img2 = Image.open(BytesIO(r2.content)).convert("RGB")
            img1.info['dpi'] = (150, 150)
            img2.info['dpi'] = (150, 150)

            pdf_bytes = BytesIO()
            img1.save(pdf_bytes, format='PDF', save_all=True, append_images=[img2])
            pdf_bytes.seek(0)

            return Response(
                pdf_bytes.read(),
                mimetype='application/pdf',
                headers={"Content-Disposition": f"inline; filename={id}_INE.pdf"}
            )

        elif tipo == 'Otro 1':
            url = f"http://54.167.121.148:8081/s3/downloadS3File?fileName=CEP/{id}_cep.jpeg"
            r = requests.get(url)
            if r.status_code != 200:
                return "Archivo CEP no encontrado", 404
            return Response(r.content, mimetype='image/jpeg')

        elif tipo == 'Contrato':
            url = f"http://54.167.121.148:8081/s3/downloadS3File?fileName=VALIDACIONES/{id}_validaciones.pdf"
            r = requests.get(url)
            if r.status_code != 200:
                return "Archivo Contrato no encontrado", 404
            return Response(r.content, mimetype='application/pdf')

        else:
            return "Tipo de documento no válido", 400

    except Exception as e:
        return f"Error al procesar documento: {e}", 500

# ------------------ PÁGINA DE CONSULTA DOCUMENTOS ------------------
@app.route('/documentos', methods=['GET', 'POST'])
def documentos():
    if 'usuario' not in session:
        return redirect('/login')
    return render_template("consulta_documentos.html")

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8080))
    app.run(host="0.0.0.0", port=port)
