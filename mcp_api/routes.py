import os
import tempfile
from flask import request, jsonify, Response
from openai import OpenAI
from mcp.core import procesar_mensaje

client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))

# Modelos/voz por defecto 
STT_MODEL = os.getenv("OPENAI_STT_MODEL", "gpt-4o-mini-transcribe")  
TTS_MODEL = os.getenv("OPENAI_TTS_MODEL", "gpt-4o-mini-tts")         
VOICE     = os.getenv("OPENAI_VOICE", "alloy")
TTS_FORMAT = os.getenv("OPENAI_TTS_FORMAT", "wav")                    

def _get_usuario_id(payload):
    # Acepta "usuario_id" o "UsuarioID" (por si llega camel/pascal)
    return int(payload.get("usuario_id") or payload.get("UsuarioID") or 3)

def configurar_rutas(app):

    @app.get("/")
    def home():
        return "DreamInCode API OK"

    @app.get("/health")
    def health():
        return jsonify(status="ok", service="api")

    # Texto -> respuesta 
    @app.post("/mcp")
    def mcp():
        data = request.get_json(silent=True) or {}
        mensaje_usuario = data.get("mensaje", "")
        usuario_id = _get_usuario_id(data)
        respuesta = procesar_mensaje(mensaje_usuario, usuario_id)
        return jsonify({"respuesta": respuesta})

    # -------- SOLO STT (voz -> texto) --------
    @app.post("/stt")
    def stt():
        if "audio" not in request.files:
            return jsonify(error="Sube el archivo en form-data con la clave 'audio'"), 400
        usuario_id = int(request.form.get("usuario_id") or request.form.get("UsuarioID") or 3)
        lang = request.form.get("lang")  # ej. "es" (opcional)

        f = request.files["audio"]
        # Guardar temporalmente para que el SDK pueda leer el archivo
        suffix = os.path.splitext(f.filename or "")[1] or ".wav"
        with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as tmp:
            f.save(tmp.name)
            tmp_path = tmp.name

        try:
            with open(tmp_path, "rb") as audio_file:
                tr = client.audio.transcriptions.create(
                    model=STT_MODEL,  
                    file=audio_file,
                    language=lang   
                )
            return jsonify({"usuario_id": usuario_id, "transcripcion": tr.text})
        finally:
            try: os.remove(tmp_path)
            except Exception: pass

    # -------- FLUJO COMPLETO (voz -> texto -> MCP -> TTS -> wav) --------
    @app.post("/voice_mcp")
    def voice_mcp():
        """
        Recibe: form-data:
          - audio (File)  -> .wav/.mp3
          - usuario_id (Text, opcional)
          - lang (Text, opcional, ej. 'es')
          - return (Text, opcional) -> 'json' para depurar texto
        Devuelve: audio/wav (por defecto) con la respuesta hablada del asistente.
        """
        if "audio" not in request.files:
            return jsonify(error="Sube el archivo en form-data con la clave 'audio'"), 400

        usuario_id = int(request.form.get("usuario_id") or request.form.get("UsuarioID") or 3)
        lang = request.form.get("lang")
        return_mode = (request.form.get("return") or "").lower()

        f = request.files["audio"]
        suffix = os.path.splitext(f.filename or "")[1] or ".wav"
        with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as tmp:
            f.save(tmp.name)
            tmp_path = tmp.name

        try:
            # 1) STT
            with open(tmp_path, "rb") as audio_file:
                tr = client.audio.transcriptions.create(
                    model=STT_MODEL,
                    file=audio_file,
                    language=lang
                )
            texto = tr.text or ""

            # 2) Tu asistente (DB + OpenAI texto)
            respuesta_texto = procesar_mensaje(texto, usuario_id)

            # Si quieres sólo depurar texto:
            if return_mode == "json":
                return jsonify({
                    "usuario_id": usuario_id,
                    "transcripcion": texto,
                    "respuesta": respuesta_texto
                })

            # 3) TTS -> bytes (WAV por defecto, ideal para 'aplay' en Pi)
            speech = client.audio.speech.create(
                model=TTS_MODEL,
                voice=VOICE,
                input=respuesta_texto,
                format=TTS_FORMAT  # "wav" o "mp3"
            )
            audio_bytes = speech.read()

            mimetype = "audio/wav" if TTS_FORMAT.lower() == "wav" else "audio/mpeg"
            filename = f"respuesta.{ 'wav' if TTS_FORMAT.lower()=='wav' else 'mp3' }"

            # 4) Responder audio directamente
            headers = {
                "Content-Disposition": f'inline; filename="{filename}"',
                "X-Usuario-Id": str(usuario_id)
            }
            return Response(audio_bytes, mimetype=mimetype, headers=headers)

        finally:
            try: os.remove(tmp_path)
            except Exception: pass

    # -------- (Opcional) Sólo TTS: texto -> audio --------
    @app.post("/tts")
    def tts():
        data = request.get_json(silent=True) or {}
        texto = data.get("texto", "").strip()
        if not texto:
            return jsonify(error="Falta 'texto'"), 400
        voice = data.get("voice") or VOICE
        fmt = (data.get("format") or TTS_FORMAT).lower()

        speech = client.audio.speech.create(
            model=TTS_MODEL,
            voice=voice,
            input=texto,
            format=fmt
        )
        audio_bytes = speech.read()
        mimetype = "audio/wav" if fmt == "wav" else "audio/mpeg"
        filename = f"tts.{ 'wav' if fmt=='wav' else 'mp3' }"
        return Response(audio_bytes, mimetype=mimetype,
                        headers={"Content-Disposition": f'inline; filename="{filename}"'})
