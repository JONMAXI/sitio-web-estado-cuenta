from flask import Flask, render_template, request, redirect, session, Response
import mysql.connector
import requests
from datetime import datetime
import hashlib
import os
from io import BytesIO
from PIL import Image

app = Flask(__name__)
app.secret_key = 'clave_super_secreta'

# ------------------ CONFIGURACIÓN BASE DE DATOS ------------------
db_config = {
    'host': '34.9.147.5',
    'user': 'jonathan',
    'password': ')1>SbilQ,$VKr=hO',
    'database': 'estado_cuenta'
}

# ------------------ CONFIGURACIÓN API EXTERNA ------------------
TOKEN = "3oJVoAHtwWn7oBT4o340gFkvq9uWRRmpFo7p"
ENDPOINT = "https://servicios.s2movil.net/s2maxikash/estadocuenta"

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
            resultado = {}
            cuota_base = float(estado_cuenta.get("cuota", 0))

            # Historial global de excedentes por idPago
            excedente_historial_global = {}

            for pago in estado_cuenta.get("datosPagos", []):
                cuotas = str(pago.get("numeroCuotaSemanal", "0")).split(",")
                monto_pago = float(pago.get("montoPago", 0))

                try:
                    fecha_valor = datetime.strptime(pago["fechaValor"], "%Y-%m-%d")
                    fecha_registro = datetime.strptime(pago["fechaRegistro"], "%Y-%m-%d %H:%M:%S")
                    dias_mora_pago = (fecha_registro.date() - fecha_valor.date()).days
                except Exception:
                    dias_mora_pago = None

                for i, cuota in enumerate(cuotas):
                    aplicado = min(monto_pago, cuota_base)
                    excedente = max(0, monto_pago - cuota_base) if i == 0 else monto_pago

                    # Revisar si ya mostramos este excedente para este idPago
                    mostrar_monto = monto_pago
                    if pago.get("idPago") in excedente_historial_global:
                        if excedente_historial_global[pago["idPago"]] == excedente:
                            mostrar_monto = 0
                    else:
                        excedente_historial_global[pago["idPago"]] = excedente

                    pago_dict = {
                        "idPago": pago.get("idPago"),
                        "fechaPago": pago.get("fechaValor") or "",
                        "fechaRegistro": pago.get("fechaRegistro") or "",
                        "montoPago": mostrar_monto,
                        "aplicado": aplicado,
                        "excedente": excedente,
                        "diasMora": dias_mora_pago if i == 0 else None
                    }

                    if cuota not in resultado:
                        resultado[cuota] = []
                    resultado[cuota].append(pago_dict)

                    monto_pago -= aplicado
                    if monto_pago <= 0:
                        break

            # ------------------ FILTRAR SOLO PAGOS CON APLICADO > 0 ------------------
            resultado_filtrado = {}
            for cuota, pagos in resultado.items():
                pagos_con_aplicado = [p for p in pagos if p['aplicado'] > 0 or p['montoPago'] > 0 or p['excedente'] > 0]
                if pagos_con_aplicado:
                    resultado_filtrado[cuota] = pagos_con_aplicado

            # ------------------ FILTRAR NOTAS DE CARGOS ------------------
            cargos_pagados = []
            for nota in estado_cuenta.get("datosNotasCargos", []):
                if float(nota.get("montoAplicado", 0)) > 0:
                    cargos_pagados.append(nota)

            return render_template(
                "resultado.html",
                datos=estado_cuenta,
                resultado=resultado_filtrado,
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
