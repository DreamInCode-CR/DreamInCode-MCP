# mcp/context.py
import os
import textwrap
from datetime import datetime, timezone, timedelta
from .database import obtener_datos_usuario


def contexto_a_texto(datos: dict) -> str:
    """Convierte el dict de la BD en texto legible para el modelo."""
    if not datos:
        return "Sin datos de usuario."

    partes = []
    # Usa .get para no explotar si falta un campo
    if datos.get("nombre"):
        partes.append(f"Nombre: {datos.get('nombre')}")
    if datos.get("edad"):
        partes.append(f"Edad: {datos.get('edad')}")
    if datos.get("genero"):
        partes.append(f"Género: {datos.get('genero')}")
    if datos.get("condiciones"):
        partes.append(f"Condiciones médicas: {datos.get('condiciones')}")
    if datos.get("medicamentos"):
        partes.append(f"Medicamentos: {datos.get('medicamentos')}")
    if datos.get("preferencias"):
        partes.append(f"Preferencias: {datos.get('preferencias')}")
    if datos.get("cuidadores"):
        partes.append(f"Cuidadores: {datos.get('cuidadores')}")
    if datos.get("objetivos"):
        partes.append(f"Objetivos: {datos.get('objetivos')}")
    # agrega aquí cualquier otro campo que devuelva tu BD

    return "\n".join(partes) if partes else "Sin datos de usuario."


def _offset_str(minutes: int) -> str:
    """Devuelve la cadena de zona estilo +HH:MM a partir de minutos."""
    sign = "+" if minutes >= 0 else "-"
    m = abs(minutes)
    hh, mm = divmod(m, 60)
    return f"{sign}{hh:02d}:{mm:02d}"


def _now_with_offset(tz_offset_min: int | None):
    """
    Devuelve (now_utc, now_local, offset_str).
    - Si tz_offset_min es None, intenta leer de env TZ_OFFSET_MIN; si no, usa UTC.
    """
    now_utc = datetime.now(timezone.utc)

    if tz_offset_min is None:
        env_off = os.getenv("TZ_OFFSET_MIN")
        if env_off and (env_off.lstrip("+-").isdigit()):
            try:
                tz_offset_min = int(env_off)
            except Exception:
                tz_offset_min = None

    if tz_offset_min is None:
        # Sin offset explícito: usa UTC
        return now_utc, now_utc, "+00:00"

    local = now_utc + timedelta(minutes=tz_offset_min)
    return now_utc, local, _offset_str(tz_offset_min)


def build_system_prompt(usuario_id: int, tz_offset_min: int | None = None) -> str:
    """
    Crea el prompt de sistema con pautas + perfil del usuario desde la BD,
    e inyecta la FECHA/HORA actuales para evitar respuestas desfasadas.
    - tz_offset_min: desfase local vs UTC en minutos (ej. -240 para UTC-4).
      Si no se pasa, intenta usar la variable de entorno TZ_OFFSET_MIN.
    """
    datos = obtener_datos_usuario(usuario_id)
    perfil = contexto_a_texto(datos)

    now_utc, now_local, offset_str = _now_with_offset(tz_offset_min)

    fecha_hora = textwrap.dedent(f"""\
        CONTEXTO DE TIEMPO (usar esto al responder):
        - NOW_LOCAL: {now_local.strftime('%Y-%m-%d %H:%M:%S')} (UTC{offset_str})
        - NOW_UTC:   {now_utc.strftime('%Y-%m-%d %H:%M:%S')} (UTC+00:00)
        Si el usuario pregunta por FECHA u HORA actuales, responde con NOW_LOCAL.
        Si hay ambigüedad, aclara la zona como (UTC{offset_str}).
    """).strip()

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

    return f"{base}\n\nPERFIL DEL USUARIO\n{perfil}\n\n{fecha_hora}\n"


# --- Compatibilidad con código antiguo ---
def cargar_contexto_basico(usuario_id: int) -> str:
    """
    Alias para mantener compatibilidad con módulos que aún importan
    'cargar_contexto_basico'. Devuelve el mismo prompt que build_system_prompt.
    """
    return build_system_prompt(usuario_id)
