# mcp/context.py
import textwrap
from .database import obtener_datos_usuario

def contexto_a_texto(datos: dict) -> str:
    """Convierte el dict de la BD en texto legible para el modelo."""
    if not datos:
        return "Sin datos de usuario."

    partes = []
    # Usa .get para no explotar si falta un campo
    if datos.get("nombre"): partes.append(f"Nombre: {datos.get('nombre')}")
    if datos.get("edad"):   partes.append(f"Edad: {datos.get('edad')}")
    if datos.get("genero"): partes.append(f"Género: {datos.get('genero')}")
    if datos.get("condiciones"): partes.append(f"Condiciones médicas: {datos.get('condiciones')}")
    if datos.get("medicamentos"): partes.append(f"Medicamentos: {datos.get('medicamentos')}")
    if datos.get("preferencias"): partes.append(f"Preferencias: {datos.get('preferencias')}")
    if datos.get("cuidadores"):   partes.append(f"Cuidadores: {datos.get('cuidadores')}")
    if datos.get("objetivos"):    partes.append(f"Objetivos: {datos.get('objetivos')}")
    # agrega aquí cualquier otro campo que devuelva tu BD

    return "\n".join(partes) if partes else "Sin datos de usuario."

def build_system_prompt(usuario_id: int) -> str:
    """Crea el prompt de sistema con pautas + perfil del usuario desde la BD."""
    datos = obtener_datos_usuario(usuario_id)
    perfil = contexto_a_texto(datos)

    base = textwrap.dedent("""\
        Eres un asistente conversacional para adultos mayores.
        - Habla SIEMPRE en español, claro y pausado.
        - Usa oraciones cortas, estructura simple y tono amable.
        - Ofrece confirmar entendimiento y repetir si hace falta.
        - Cuando des pasos o instrucciones, enumera con viñetas o pasos.
        - Si hay dudas médicas, da información general y sugiere consultar a un profesional.
        - Evita tecnicismos innecesarios; explica conceptos de forma sencilla.

        Responde SIEMPRE en función del siguiente perfil del usuario:
    """).strip()

    return f"{base}\n\nPERFIL DEL USUARIO\n{perfil}\n"

# --- Compatibilidad con código antiguo ---
def cargar_contexto_basico(usuario_id: int) -> str:
    """
    Alias para mantener compatibilidad con módulos que aún importan
    'cargar_contexto_basico'. Devuelve el mismo prompt que build_system_prompt.
    """
    return build_system_prompt(usuario_id)
