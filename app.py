from flask import Flask, render_template, g, redirect, url_for
import sqlite3

DATABASE = "escolar.db"

app = Flask(__name__)

def get_db():
    db = getattr(g, '_database', None)
    if db is None:
        db = g._database = sqlite3.connect(DATABASE)
        db.row_factory = sqlite3.Row
    return db

@app.teardown_appcontext
def close_connection(exception):
    db = getattr(g, '_database', None)
    if db is not None:
        db.close()

@app.route("/")
def index():
    db = get_db()
    alumnos = db.execute("SELECT * FROM alumnos").fetchall()
    return render_template("index.html", alumnos=alumnos)

@app.route("/alumno/<int:alumno_id>")
def alumno_detalle(alumno_id):
    db = get_db()
    alumno = db.execute(
        "SELECT * FROM alumnos WHERE id_alumno = ?", (alumno_id,)
    ).fetchone()
    
    # Todas las asignaturas
    asignaturas = db.execute("SELECT * FROM asignaturas").fetchall()
    
    # Calificaciones del alumno por materia y unidad
    calificaciones = db.execute("""
        SELECT aa.id_asignatura, aa.unidad, aa.calificacion
        FROM alumnos_asignaturas aa
        WHERE aa.id_alumno = ?
        ORDER BY aa.id_asignatura, aa.unidad
    """, (alumno_id,)).fetchall()
    
    # Promedios generales por asignatura (de promedios_asignaturas)
    proms = db.execute("""
        SELECT id_asignatura, promedio
        FROM promedios_asignaturas
    """).fetchall()
    proms_dict = {p["id_asignatura"]: p["promedio"] for p in proms}
    
    # Organizar calificaciones por asignatura
    materias = []
    for asig in asignaturas:
        califs = [c for c in calificaciones if c["id_asignatura"] == asig["id_asignatura"]]
        unidades = [c["unidad"] for c in califs]
        califs_por_unidad = {c["unidad"]: c["calificacion"] for c in califs}
        max_unidad = max(unidades) if unidades else 0
        promedio_general = proms_dict.get(asig["id_asignatura"], None)
        materias.append({
            "descripcion": asig["descripcion"],
            "unidades": list(range(1, max_unidad+1)),
            "califs_por_unidad": califs_por_unidad,
            "promedio_general": promedio_general
        })
    
    return render_template("alumno.html", alumno=alumno, materias=materias)

@app.route("/calcular-promedios")
def calcular_promedios():
    db = get_db()
    cur = db.cursor()
    
    # 1. Limpiar tablas destino para evitar duplicados
    cur.execute("DELETE FROM competencias")
    cur.execute("DELETE FROM promedios_asignaturas")

    # 2. Calcular promedio de cada alumno por cada asignatura
    cur.execute("""
        SELECT id_alumno, id_asignatura, AVG(calificacion) as promedio
        FROM alumnos_asignaturas
        GROUP BY id_alumno, id_asignatura
    """)
    competencias = cur.fetchall()

    # Obtener acrónimos de asignaturas
    acronimos = {}
    for row in cur.execute("SELECT id_asignatura, SUBSTR(descripcion, 1, 2) as acronimo FROM asignaturas"):
        acronimos[row["id_asignatura"]] = row["acronimo"].upper()

    # Insertar en tabla competencias
    for c in competencias:
        promedio = round(c["promedio"], 1)
        acronimo = acronimos.get(c["id_asignatura"], "NA")
        cur.execute("""
            INSERT INTO competencias (promedio, acronimo, id_asignatura, id_alumno)
            VALUES (?, ?, ?, ?)
        """, (promedio, acronimo, c["id_asignatura"], c["id_alumno"]))

    # 3. Calcular promedio general por asignatura
    cur.execute("""
        SELECT id_asignatura, AVG(calificacion) as promedio
        FROM alumnos_asignaturas
        GROUP BY id_asignatura
    """)
    promedios_asignatura = cur.fetchall()

    # Insertar en tabla promedios_asignatura
    for p in promedios_asignatura:
        promedio = round(p["promedio"], 1)
        cur.execute("""
            INSERT INTO promedios_asignaturas (promedio, id_asignatura)
            VALUES (?, ?)
        """, (promedio, p["id_asignatura"]))

    db.commit()
    return "<h2>¡Promedios calculados y guardados exitosamente!</h2><a href='/'>Volver al inicio</a>"

