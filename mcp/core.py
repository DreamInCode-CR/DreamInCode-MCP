# mcp/core.py
from mcp.context import cargar_contexto_basico
from mcp.openai_client import prompt_to_openai

def procesar_mensaje(mensaje_usuario, usuario_id=3):
    contexto = cargar_contexto_basico(usuario_id)
    contexto.append({"role": "user", "content": mensaje_usuario})
    respuesta = prompt_to_openai(contexto)
    return respuesta