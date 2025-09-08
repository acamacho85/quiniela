import sqlite3
import json
from flask import Flask, render_template, request, redirect, url_for, jsonify
from datetime import datetime, timedelta
from equipos_dict import EQUIPOS

# ============================================================
# Función de utilidad para obtener el slug del logo
# ============================================================
def get_logo_slug(nombre_equipo: str) -> str:
    return EQUIPOS.get(nombre_equipo, "default")

app = Flask(__name__)

DB_FILE = "database.db"

# ------------------ Funciones de ayuda ------------------
# -- Resultado real --

def resultado_real(resultado_str):
    try:
        goles = resultado_str.replace("–", "-").split("-")
        local = int(goles[0].strip())
        visitante = int(goles[1].strip())
        if local > visitante:
            return "local"
        elif visitante > local:
            return "visitante"
        else:
            return "empate"
    except Exception:
        return None

def init_db(force_reload=False):
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()

    if force_reload:
        cursor.execute("DROP TABLE IF EXISTS pronosticos")

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS pronosticos (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            usuario TEXT,
            partido_id INTEGER,
            pronostico TEXT CHECK(pronostico IN ('local','empate','visitante')),
            FOREIGN KEY(partido_id) REFERENCES partidos(id)
        )
    """)

    cursor.execute("SELECT COUNT(*) FROM jornadas")
    print(cursor.fetchone()[0])
    
    conn.commit()
    conn.close()

def obtener_partidos():
    conn = sqlite3.connect(DB_FILE)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM jornadas")
    datos = [dict(row) for row in cursor.fetchall()]
    conn.close()
    return datos

# ------------------ Rutas ------------------

@app.route("/")
def index():
    conn = sqlite3.connect(DB_FILE)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()

    cursor.execute("""
        SELECT DISTINCT jornada 
        FROM jornadas 
        ORDER BY CAST(substr(jornada, 9) AS INTEGER)
    """)
    jornadas = [row["jornada"] for row in cursor.fetchall()]

    calendario = {}
    for j in jornadas:
        cursor.execute("SELECT * FROM jornadas WHERE jornada = ?", (j,))
        calendario[j] = cursor.fetchall()

    conn.close()
    return render_template("index.html", calendario=calendario, jornadas=jornadas, EQUIPOS=EQUIPOS)

@app.route("/pronosticos", methods=["GET", "POST"])
def pronosticos():
    conn = sqlite3.connect(DB_FILE)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()

    cursor.execute("""
        SELECT DISTINCT jornada 
        FROM jornadas 
        ORDER BY CAST(substr(jornada, 9) AS INTEGER)
    """)
    jornadas = [row["jornada"] for row in cursor.fetchall()]

    # Filtrar solo jornadas con partidos futuros (más de 15 min antes del primer partido)
    jornadas_futuras = []
    for j in jornadas:
        cursor.execute("SELECT MIN(fechahora) AS primer_partido FROM jornadas WHERE jornada = ?", (j,))
        fila = cursor.fetchone()
        if fila and fila["primer_partido"]:
            primer_partido_dt = datetime.strptime(fila["primer_partido"], "%Y-%m-%d %H:%M:%S")
            if primer_partido_dt > datetime.now() + timedelta(minutes=15):
                jornadas_futuras.append(j)

    jornada_sel = request.args.get("jornada", jornadas_futuras[0] if jornadas_futuras else None)

    if request.method == "POST":
        usuario = request.form.get("usuario")
        cursor.execute("""
            DELETE FROM pronosticos 
            WHERE usuario = ? 
              AND partido_id IN (SELECT id FROM jornadas WHERE jornada = ?)
        """, (usuario, jornada_sel))

        cursor.execute("SELECT * FROM jornadas WHERE jornada = ?", (jornada_sel,))
        partidos = cursor.fetchall()
        for p in partidos:
            pron = request.form.get(f"partido_{p['id']}")
            if pron:
                cursor.execute("""
                    INSERT INTO pronosticos (usuario, partido_id, pronostico)
                    VALUES (?, ?, ?)
                """, (usuario, p["id"], pron))
        conn.commit()
        return redirect(url_for("pronosticos", jornada=jornada_sel, usuario=usuario))

    # GET → mostrar formulario
    cursor.execute("SELECT * FROM jornadas WHERE jornada = ?", (jornada_sel,))
    partidos = cursor.fetchall()

    # Obtener usuarios que tienen pronósticos en esta jornada
    cursor.execute("""
        SELECT DISTINCT usuario 
        FROM pronosticos
        WHERE partido_id IN (SELECT id FROM jornadas WHERE jornada = ?)
    """, (jornada_sel,))
    usuarios_existentes = [row["usuario"] for row in cursor.fetchall()]

    # Obtener pronósticos previos de todos los usuarios de la jornada
    pronosticos_previos = {}
    for u in usuarios_existentes:
        cursor.execute("""
            SELECT partido_id, pronostico FROM pronosticos
            WHERE usuario = ? AND partido_id IN (SELECT id FROM jornadas WHERE jornada = ?)
        """, (u, jornada_sel))
        pronosticos_previos[u] = {row["partido_id"]: row["pronostico"] for row in cursor.fetchall()}

    # No necesitamos resultados reales para capturar pronósticos futuros
    resultados_real = {}

    conn.close()
    return render_template(
        "pronosticos.html",
        partidos=partidos,
        jornadas=jornadas_futuras,
        jornada_sel=jornada_sel,
        usuarios_existentes=usuarios_existentes,
        pronosticos_previos=pronosticos_previos,
        resultados_real=resultados_real,
        EQUIPOS=EQUIPOS
    )

@app.route("/evaluacion")
def evaluacion():
    jornada_sel = request.args.get("jornada", None)

    conn = sqlite3.connect(DB_FILE)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()

    cursor.execute("SELECT DISTINCT jornada FROM jornadas ORDER BY CAST(substr(jornada, 9) AS INTEGER)")
    jornadas = [row["jornada"] for row in cursor.fetchall()]

    if jornada_sel:
        cursor.execute("""
            SELECT pr.usuario, p.local, p.visitante, p.resultado, pr.pronostico
            FROM pronosticos pr
            JOIN jornadas p ON pr.partido_id = p.id
            WHERE p.jornada = ?
            ORDER BY pr.usuario
        """, (jornada_sel,))
    else:
        cursor.execute("""
            SELECT pr.usuario, p.local, p.visitante, p.resultado, pr.pronostico
            FROM pronosticos pr
            JOIN jornadas p ON pr.partido_id = p.id
            ORDER BY pr.usuario
        """)

    rows = cursor.fetchall()
    conn.close()

    evaluacion = {}
    for r in rows:
        real = resultado_real(r["resultado"])
        correcto = (real == r["pronostico"])
        usuario = r["usuario"]

        if usuario not in evaluacion:
            evaluacion[usuario] = {"aciertos": 0, "total": 0, "detalle": []}

        evaluacion[usuario]["total"] += 1
        if correcto:
            evaluacion[usuario]["aciertos"] += 1

        evaluacion[usuario]["detalle"].append({
            "partido": f"{r['local']} vs {r['visitante']}",
            "resultado_real": real,
            "pronostico": r["pronostico"],
            "correcto": correcto
        })

    ranking = sorted(
        [(u, d["aciertos"]) for u, d in evaluacion.items()],
        key=lambda x: x[1],
        reverse=True
    )

    return render_template("evaluacion.html",
                           evaluacion=evaluacion,
                           ranking=ranking,
                           jornadas=jornadas,
                           jornada_sel=jornada_sel,
                           EQUIPOS=EQUIPOS)

@app.route("/api/partidos")
def api_partidos():
    return jsonify(obtener_partidos())

@app.context_processor
def utility_processor():
    return dict(get_logo_slug=get_logo_slug)

# ------------------ Main ------------------
if __name__ == "__main__":
    #init_db(force_reload=True)
    init_db()
    app.run(debug=True, port=5000, host="0.0.0.0")
