# mcp_api/routes.py
import os
import tempfile
import base64
from datetime import datetime, timedelta, timezone

from flask import request, jsonify, Response
from openai import OpenAI
import io  # (quedó uno solo, se eliminó el duplicado)

from mcp.database import get_due_meds
from mcp.core import procesar_mensaje
from mcp.context import build_system_prompt


# ---------- OpenAI client y defaults ----------
client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))

STT_MODEL  = os.getenv("OPENAI_STT_MODEL", "gpt-4o-mini-transcribe")
TTS_MODEL  = os.getenv("OPENAI_TTS_MODEL", "gpt-4o-mini-tts")
VOICE      = os.getenv("OPENAI_VOICE", "alloy")
TTS_FORMAT = os.getenv("OPENAI_TTS_FORMAT", "wav")


# ---------- TTS: garantiza WAV sin usar ffmpeg/pydub ----------
def synthesize_wav(texto: str, voice: str):
    """
    Devuelve (audio_bytes, 'audio/wav') **sin** usar ffmpeg/pydub.
    Estrategia:
      1) Intentar audio.speech.create(format='wav')
      2) Fallback: responses.create(..., audio={"format":"wav"}) y decodificar base64
    """
    # 1) Intento directo (SDKs que aceptan format="wav")
    try:
        r = client.audio.speech.create(
            model=TTS_MODEL,
            voice=voice,
            input=texto,
            format="wav",  # clave: pedimos WAV directamente
        )
        return r.read(), "audio/wav"
    except TypeError:
        # Algunas versiones antiguas no aceptan el parámetro format
        pass
    except Exception:
        # Cualquier otro error: probamos el fallback
        pass

    # 2) Fallback: API 'responses' con salida de audio en base64 WAV (SDKs modernos)
    try:
        r = client.responses.create(
            model=TTS_MODEL,
            input=texto,
            modalities=["text", "audio"],
            audio={"voice": voice, "format": "wav"},
        )

        # Extraer el audio base64 según la forma del SDK
        audio_b64 = None
        if hasattr(r, "output_audio"):  # algunos SDKs exponen esto directamente
            audio_b64 = r.output_audio
        elif getattr(r, "output", None):
            try:
                audio_b64 = r.output[0].content[0].audio.data
            except Exception:
                audio_b64 = None
        elif getattr(r, "choices", None):
            try:
                audio_b64 = r.choices[0].message.audio.data
            except Exception:
                audio_b64 = None

        if not audio_b64:
            raise RuntimeError("No se encontró audio en la respuesta de 'responses'.")

        return base64.b64decode(audio_b64), "audio/wav"
    except Exception as e:
        # Si también falla el fallback, propagamos un error claro
        raise RuntimeError(f"No se pudo sintetizar TTS en WAV: {e}") from e


# ---------- Helpers (módulo) ----------
def _get_usuario_id(payload) -> int:
    """Acepta 'usuario_id' o 'UsuarioID'. Por defecto 3."""
    return int(payload.get("usuario_id") or payload.get("UsuarioID") or 3)


def _now_with_offset(offset_min: int | None) -> datetime:
    """Devuelve ahora en UTC + offset en minutos (si se envía)."""
    now_utc = datetime.utcnow().replace(tzinfo=timezone.utc)
    if offset_min is None:
        return now_utc
    return now_utc + timedelta(minutes=offset_min)


def _build_spanish_reminder(nombre: str | None, medicamento: str, dosis: str | None, hora: str) -> str:
    """Texto de recordatorio en español para TTS."""
    quien = f"{nombre}, " if nombre else ""
    dosis_txt = f" {dosis}" if dosis else ""
    return f"Hola {quien}es la hora de tomar {medicamento}{dosis_txt}. Son las {hora}. Por favor tómala con cuidado."


