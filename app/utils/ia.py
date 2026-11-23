"""
app/utils/ia.py — Acceso perezoso a OpenAI (tanda 12).

El cliente se crea SOLO cuando se usa, nunca al importar un módulo: sin OPENAI_API_KEY la app
arranca igual y el asistente responde un mensaje claro de "no disponible".

Una clave que no tenga forma de clave de OpenAI (p. ej. el valor falso del sandbox,
"sandbox-sin-ia") cuenta como ausente: no se envía nada a OpenAI.
"""
import os

MENSAJE_NO_DISPONIBLE = ("El asistente no está disponible en este momento. "
                         "Para tu consulta, comunícate con la oficina del Colegio.")
MENSAJE_VOZ_NO_DISPONIBLE = ("El asistente de voz no está disponible en este momento. "
                             "Escribe tu pregunta o comunícate con la oficina del Colegio.")


def openai_api_key():
    """La clave de OpenAI si está configurada y parece real; si no, None."""
    k = (os.getenv("OPENAI_API_KEY") or "").strip()
    return k if k.startswith("sk-") else None


def ia_disponible() -> bool:
    return openai_api_key() is not None


def cliente_openai():
    """Cliente de OpenAI creado al momento de usarlo; None si no hay clave."""
    k = openai_api_key()
    if not k:
        return None
    from openai import OpenAI
    return OpenAI(api_key=k)
