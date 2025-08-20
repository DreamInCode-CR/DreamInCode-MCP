# mcp/database.py
import pyodbc
from datetime import datetime, time, timedelta
import datetime as _dt  # para tipos date/datetime en normalizaciones


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
# Usuario / Enfermedades (EXISTENTE)
# -------------------------------------------------------------------
def obtener_enfermedades_usuario(usuario_id: int):
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
# Medicamentos – qué toca ahora (EXISTENTE)
# -------------------------------------------------------------------
def _weekday_flag_column(dt: datetime) -> str:
    return ["Lunes", "Martes", "Miercoles", "Jueves", "Viernes", "Sabado", "Domingo"][dt.weekday()]

def _time_to_minutes(t: time) -> int:
    return t.hour * 60 + t.minute

def get_due_meds(usuario_id: int, now_local: datetime, window_min: int = 5):
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
        print(f"[DB:get_due_meds] SQL error: {e}")
        return []

    for r in rows:
        diff = abs(_time_to_minutes(r.Hora) - now_min)
        if diff <= window_min:
            items.append({
                "usuario_nombre": getattr(r, "UsuarioNombre", None),
                "medicamento": r.Medicamento,
                "dosis": getattr(r, "Dosis", None),
                "instrucciones": getattr(r, "Instrucciones", None),
                "hora": r.Hora.strftime("%H:%M"),
            })
    return items


def get_all_meds(usuario_id: int) -> list[dict]:
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

            for f in ("Lunes", "Martes", "Miercoles", "Jueves", "Viernes", "Sabado", "Domingo", "Activo"):
                if f in rec and rec[f] is not None:
                    rec[f] = bool(rec[f])

            if rec.get("FechaInicio") and isinstance(rec["FechaInicio"], (_dt.date, _dt.datetime)):
                rec["FechaInicio"] = rec["FechaInicio"].isoformat()
            if rec.get("FechaHasta") and isinstance(rec["FechaHasta"], (_dt.date, _dt.datetime)):
                rec["FechaHasta"] = rec["FechaHasta"].isoformat()
            if rec.get("CreatedAt") and isinstance(rec["CreatedAt"], (_dt.date, _dt.datetime)):
                rec["CreatedAt"] = rec["CreatedAt"].isoformat()

            if rec.get("HoraToma"):
                ht = rec["HoraToma"]
                if isinstance(ht, _dt.time):
                    rec["HoraToma"] = ht.strftime("%H:%M")
                else:
                    rec["HoraToma"] = str(ht)

            rows_out.append(rec)
    return rows_out


# -------------------------------------------------------------------
# Citas médicas – NUEVO
# -------------------------------------------------------------------
def get_all_appointments(usuario_id: int) -> list[dict]:
    """
    Devuelve todas las citas del usuario (tabla dbo.CitasMedicas), normalizadas para JSON.
    """
    sql = """
    SELECT
        CitaID, UsuarioID, Titulo, Doctor, Lugar, Notas,
        Fecha, Hora, PreAvisoMinutos, Activo, CreatedAt
    FROM dbo.CitasMedicas
    WHERE UsuarioID = ?
    ORDER BY Fecha ASC, Hora ASC
    """
    out: list[dict] = []
    with get_connection() as cn:
        cur = cn.cursor()
        rs = cur.execute(sql, (usuario_id,))
        cols = [c[0] for c in cur.description]
        for row in rs.fetchall():
            rec = dict(zip(cols, row))
            rec["Activo"] = bool(rec.get("Activo", True))
            if isinstance(rec.get("Fecha"), _dt.date):
                rec["Fecha"] = rec["Fecha"].isoformat()
            if isinstance(rec.get("Hora"), _dt.time):
                rec["Hora"] = rec["Hora"].strftime("%H:%M")
            if isinstance(rec.get("CreatedAt"), (_dt.date, _dt.datetime)):
                rec["CreatedAt"] = rec["CreatedAt"].isoformat()
            out.append(rec)
    return out


def get_due_appointments(usuario_id: int, now_local: datetime, window_min: int = 5) -> list[dict]:
    """
    Devuelve citas que deben recordarse AHORA.
    Regla: now ≈ (Fecha + Hora - PreAvisoMinutos) con tolerancia ±window_min.
    """
    items: list[dict] = []

    sql = """
    SELECT
        c.CitaID, u.Nombre AS UsuarioNombre,
        c.Titulo, c.Doctor, c.Lugar, c.Notas,
        c.Fecha, c.Hora, c.PreAvisoMinutos, c.Activo
    FROM dbo.CitasMedicas AS c
    JOIN dbo.Usuarios     AS u ON u.UsuarioID = c.UsuarioID
    WHERE c.UsuarioID = ? AND c.Activo = 1
    """
    with get_connection() as cn:
        cur = cn.cursor()
        cur.execute(sql, (usuario_id,))
        for r in cur.fetchall():
            fecha = r.Fecha
            hora  = r.Hora
            pre   = int(r.PreAvisoMinutos or 0)
            cita_dt = datetime.combine(fecha, hora)
            target  = cita_dt - timedelta(minutes=pre)
            diff_min = abs(int((now_local - target).total_seconds() // 60))

            if diff_min <= window_min:
                items.append({
                    "usuario_nombre": getattr(r, "UsuarioNombre", None),
                    "cita_id": r.CitaID,
                    "titulo": r.Titulo,
                    "doctor": r.Doctor,
                    "lugar": r.Lugar,
                    "notas": r.Notas,
                    "fecha": fecha.isoformat(),
                    "hora": hora.strftime("%H:%M"),
                    "preaviso_min": pre
                })
    return items
