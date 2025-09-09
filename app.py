from flask import Flask, render_template, request, redirect, session
import mysql.connector
import requests
from datetime import datetime
import hashlib
import os

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

            # Calcular estatusPago
            for pago in estado_cuenta.get("datosPagos", []):
                try:
                    fecha_valor = datetime.strptime(pago["fechaValor"], "%Y-%m-%d")
                    fecha_registro = datetime.strptime(pago["fechaRegistro"], "%Y-%m-%d %H:%M:%S")
                    dias_atraso = (fecha_registro.date() - fecha_valor.date()).days
                except Exception:
                    dias_atraso = None

                if dias_atraso is not None:
                    pago["estatusPago"] = "Puntual" if dias_atraso <= 0 else f"Atraso de {dias_atraso} días"
                else:
                    pago["estatusPago"] = "No disponible"

            # ----------------- LOGICA PARA PAGOS AGRUPADOS POR CUOTA -----------------
            resultado = {}
            cuota_base = float(estado_cuenta.get("cuota", 0))

            for pago in estado_cuenta.get("datosPagos", []):
                cuotas = str(pago.get("numeroCuotaSemanal", "0")).split(",")
                monto_pago = float(pago.get("montoPago", 0))

                for i, cuota in enumerate(cuotas):
                    aplicado = min(monto_pago, cuota_base)
                    excedente = max(0, monto_pago - cuota_base) if i == 0 else monto_pago

                    pago_dict = {
                        "idPago": pago.get("idPago"),
                        "fecha": pago.get("fechaValor") or "",
 			"monto_pago": float(pago.get("montoPago", 0)),   # 👈 aquí lo agregas
                        "aplicado": aplicado,
                        "excedente": excedente
                    }

                    if cuota not in resultado:
                        resultado[cuota] = []
                    resultado[cuota].append(pago_dict)

                    monto_pago -= aplicado
                    if monto_pago <= 0:
                        break

            return render_template("resultado.html", datos=estado_cuenta, resultado=resultado)

        else:
            mensaje = data.get("mensaje", ["Error desconocido"])[0]
            return render_template("resultado.html", error=mensaje, http=res.status_code)

    fecha_actual_iso = datetime.now().strftime("%Y-%m-%d")
    return render_template("index.html", fecha_actual_iso=fecha_actual_iso)


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8080))
    app.run(host="0.0.0.0", port=port)
