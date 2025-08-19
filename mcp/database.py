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
#   Requiere las tablas:
#   - dbo.Medicamentos
#   - dbo.UsuarioMedicacion
#   - dbo.UsuarioMedicacionHorario
# -------------------------------------------------------------------
def _weekday_flag_column(dt: datetime) -> str:
    """Lunes=0 ... Domingo=6 -> nombre de columna bit en la tabla horario."""
    return ["Lunes", "Martes", "Miercoles", "Jueves", "Viernes", "Sabado", "Domingo"][dt.weekday()]


def _time_to_minutes(t: time) -> int:
    return t.hour * 60 + t.minute


def get_due_meds(usuario_id: int, now_local: datetime, window_min: int = 5):
    """
    Devuelve una lista de medicamentos que 'tocan' ahora (± window_min minutos)
    para el usuario dado, considerando día de semana y hora local.

    Estructura del item:
      {
        "usuario_nombre": str | None,
        "medicamento": str,
        "dosis": str | None,
        "instrucciones": str | None,
        "hora": "HH:MM"
      }
    """
    day_col = _weekday_flag_column(now_local)
    now_min = now_local.hour * 60 + now_local.minute
    items = []

    sql = f"""
    SELECT u.Nombre AS UsuarioNombre,
           m.Nombre AS Medicamento,
           um.Dosis,
           um.Instrucciones,
           h.Hora,
           h.Lunes, h.Martes, h.Miercoles, h.Jueves, h.Viernes, h.Sabado, h.Domingo
    FROM dbo.UsuarioMedicacion AS um
    JOIN dbo.Medicamentos      AS m  ON m.MedicamentoID = um.MedicamentoID
    JOIN dbo.UsuarioMedicacionHorario AS h ON h.UsuarioMedicacionID = um.UsuarioMedicacionID
    JOIN dbo.Usuarios          AS u  ON u.UsuarioID = um.UsuarioID
    WHERE um.UsuarioID = ?
      AND um.Activo = 1
      AND h.Activo = 1
      AND (CASE ?
            WHEN 'Lunes'     THEN h.Lunes
            WHEN 'Martes'    THEN h.Martes
            WHEN 'Miercoles' THEN h.Miercoles
            WHEN 'Jueves'    THEN h.Jueves
            WHEN 'Viernes'   THEN h.Viernes
            WHEN 'Sabado'    THEN h.Sabado
            WHEN 'Domingo'   THEN h.Domingo
          END) = 1
    """

    try:
        with get_connection() as conn:
            cur = conn.cursor()
            cur.execute(sql, (usuario_id, day_col))
            rows = cur.fetchall()
    except pyodbc.Error as e:
        # Si las tablas aún no existen, evita romper la API
        print(f"[DB:get_due_meds] SQL error: {e}")
        return []

    for r in rows:
        # r.Hora es datetime.time
        diff = abs(_time_to_minutes(r.Hora) - now_min)
        if diff <= window_min:
            items.append({
                "usuario_nombre": getattr(r, "UsuarioNombre", None),
                "medicamento": r.Medicamento,
                "dosis": getattr(r, "Dosis", None),
                "instrucciones": getattr(r, "Instrucciones", None),
                "hora": r.Hora.strftime("%H:%M"),
            })

    # <-- ¡Faltaba este return dentro de la función!
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

    with get_connection() as cn:  # <- corregido (antes decía get_conn)
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
                if isinstance(ht, datetime.time):
                    rec["HoraToma"] = ht.strftime("%H:%M")
                else:
                    rec["HoraToma"] = str(ht)

            rows_out.append(rec)

    return rows_out
