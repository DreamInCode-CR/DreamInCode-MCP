# mcp/database.py
import pyodbc
from datetime import datetime, time
import datetime  # módulo, usado para date/datetime en normalizaciones

# -------------------------------------------------------------------
# Conexión
# -------------------------------------------------------------------
def get_connection():
    conn = pyodbc.connect(
        "DRIVER={ODBC Driver 17 for SQL Server};"
        "SERVER=dreamincode.database.windows.net;"
        "DATABASE=DreamInCode;"
        "UID=Admin123;"
        "PWD=DreamInCode123;"
        "Encrypt=yes;"
        "TrustServerCertificate=no;"
        "Connection Timeout=30;"
    )
    return conn

# -------------------------------------------------------------------
# Usuario / Enfermedades
# -------------------------------------------------------------------
def obtener_enfermedades_usuario(usuario_id: int):
    """Devuelve lista de nombres de enfermedades del usuario."""
    with get_connection() as conn:
        cur = conn.cursor()
        cur.execute(
            """
            SELECT e.Nombre
            FROM dbo.UsuarioEnfermedad AS ue
            JOIN dbo.Enfermedades     AS e ON ue.EnfermedadID = e.EnfermedadID
            WHERE ue.UsuarioID = ?
            """,
            (usuario_id,),
        )
        return [row.Nombre for row in cur.fetchall()]

def obtener_datos_usuario(usuario_id: int):
    """
    Devuelve dict con datos básicos del usuario + enfermedades, o None si no existe.
      { nombre, edad, observaciones, enfermedades: [...] }
    """
    with get_connection() as conn:
        cur = conn.cursor()
        cur.execute(
            """
            SELECT Nombre, Edad, Observaciones
            FROM dbo.Usuarios
            WHERE UsuarioID = ?
            """,
            (usuario_id,),
        )
        row = cur.fetchone()

    if not row:
        return None

    enfermedades = obtener_enfermedades_usuario(usuario_id)
    return {
        "nombre": row.Nombre,
        "edad": row.Edad,
        "observaciones": row.Observaciones,
        "enfermedades": enfermedades,
    }

# -------------------------------------------------------------------
# Helpers y consulta para “qué medicamento toca ahora”
#   Ahora se usa SOLO dbo.Medicamentos (bits de día + HoraToma)
# -------------------------------------------------------------------
def _weekday_flag_column(dt_obj: datetime) -> str:
    """Lunes=0 ... Domingo=6 -> nombre de columna bit en la tabla Medicamentos."""
    return ["Lunes", "Martes", "Miercoles", "Jueves", "Viernes", "Sabado", "Domingo"][dt_obj.weekday()]

def _time_to_minutes(t: time) -> int:
    return t.hour * 60 + t.minute

def get_due_meds(usuario_id: int, now_local: datetime, window_min: int = 5):
    """
    Devuelve una lista de medicamentos que 'tocan' ahora (± window_min minutos)
    para el usuario dado, leyendo de dbo.Medicamentos y respetando:
      - Activo
      - FechaInicio / FechaHasta (si vienen)
      - bits Lunes..Domingo
      - HoraToma

    Estructura del item:
      {
        "usuario_nombre": None,
        "medicamento": str,
        "dosis": str | None,
        "instrucciones": str | None,
        "hora": "HH:MM"
      }
    """
    day_col = _weekday_flag_column(now_local)
    now_min = now_local.hour * 60 + now_local.minute
    items = []

    sql = """
    SELECT
        NombreMedicamento,
        Dosis,
        Instrucciones,
        FechaInicio,
        FechaHasta,
        Lunes, Martes, Miercoles, Jueves, Viernes, Sabado, Domingo,
        Activo,
        HoraToma
    FROM dbo.Medicamentos
    WHERE UsuarioID = ?
    """
    try:
        with get_connection() as conn:
            cur = conn.cursor()
            rows = cur.execute(sql, (usuario_id,)).fetchall()
    except pyodbc.Error as e:
        print(f"[DB:get_due_meds] SQL error: {e}")
        return []

    today = now_local.date()
    for r in rows:
        # Activo
        try:
            if r.Activo is not None and int(r.Activo) == 0:
                continue
        except Exception:
            pass

        # Rango de fechas (permitir nulos)
        fi = getattr(r, "FechaInicio", None)
        fh = getattr(r, "FechaHasta", None)
        if isinstance(fi, datetime.datetime):
            fi = fi.date()
        if isinstance(fh, datetime.datetime):
            fh = fh.date()
        if fi and today < fi:
            continue
        if fh and today > fh:
            continue

        # Día de semana
        if not getattr(r, day_col, False):
            continue

        # Hora en ventana
        ht = getattr(r, "HoraToma", None)
        if not isinstance(ht, time):
            continue
        if abs(_time_to_minutes(ht) - now_min) > window_min:
            continue

        items.append({
            "usuario_nombre": None,
            "medicamento": getattr(r, "NombreMedicamento", "") or "",
            "dosis": getattr(r, "Dosis", None),
            "instrucciones": getattr(r, "Instrucciones", None),
            "hora": ht.strftime("%H:%M"),
        })

    return items

# -------------------------------------------------------------------
# Listado completo de medicamentos por usuario (tabla dbo.Medicamentos)
# -------------------------------------------------------------------
def get_all_meds(usuario_id: int) -> list[dict]:
    """
    Lee todas las columnas de dbo.Medicamentos para el UsuarioID dado.
    Normaliza tipos para JSON (bool, fechas ISO, hora HH:mm).
    """
    sql = """
    SELECT
        MedicamentoID,
        UsuarioID,
        NombreMedicamento,
        Dosis,
        Instrucciones,
        FechaInicio,
        FechaHasta,
        Lunes, Martes, Miercoles, Jueves, Viernes, Sabado, Domingo,
        Activo,
        CreatedAt,
        HoraToma
    FROM dbo.Medicamentos
    WHERE UsuarioID = ?
    ORDER BY Activo DESC, NombreMedicamento ASC, HoraToma ASC
    """

    rows_out: list[dict] = []

    with get_connection() as cn:
        cur = cn.cursor()
        rs = cur.execute(sql, (usuario_id,))
        cols = [c[0] for c in cur.description]

        for row in rs.fetchall():
            rec = dict(zip(cols, row))

            # bits -> bool
            for f in ("Lunes", "Martes", "Miercoles", "Jueves", "Viernes", "Sabado", "Domingo", "Activo"):
                if f in rec and rec[f] is not None:
                    rec[f] = bool(rec[f])

            # fechas -> ISO
            if rec.get("FechaInicio") and isinstance(rec["FechaInicio"], (datetime.date, datetime.datetime)):
                rec["FechaInicio"] = rec["FechaInicio"].isoformat()
            if rec.get("FechaHasta") and isinstance(rec["FechaHasta"], (datetime.date, datetime.datetime)):
                rec["FechaHasta"] = rec["FechaHasta"].isoformat()
            if rec.get("CreatedAt") and isinstance(rec["CreatedAt"], (datetime.date, datetime.datetime)):
                rec["CreatedAt"] = rec["CreatedAt"].isoformat()

            # hora -> HH:mm
            if rec.get("HoraToma"):
                ht = rec["HoraToma"]
                if isinstance(ht, time):
                    rec["HoraToma"] = ht.strftime("%H:%M")
                else:
                    rec["HoraToma"] = str(ht)

            rows_out.append(rec)

    return rows_out