# ---------- Registro de rutas ----------
def configurar_rutas(app):

    # --- ping ---
    @app.get("/")
    def home():
        return "DreamInCode API OK"

    @app.get("/health")
    def health():
        return jsonify(status="ok", service="api")

    # --- Texto -> respuesta  ---
    @app.post("/mcp")
    def mcp():
        data = request.get_json(silent=True) or {}
        mensaje_usuario = data.get("mensaje", "") or ""
        usuario_id = _get_usuario_id(data)

        # Inyecta contexto del usuario en el system prompt
        system = build_system_prompt(usuario_id)

        # Tu función debe aceptar system_override=system
        respuesta = procesar_mensaje(mensaje_usuario, usuario_id, system_override=system)
        return jsonify({"respuesta": respuesta})

    # --- SOLO STT: voz -> texto ---
    @app.post("/stt")
    def stt():
        if "audio" not in request.files:
            return jsonify(error="Sube el archivo en form-data con la clave 'audio'"), 400

        # (opcional) campos extra
        _ = int(request.form.get("usuario_id") or request.form.get("UsuarioID") or 3)
        lang = request.form.get("lang")  # ej. "es"

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

    # --- Flujo completo: voz -> texto -> MCP -> TTS -> audio ---
    @app.post("/voice_mcp")
    def voice_mcp():
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

            # 2) Contexto y MCP
            system = build_system_prompt(usuario_id)
            respuesta_texto = procesar_mensaje(texto, usuario_id, system_override=system)

            # Opcional para depurar
            if return_mode == "json":
                return jsonify({
                    "usuario_id": usuario_id,
                    "transcripcion": texto,
                    "respuesta": respuesta_texto
                })

            # 3) TTS -> WAV garantizado (sin ffmpeg)
            audio_bytes, mimetype = synthesize_wav(respuesta_texto, VOICE)

            filename = "respuesta.wav"
            headers = {
                "Content-Disposition": f'inline; filename="{filename}"',
                "X-Usuario-Id": str(usuario_id)
            }
            return Response(audio_bytes, mimetype=mimetype, headers=headers)

        finally:
            try:
                os.remove(tmp_path)
            except Exception:
                pass

    @app.post("/tts")
    def tts():
        data = request.get_json(silent=True) or {}
        texto = (data.get("texto") or "").strip()
        if not texto:
            return jsonify(error="Falta 'texto'"), 400

        voice = data.get("voice") or VOICE

        # WAV garantizado (sin ffmpeg)
        audio_bytes, mimetype = synthesize_wav(texto, voice)
        filename = "tts.wav"
        return Response(
            audio_bytes,
            mimetype=mimetype,
            headers={"Content-Disposition": f'inline; filename="{filename}"'}
        )

    # --- (A) Qué medicamento toca ahora (JSON) ---
    @app.get("/meds/due")
    def meds_due():
        """
        Params:
          - usuario_id: int (requerido)
          - window_min: int (opcional, default 5)
          - tz_offset_min: int (opcional) minutos vs UTC (p.ej. -240)
        """
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

    # --- (B) Generar recordatorio TTS (WAV/MP3) ---
    @app.post("/reminder_tts")
    def reminder_tts():
        """
        Body JSON:
          - usuario_id (int, opcional)
          - medicamento (string, requerido si no se usa 'auto')
          - dosis (string, opcional)
          - hora (HH:mm, requerido si no se usa 'auto')
          - auto (bool, opcional): si true, usa primer 'due' de /meds/due
          - tz_offset_min (int, opcional) minutos vs UTC

        Respuesta:
          - audio (wav/mp3). ?mode=json devuelve base64 para pruebas.
        """
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

        # Aquí seguimos respetando TTS_FORMAT (por si quieres MP3 en este endpoint)
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

        headers = {
            "X-Usuario-Id": str(usuario_id) if usuario_id else "",
            "X-Medicamento": medicamento,
            "X-Dosis": dosis or "",
            "X-Hora": hora,
        }
        mimetype = "audio/wav" if TTS_FORMAT.lower() == "wav" else "audio/mpeg"
        return Response(audio_bytes, mimetype=mimetype, headers=headers)
