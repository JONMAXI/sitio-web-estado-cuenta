from flask import Flask, render_template, request, redirect, session, url_for
import mysql.connector
import requests
from datetime import datetime
import hashlib
import os

app = Flask(__name__)
app.secret_key = 'clave_super_secreta'  # cámbiala por seguridad

# ------------------ CONFIGURACIÓN BASE DE DATOS ------------------

db_config = {
    'user': os.environ['DB_USER'],
    'password': os.environ['DB_PASSWORD'],
    'database': os.environ['DB_NAME'],
    'unix_socket': f"/cloudsql/{os.environ['DB_CONNECTION_NAME']}"
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
            error_msg = "Fecha inválida. Usa formato AAAA-MM-DD."
            return render_template("index.html", error=error_msg, fecha_actual_iso=fecha_corte)

        payload = {
            "idCredito": int(id_credito),
            "fechaCorte": fecha_corte
        }

        headers = {
            "Token": TOKEN,
            "Content-Type": "application/json"
        }

        res = requests.post(ENDPOINT, json=payload, headers=headers)

        try:
            data = res.json()
        except Exception:
            return render_template("resultado.html", error="Respuesta no válida del servidor", http=res.status_code)

        if res.status_code == 200 and "estadoCuenta" in data:
            return render_template("resultado.html", datos=data["estadoCuenta"])
        else:
            mensaje = data.get("mensaje", ["Error desconocido"])[0]
            return render_template("resultado.html", error=mensaje, http=res.status_code)

    fecha_actual_iso = datetime.now().strftime("%Y-%m-%d")
    return render_template("index.html", fecha_actual_iso=fecha_actual_iso)

# ------------------ APP ------------------

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8080))
    app.run(host="0.0.0.0", port=port)
