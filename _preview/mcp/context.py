from mcp.database import obtener_datos_usuario
from datetime import datetime

def cargar_contexto_basico(usuario_id=3):
    print(f"[DEBUG API] Cargando datos para usuario_id={usuario_id}")
    datos = obtener_datos_usuario(usuario_id)
    print("[DEBUG API] Datos obtenidos:", datos)
    fecha_actual = datetime.now().strftime("%A %d de %B de %Y")
    hora_actual = datetime.now().strftime("%H:%M")
    
    if not datos:
        nombre = "usuario"
        datos_extra = "No hay información adicional disponible."
    else:
        nombre = datos["nombre"] 
        enfermedades_lista = datos.get("enfermedades", [])
        enfermedades_texto = ", ".join(enfermedades_lista) if enfermedades_lista else "no especificadas"
        datos_extra = (
            f"Tiene {datos['edad']} años. "
            f"Enfermedades: {enfermedades_texto}. "
            f"Observaciones: {datos['observaciones'] or 'ninguna'}."
        )

    return [
        {
            "role": "system",
            "content": (
                f"Eres un asistente personalizado para una persona mayor llamada {nombre}. "
                f"{datos_extra} "
                f"La fecha actual es {fecha_actual} y la hora actual es {hora_actual}. "
                f"Siempre que el usuario pregunte sobre sí mismo o sobre la fecha/hora, usa esta información."
            )
        }
    ]
