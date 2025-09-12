from flask import Flask, render_template, request, redirect, session, Response
import mysql.connector
import requests
from datetime import datetime, timedelta
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

# ------------------ PROCESAR ESTADO DE CUENTA ------------------
def procesar_estado_cuenta(estado_cuenta):
    cargos = estado_cuenta.get("datosCargos", []) or []
    pagos = estado_cuenta.get("datosPagos", []) or []

    pagos_list = []
    for p in pagos:
        try:
            monto_pago = float(p.get("montoPago", 0) or 0)
        except:
            monto_pago = 0.0
        cuotas = _parse_cuotas_field(p.get("numeroCuotaSemanal"))
        pagos_list.append({
            "idPago": p.get("idPago"),
            "remaining": monto_pago,
            "cuotas": cuotas,
            "fechaValor": p.get("fechaValor"),
            "fechaRegistro": p.get("fechaRegistro"),
            "montoPagoOriginal": monto_pago
        })

    cargos_sorted = sorted(cargos, key=lambda c: int(c.get("idCargo", 0)))
    pagos_por_cuota_index = {}
    for pago in pagos_list:
        for cnum in pago["cuotas"]:
            pagos_por_cuota_index.setdefault(cnum, []).append(pago)

    tabla = []

    for cargo in cargos_sorted:
        concepto = cargo.get("concepto", "")
        cuota_num = _extraer_numero_cuota(concepto)
        if cuota_num is None:
            cuota_num = int(cargo.get("idCargo", 0))

        monto_cargo = float(cargo.get("monto", 0) or 0)
        capital = float(cargo.get("capital", 0) or 0)
        interes = float(cargo.get("interes", 0) or 0)
        seguro_total = sum(float(cargo.get(k, 0) or 0) for k in ["seguroBienes","seguroVida","seguroDesempleo"])
        fecha_venc = cargo.get("fechaVencimiento", "")

        monto_restante_cargo = monto_cargo
        aplicados = []

        pagos_relacionados = pagos_por_cuota_index.get(cuota_num, [])
        pagos_relacionados_sorted = sorted(
            pagos_relacionados,
            key=lambda p: datetime.strptime(p["fechaRegistro"], "%Y-%m-%d %H:%M:%S") 
                          if p.get("fechaRegistro") 
                          else (datetime.min + timedelta(seconds=int(p.get("idPago", 0))))
        )

        for pago in pagos_relacionados_sorted:
            if monto_restante_cargo <= 0 or pago["remaining"] <= 0:
                continue

            aplicar = min(pago["remaining"], monto_restante_cargo)

            aplicados.append({
                "idPago": pago["idPago"],
                "montoPago": round(pago["remaining"], 2),
                "aplicado": round(aplicar, 2),
                "fechaRegistro": pago.get("fechaRegistro"),
                "fechaPago": fecha_venc,
                "diasMora": None
            })

            pago["remaining"] = round(pago["remaining"] - aplicar, 2)
            monto_restante_cargo = round(monto_restante_cargo - aplicar, 2)

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

    return sorted(tabla, key=lambda x: x["cuota"])

# ------------------ LOGIN ------------------
@app.route('/consultar', methods=['POST'])
def consultar():
    if 'usuario' not in session:
        return jsonify({"error": "No autorizado"}), 403

    try:
        id_credito = request.form.get("idCredito", "").strip()
        fecha_corte = request.form.get("fechaCorte", "").strip()

        if not id_credito.isdigit():
            return jsonify({"mensaje": "ID Crédito inválido. Debe ser un número entero"}), 400

        # Validar fecha
        try:
            datetime.strptime(fecha_corte, "%Y-%m-%d")
        except ValueError:
            return jsonify({"mensaje": "Fecha inválida. Usa formato AAAA-MM-DD"}), 400

        payload = {"idCredito": int(id_credito), "fechaCorte": fecha_corte}
        headers = {"Token": TOKEN, "Content-Type": "application/json"}
        res = requests.post(ENDPOINT, json=payload, headers=headers, timeout=15)
        data = res.json() if res.ok else {}

        # Manejo de errores API
        if res.status_code != 200 or data.get("http") != 200:
            mensaje = data.get("mensaje", ["Error desconocido"])
            return jsonify({"mensaje": mensaje[0]}), 400

        estado_cuenta = data.get("estadoCuenta")
        if not estado_cuenta or estado_cuenta.get("idCredito") is None:
            return jsonify({"mensaje": "El cliente no existe o no tiene datos disponibles"}), 200

        # Si existen datos
        return jsonify({
            "mensaje": "Cliente encontrado",
            "estadoCuenta": estado_cuenta
        })

    except Exception as e:
        return jsonify({"mensaje": f"Ocurrió un error inesperado: {str(e)}"}), 500

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
            data = res.json() if res.ok else None

            if not data or "estadoCuenta" not in data:
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

            return Response(pdf_bytes.read(), mimetype='application/pdf', headers={"Content-Disposition": f"inline; filename={id}_INE.pdf"})

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
                return "Cliente no encontrado en la Base de Datos", 404
            return Response(r.content, mimetype='application/pdf')

        else:
            return "Tipo de documento no válido", 400

    except Exception as e:
        return f"Cliente no encontrado en la Base de Datos", 500

# ------------------ PÁGINA DE CONSULTA DOCUMENTOS ------------------
@app.route('/documentos', methods=['GET', 'POST'])
def documentos():
    if 'usuario' not in session:
        return redirect('/login')
    return render_template("consulta_documentos.html")

# ------------------ INICIO ------------------
if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8080))
    app.run(host="0.0.0.0", port=port)
