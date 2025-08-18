# mcp_api/routes.py  (versión unificada)
import os
import io
import base64
import tempfile
from datetime import datetime, timedelta, timezone

from flask import Blueprint, request, jsonify, Response, send_file
from openai import OpenAI

# Tu lógica propia
from mcp.database import get_due_meds
from mcp.core import procesar_mensaje           # Mantén tu implementación
from mcp.context import build_system_prompt     # Mantén tu system prompt

def configurar_rutas(app):
    api = Blueprint("api", __name__)

    # -------- Config desde variables de entorno (Azure App Settings) --------
    OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
    CHAT_MODEL     = os.getenv("OPENAI_MODEL", "gpt-4o-mini")
    STT_MODEL      = os.getenv("OPENAI_STT_MODEL", "gpt-4o-mini-transcribe")
    TTS_MODEL      = os.getenv("OPENAI_TTS_MODEL", "gpt-4o-mini-tts")
    TTS_FORMAT     = os.getenv("OPENAI_TTS_FORMAT", "wav")
    VOICE          = os.getenv("OPENAI_VOICE", "alloy")

    client = OpenAI(api_key=OPENAI_API_KEY)

    # -------------------- Helpers --------------------
    def _get_usuario_id(payload) -> int:
        return int(payload.get("usuario_id") or payload.get("UsuarioID") or 3)

    def _now_with_offset(offset_min: int | None) -> datetime:
        now_utc = datetime.utcnow().replace(tzinfo=timezone.utc)
        return now_utc if offset_min is None else now_utc + timedelta(minutes=offset_min)

    def _build_spanish_reminder(nombre: str | None, medicamento: str, dosis: str | None, hora: str) -> str:
        quien = f"{nombre}, " if nombre else ""
        dosis_txt = f" {dosis}" if dosis else ""
        return f"Hola {quien}es la hora de tomar {medicamento}{dosis_txt}. Son las {hora}. Por favor tómala con cuidado."

    def transcribir_audio(file_storage) -> str:
        """STT: archivo (werkzeug FileStorage) -> texto."""
        data = file_storage.read()
        filename = file_storage.filename or "audio.wav"
        mimetype = file_storage.mimetype or "audio/wav"
        resp = client.audio.transcriptions.create(
            model=STT_MODEL,
            file=(filename, data, mimetype),
        )
        return resp.text

    def synthesize_wav(texto: str, voice: str | None = None) -> bytes:
        """TTS: texto -> WAV (sin ffmpeg)."""
        v = voice or VOICE
        with client.audio.speech.with_streaming_response.create(
            model=TTS_MODEL,
            voice=v,
            input=texto,
            format="wav",
        ) as r:
            tmp = tempfile.NamedTemporaryFile(suffix=".wav", delete=False)
            try:
                r.stream_to_file(tmp.name)
                with open(tmp.name, "rb") as f:
                    return f.read()
            finally:
                try:
                    os.remove(tmp.name)
                except Exception:
                    pass

    # -------------------- Rutas --------------------
    @api.get("/")
    def home():
        return "DreamInCode API OK"

    @api.get("/health")
    def health():
        return jsonify({"status": "ok", "service": "api"})

    # Texto -> respuesta (usa tu procesar_mensaje)
    @api.post("/mcp")
    def mcp():
        data = request.get_json(silent=True) or {}
        mensaje_usuario = (data.get("mensaje") or "").strip()
        usuario_id = _get_usuario_id(data)
        system = build_system_prompt(usuario_id)
        # Tu procesar_mensaje debe soportar system_override si quieres inyectarlo:
        respuesta = procesar_mensaje(mensaje_usuario, usuario_id, system_override=system)
        return jsonify({"respuesta": respuesta})

    # Solo STT
    @api.post("/stt")
    def stt():
        if "audio" not in request.files:
            return jsonify(error="Sube el archivo en form-data con la clave 'audio'"), 400

        _ = int(request.form.get("usuario_id") or request.form.get("UsuarioID") or 3)
        lang = request.form.get("lang")  # opcional

        f = request.files["audio"]
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
            return jsonify({"transcripcion": tr.text})
        finally:
            try:
                os.remove(tmp_path)
            except Exception:
                pass

    # Flujo completo: voz -> texto -> MCP -> TTS
    @api.post("/voice_mcp")
    def voice_mcp():
        if "audio" not in request.files:
            return jsonify(error="faltó 'audio' en form-data"), 400

        audio_file = request.files["audio"]
        usuario_id = request.form.get("usuario_id")
        retorno    = (request.form.get("return") or "audio").lower()

        try:
            texto = transcribir_audio(audio_file)
            # Usa tu LLM con contexto
            system = build_system_prompt(usuario_id)
            respuesta_texto = procesar_mensaje(texto, usuario_id, system_override=system)
        except Exception as e:
            app.logger.exception("Error en STT o LLM")
            return jsonify(error="processing_failed", detail=str(e)), 500

        if retorno == "json":
            return jsonify({"transcript": texto, "reply": respuesta_texto})

        try:
            wav_bytes = synthesize_wav(respuesta_texto)
        except Exception as e:
            app.logger.exception("Error en TTS")
            return jsonify(error="tts_failed", detail=str(e)), 500

        return send_file(
            io.BytesIO(wav_bytes),
            mimetype="audio/wav",
            as_attachment=False,
            download_name="reply.wav",
        )

    # Texto -> TTS directo
    @api.post("/tts")
    def tts():
        data = request.get_json(silent=True) or {}
        texto = (data.get("texto") or "").strip()
        if not texto:
            return jsonify(error="Falta 'texto'"), 400
        voice = data.get("voice") or VOICE
        audio_bytes = synthesize_wav(texto, voice)
        return Response(
            audio_bytes,
            mimetype="audio/wav",
            headers={"Content-Disposition": 'inline; filename="tts.wav"'}
        )

    # Qué medicamento toca ahora (JSON)
    @api.get("/meds/due")
    def meds_due():
        try:
            usuario_id = int(request.args.get("usuario_id"))
        except (TypeError, ValueError):
            return jsonify(error="usuario_id requerido"), 400

        window = int(request.args.get("window_min", 5))
        tz_offset = request.args.get("tz_offset_min")
        tz_offset = int(tz_offset) if tz_offset not in (None, "") else None

        now_local = _now_with_offset(tz_offset)
        items = get_due_meds(usuario_id, now_local, window)

        return jsonify({
            "usuario_id": usuario_id,
            "now_local": now_local.isoformat(),
            "window_min": window,
            "items": items
        })

    # Generar recordatorio TTS (WAV/MP3 configurable por TTS_FORMAT)
    @api.post("/reminder_tts")
    def reminder_tts():
        data = request.get_json(silent=True) or {}
        usuario_id = int(data.get("usuario_id") or 0) or None
        auto = bool(data.get("auto"))
        tz_offset = data.get("tz_offset_min")
        tz_offset = int(tz_offset) if tz_offset not in (None, "") else None

        if auto:
            if not usuario_id:
                return jsonify(error="auto=true requiere usuario_id"), 400
            now_local = _now_with_offset(tz_offset)
            due = get_due_meds(usuario_id, now_local, window_min=5)
            if not due:
                return jsonify(error="No hay medicamentos para este momento."), 404
            item = due[0]
            medicamento = item["medicamento"]
            dosis = item.get("dosis")
            hora = item["hora"]
            nombre = item.get("usuario_nombre")
        else:
            medicamento = (data.get("medicamento") or "").strip()
            dosis = (data.get("dosis") or "").strip() or None
            hora = (data.get("hora") or "").strip()
            nombre = None
            if not medicamento or not hora:
                return jsonify(error="Faltan campos: 'medicamento' y 'hora'"), 400

        texto = _build_spanish_reminder(nombre, medicamento, dosis, hora)

        speech = client.audio.speech.create(
            model=TTS_MODEL,
            voice=VOICE,
            input=texto,
            format=TTS_FORMAT
        )
        audio_bytes = speech.read()

        if request.args.get("mode") == "json":
            return jsonify({
                "usuario_id": usuario_id,
                "medicamento": medicamento,
                "dosis": dosis,
                "hora": hora,
                "tts_texto": texto,
                "audio_format": TTS_FORMAT,
                "audio_base64": base64.b64encode(audio_bytes).decode("utf-8")
            })

        mimetype = "audio/wav" if TTS_FORMAT.lower() == "wav" else "audio/mpeg"
        headers = {
            "X-Usuario-Id": str(usuario_id) if usuario_id else "",
            "X-Medicamento": medicamento,
            "X-Dosis": dosis or "",
            "X-Hora": hora,
        }
        return Response(audio_bytes, mimetype=mimetype, headers=headers)

    # <<< REGISTRO DEL BLUEPRINT (fuera de los handlers) >>>
    app.register_blueprint(api, url_prefix="/")
