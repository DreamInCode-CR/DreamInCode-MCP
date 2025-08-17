# mcp/core.py
from .context import build_system_prompt, cargar_contexto_basico  # si la usas en otro lado
from .openai_client import completar_chat

def procesar_mensaje(mensaje: str, usuario_id: int, system_override: str | None = None) -> str:
    """
    Procesa el mensaje:
      - construye (o recibe) el system prompt
      - llama al modelo con system + user
    """
    # Si lo necesitas para otras cosas, puedes seguir cargando el contexto básico:
    _ctx = cargar_contexto_basico(usuario_id)  # opcional: útil si haces más lógica

    system = system_override or build_system_prompt(usuario_id)
    respuesta = completar_chat(system, mensaje)
    return respuesta
