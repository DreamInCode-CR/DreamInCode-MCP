# mcp/openai_client.py
import os
from openai import OpenAI

client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))
MODEL = os.getenv("OPENAI_MODEL", "gpt-4o-mini")

def completar_chat(system: str, user_text: str) -> str:
    """Hace una llamada Chat Completions con system + user."""
    resp = client.chat.completions.create(
        model=MODEL,
        messages=[
            {"role": "system", "content": system},
            {"role": "user",   "content": user_text}
        ],
        temperature=0.3,
    )
    return resp.choices[0].message.content
