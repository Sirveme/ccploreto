"""
app/routers/asistente.py
Asistente de voz/texto para portal del colegiado.
Fase 1: Claude Haiku + Web Speech API
Fase 2: Claude Haiku + Whisper (solo cambiar el endpoint de audio)
"""
import os
import httpx
from fastapi import APIRouter, Request, Depends, Form, UploadFile, File
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session
from app.database import get_db
from app.routers.dashboard import get_current_member
from app.models import Member, Colegiado
from app.services.deuda_cuotas_service import calcular_deuda_total

router = APIRouter(tags=["asistente"])

ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY")
OPENAI_API_KEY    = os.getenv("OPENAI_API_KEY")   # para Whisper fase 2


def _build_system_prompt(col, deuda_info: dict) -> str:
    resumen      = deuda_info.get("resumen", {})
    deuda_total  = resumen.get("deuda_total", 0)
    cuotas_pend  = resumen.get("cuotas_pendientes", 0)
    deuda_otras  = resumen.get("deuda_otras", 0)
    tiene_fracc  = bool(deuda_info.get("fraccionamiento"))
    min_inicial  = round(deuda_total * 0.20, 2)
    condona      = 0.0

    # Calcular condonable (multas asamblea + cuotas ≤ 2019)
    for o in deuda_info.get("obligaciones", []):
        tipo     = (o.get("categoria") or "").lower()
        concepto = (o.get("concepto")  or "").lower()
        periodo  = (o.get("periodo")   or "")
        balance  = float(o.get("balance") or 0)
        if tipo == "multa" and not any(p in concepto for p in ["elecci", "votaci"]):
            condona += balance
        elif tipo == "cuota_ordinaria":
            m = __import__("re").search(r"(\d{4})", periodo)
            if m and int(m.group(1)) <= 2019:
                condona += balance

    deuda_real = deuda_total - condona

    return f"""Eres el asistente virtual del Colegio de Contadores Públicos de Loreto (CCPL).
Atiendes al colegiado {col.apellidos_nombres.split()[0] if col else 'estimado'}.

DATOS ACTUALES DEL COLEGIADO:
- Nombre: {col.apellidos_nombres if col else '—'}
- Condición: {'INHÁBIL' if col and col.condicion == 'inhabil' else col.condicion if col else '—'}
- Deuda total: S/ {deuda_total:.2f}
- Cuotas ordinarias vencidas: {cuotas_pend}
- Otras deudas (multas, extraordinarias): S/ {deuda_otras:.2f}
- Monto condonable (Acuerdo 007-2026): S/ {condona:.2f}
- Deuda real a fraccionar: S/ {deuda_real:.2f}
- Cuota inicial mínima (20%): S/ {min_inicial:.2f}
- Cuota mensual mínima: S/ 100.00
- Fraccionamiento activo: {'Sí' if tiene_fracc else 'No'}
- Máximo cuotas mensuales: 12

REGLAS QUE DEBES CONOCER:
- Para ser HÁBIL: 0 multas, 0 cuotas extraordinarias, menos de 3 cuotas ordinarias vencidas.
- Fraccionamiento: requiere deuda mínima S/ 500, cuota inicial 20%, cuotas desde S/ 100.
- Al pagar cuota inicial del fraccionamiento → queda HÁBIL de inmediato.
- Con Acuerdo 007-2026: las multas de asamblea y cuotas ≤ 2019 se condonan al fraccionar.
- Pagos en línea: tarjeta Visa/Mastercard vía OpenPay. Yape/Plin: reportar pago manual.
- Constancia de Habilidad: S/ 10, se emite al instante tras pago en línea.

INSTRUCCIONES:
- Responde en máximo 2 oraciones, en español peruano simple y directo.
- Si preguntan cuánto deben, da el número exacto.
- Si preguntan por fraccionamiento, da la cuota inicial mínima y las opciones de cuotas.
- Si preguntan qué se condona, explica el Acuerdo 007-2026 brevemente.
- Nunca inventes datos. Si no sabes algo, di "consulta en ventanilla".
- Tono: amigable, breve, como un colega que ayuda."""


@router.post("/api/portal/asistente")
async def asistente_texto(
    request:  Request,
    pregunta: str     = Form(...),
    member:   Member  = Depends(get_current_member),
    db:       Session = Depends(get_db),
):
    """Asistente de texto — Claude Haiku."""
    col = db.query(Colegiado).filter(
        Colegiado.member_id == member.id
    ).first()

    org_id     = member.organization_id
    col_id     = col.id if col else None
    deuda_info = calcular_deuda_total(col_id, org_id, db) if col_id else {}

    system = _build_system_prompt(col, deuda_info)

    async with httpx.AsyncClient(timeout=20) as client:
        resp = await client.post(
            "https://api.anthropic.com/v1/messages",
            headers={
                "x-api-key":         ANTHROPIC_API_KEY,
                "anthropic-version": "2023-06-01",
                "content-type":      "application/json",
            },
            json={
                "model":      "claude-haiku-4-5-20251001",
                "max_tokens": 150,
                "system":     system,
                "messages":   [{"role": "user", "content": pregunta}],
            }
        )
        data = resp.json()

    texto = data.get("content", [{}])[0].get("text", "Disculpa, no pude procesar tu consulta.")
    return JSONResponse({"respuesta": texto})


@router.post("/api/portal/asistente/audio")
async def asistente_audio(
    request: Request,
    audio:   UploadFile = File(...),
    member:  Member     = Depends(get_current_member),
    db:      Session    = Depends(get_db),
):
    """
    Asistente de voz — Whisper + Claude Haiku.
    Fase 2: activar cuando el cliente apruebe.
    Requiere: OPENAI_API_KEY en Railway.
    """
    if not OPENAI_API_KEY:
        return JSONResponse({"error": "Whisper no configurado"}, status_code=503)

    # 1. Transcribir con Whisper
    audio_bytes = await audio.read()
    async with httpx.AsyncClient(timeout=30) as client:
        whisper_resp = await client.post(
            "https://api.openai.com/v1/audio/transcriptions",
            headers={"Authorization": f"Bearer {OPENAI_API_KEY}"},
            data={"model": "whisper-1", "language": "es"},
            files={"file": (audio.filename or "audio.webm", audio_bytes, "audio/webm")},
        )
        transcripcion = whisper_resp.json().get("text", "")

    if not transcripcion:
        return JSONResponse({"error": "No se pudo transcribir el audio"}, status_code=400)

    # 2. Pasar transcripción a Claude (mismo flujo que texto)
    col = db.query(Colegiado).filter(Colegiado.member_id == member.id).first()
    deuda_info = calcular_deuda_total(col.id, member.organization_id, db) if col else {}
    system     = _build_system_prompt(col, deuda_info)

    async with httpx.AsyncClient(timeout=20) as client:
        resp = await client.post(
            "https://api.anthropic.com/v1/messages",
            headers={
                "x-api-key":         ANTHROPIC_API_KEY,
                "anthropic-version": "2023-06-01",
                "content-type":      "application/json",
            },
            json={
                "model":      "claude-haiku-4-5-20251001",
                "max_tokens": 150,
                "system":     system,
                "messages":   [{"role": "user", "content": transcripcion}],
            }
        )
        data = resp.json()

    texto = data.get("content", [{}])[0].get("text", "No pude procesar tu consulta.")
    return JSONResponse({"transcripcion": transcripcion, "respuesta": texto})