@app.route("/calcular-indicadores")
def calcular_indicadores():
    db = get_db()
    cur = db.cursor()
    
    # Limpiar tabla para evitar duplicados
    cur.execute("DELETE FROM indicadores_rendimiento")
    
    # Obtener todos los alumnos
    alumnos = cur.execute("SELECT id_alumno FROM alumnos").fetchall()
    
    for alu in alumnos:
        id_alumno = alu["id_alumno"]
        semestrales = 0
        parciales = 0
        
        # Obtener todas las asignaturas del alumno
        asignaturas = cur.execute("""
            SELECT id_asignatura FROM alumnos_asignaturas
            WHERE id_alumno = ?
            GROUP BY id_asignatura
        """, (id_alumno,)).fetchall()
        
        for asig in asignaturas:
            id_asig = asig["id_asignatura"]
            # Obtener calificaciones de las 3 unidades
            califs = cur.execute("""
                SELECT unidad, calificacion
                FROM alumnos_asignaturas
                WHERE id_alumno = ? AND id_asignatura = ?
                ORDER BY unidad
            """, (id_alumno, id_asig)).fetchall()
            calif_values = [c["calificacion"] for c in califs]
            if len(calif_values) != 3:
                continue  # Salta asignaturas incompletas
            
            promedio = sum(calif_values) / 3
            if promedio < 80:
                semestrales += 1
            else:
                parciales += sum(1 for c in calif_values if c < 80)
        
        # Guardar resultado para el alumno
        cur.execute("""
            INSERT INTO indicadores_rendimiento 
                (id_alumno, cantidad_semestrales, cantidad_parciales)
            VALUES (?, ?, ?)
        """, (id_alumno, semestrales, parciales))
    
    db.commit()
    # Redirige directamente a la vista de ingresos después de calcular indicadores
    return redirect(url_for('calcular_ingresos'))


@app.route("/calcular-ingresos")
def calcular_ingresos():
    db = get_db()
    cur = db.cursor()
    
    # Limpiar la tabla ingresos para evitar duplicados
    cur.execute("DELETE FROM ingresos")
    
    # Recuperar información de todos los alumnos y sus indicadores
    indicadores = cur.execute("""
        SELECT id_alumno, cantidad_parciales, cantidad_semestrales
        FROM indicadores_rendimiento
    """).fetchall()
    
    for ind in indicadores:
        id_alumno = ind["id_alumno"]
        parciales = ind["cantidad_parciales"] or 0
        semestrales = ind["cantidad_semestrales"] or 0
        
        costo_parciales = parciales * 100
        costo_semestrales = semestrales * 350
        costo_total = costo_parciales + costo_semestrales
        
        cur.execute("""
            INSERT INTO ingresos (costo_parciales, costo_semestrales, costo_total, id_alumno)
            VALUES (?, ?, ?, ?)
        """, (costo_parciales, costo_semestrales, costo_total, id_alumno))
    
    db.commit()

    # Ahora prepara los datos para la tabla ingresos, uniendo con los datos del alumno y los indicadores
    ingresos = cur.execute("""
        SELECT a.nombre, a.apellido_paterno, a.apellido_materno, 
               ir.cantidad_parciales, i.costo_parciales, 
               ir.cantidad_semestrales, i.costo_semestrales, 
               i.costo_total
        FROM ingresos i
        JOIN alumnos a ON a.id_alumno = i.id_alumno
        JOIN indicadores_rendimiento ir ON ir.id_alumno = a.id_alumno
        ORDER BY a.apellido_paterno, a.apellido_materno, a.nombre
    """).fetchall()

    # Renderiza la plantilla de ingresos
    return render_template("ingresos.html", ingresos=ingresos)

from flask import render_template

@app.route("/calcular-competencias-generales")
def calcular_competencias_generales():
    db = get_db()
    cur = db.cursor()

    # Opcional: Limpia las competencias generales si existen (donde id_alumno IS NULL)
    cur.execute("DELETE FROM competencias WHERE id_alumno IS NULL")

    # Leer promedios generales por asignatura
    promedios = cur.execute("""
        SELECT id_asignatura, promedio
        FROM promedios_asignaturas
    """).fetchall()

    def obtener_acronimo(prom):
        if prom >= 90:
            return "AU"   # AUTONOMO
        elif prom >= 80:
            return "SO"   # SOBRESALIENTE
        elif prom >= 70:
            return "RE"   # REGULAR
        else:
            return "NC"   # NO COMPETENTE

    for p in promedios:
        promedio = p["promedio"]
        id_asignatura = p["id_asignatura"]
        acronimo = obtener_acronimo(promedio)
        cur.execute("""
            INSERT INTO competencias (promedio, acronimo, id_asignatura, id_alumno)
            VALUES (?, ?, ?, NULL)
        """, (promedio, acronimo, id_asignatura))

    db.commit()
    competencias = cur.execute("""
        SELECT 
            'LUIS ANGEL PEREZ LOPEZ' AS nombre_alumno, 
            nombre AS nombre_asignatura, 
            promedio, 
            acronimo
        FROM competencias c
        JOIN asignaturas a ON a.id = c.id_asignatura
        WHERE id_alumno IS NULL
    """).fetchall()

    competencias = [dict(row) for row in competencias]

    return render_template("competencias_generales.html", competencias=competencias)

if __name__ == "__main__":
    app.run(debug=True)