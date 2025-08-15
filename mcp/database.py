import pyodbc

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

    
def obtener_enfermedades_usuario(usuario_id):
    conn = get_connection()
    cursor = conn.cursor()

    cursor.execute("""
        SELECT E.Nombre
        FROM UsuarioEnfermedad UE
        JOIN Enfermedades E ON UE.EnfermedadID = E.EnfermedadID
        WHERE UE.UsuarioID = ?
    """, usuario_id)

    enfermedades = [row.Nombre for row in cursor.fetchall()]
    conn.close()
    return enfermedades


def obtener_datos_usuario(usuario_id):
    conn = get_connection()
    cursor = conn.cursor()

    cursor.execute("""
        SELECT Nombre, Edad, Observaciones 
        FROM dbo.Usuarios 
        WHERE UsuarioID = ?
    """, usuario_id)

    row = cursor.fetchone()
    conn.close()

    if row:
        enfermedades = obtener_enfermedades_usuario(usuario_id)
        return {
            "nombre": row.Nombre,
            "edad": row.Edad,
            "enfermedades": enfermedades,
            "observaciones": row.Observaciones
        }
    else:
        return None
