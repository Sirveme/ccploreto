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


import re as _re

def _build_system_prompt(col, deuda_info: dict) -> str:
    resumen = deuda_info.get("resumen", {})

    # Compatibilidad con distintas claves del resumen
    deuda_total = (
        resumen.get("deuda_total") or
        (resumen.get("deuda_cuotas", 0) +
         resumen.get("deuda_otras",  0) +
         resumen.get("deuda_fraccionamiento", 0))
    ) or 0.0

    cuotas_pend = (
        resumen.get("cuotas_pendientes") or
        resumen.get("cantidad_cuotas")   or
        deuda_info.get("cantidad_cuotas", 0)
    ) or 0

    deuda_otras = resumen.get("deuda_otras", 0) or 0
    tiene_fracc = bool(deuda_info.get("fraccionamiento"))
    condona     = 0.0

    # Calcular condonable (multas asamblea + cuotas ordinarias ≤ 2019)
    for o in deuda_info.get("obligaciones", []):
        tipo     = (o.get("categoria") or "").lower()
        concepto = (o.get("concepto")  or "").lower()
        periodo  = (o.get("periodo")   or "")
        balance  = float(o.get("balance") or 0)

        if tipo == "multa":
            es_eleccion = any(p in concepto for p in ["elecci", "votaci", "elección"])
            if not es_eleccion:
                condona += balance

        elif tipo == "cuota_ordinaria":
            m = _re.search(r"(\d{4})", periodo)
            if m and int(m.group(1)) <= 2019:
                condona += balance

    deuda_real  = max(deuda_total - condona, 0)
    min_inicial = round(deuda_real * 0.20, 2)
    califica_fracc = deuda_real >= 500

    return f"""Eres el asistente virtual del Colegio de Contadores Públicos de Loreto (CCPL).
Atiendes al colegiado {col.apellidos_nombres.split()[0] if col else 'estimado'}.

DATOS ACTUALES DEL COLEGIADO:
- Nombre: {col.apellidos_nombres if col else '—'}
- Condición: {'INHÁBIL' if col and col.condicion == 'inhabil' else (col.condicion if col else '—')}
- Deuda total: S/ {deuda_total:.2f}
- Cuotas ordinarias vencidas: {cuotas_pend}
- Otras deudas (multas, extraordinarias, eventos): S/ {deuda_otras:.2f}
- Monto condonable (Acuerdo 007-2026): S/ {condona:.2f}
- Deuda real a fraccionar (sin condonables): S/ {deuda_real:.2f}
- Cuota inicial mínima (20% de deuda real): S/ {min_inicial:.2f}
- Cuota mensual mínima: S/ 100.00
- Fraccionamiento activo: {'Sí' if tiene_fracc else 'No'}
- Califica para fraccionar: {'Sí' if califica_fracc else 'No (deuda real menor a S/ 500)'}
- Máximo cuotas mensuales: 12

REGLAS QUE DEBES CONOCER:
- Para ser HÁBIL: cero multas impagas, cero cuotas extraordinarias impagas, menos de 3 cuotas ordinarias vencidas.
- Fraccionamiento requiere: deuda real mínima S/ 500, cuota inicial al menos 20%, cuotas desde S/ 100/mes.
- Al pagar la cuota inicial del fraccionamiento → queda HÁBIL de inmediato ese mismo día.
- Acuerdo 007-2026: las multas por inasistencia a asambleas y las cuotas ordinarias del año 2019 hacia atrás se condonan automáticamente al activar un fraccionamiento. Las multas por elecciones NUNCA se condonan.
- Pagos en línea: tarjeta Visa o Mastercard vía OpenPay (activación inmediata). Yape/Plin/transferencia: se reporta manualmente y se valida en hasta 24 horas.
- Constancia de Habilidad: cuesta S/ 10, se emite en PDF al instante tras pago en línea.

INSTRUCCIONES DE RESPUESTA:
- Máximo 2 oraciones, en español peruano simple y directo.
- Da siempre el monto exacto cuando pregunten por deuda o cuotas.
- Si preguntan cómo reactivarse, menciona el fraccionamiento y la cuota inicial mínima.
- Si preguntan qué se condona, menciona el Acuerdo 007-2026 brevemente.
- Nunca inventes datos que no estén arriba. Si no sabes algo, di: consulta en ventanilla o llama al 979 169 813.
- Tono: amigable, breve, como un colega contador que ayuda."""


@router.post("/api/portal/asistente")
async def asistente_texto(
    request:  Request,
    pregunta: str     = Form(...),
    member:   Member  = Depends(get_current_member),
    db:       Session = Depends(get_db),
):
    """Asistente de texto — GPT-4o mini."""

    # ── Buscar colegiado con la misma lógica que dashboard.py ────────
    col = None
    user_input = member.user.public_id if member.user else None

    if user_input:
        user_input = user_input.strip().upper()
        # Por DNI
        if len(user_input) == 8 and user_input.isdigit():
            col = db.query(Colegiado).filter(
                Colegiado.organization_id == member.organization_id,
                Colegiado.dni == user_input
            ).first()
        # Por matrícula con guión
        elif '-' in user_input:
            col = db.query(Colegiado).filter(
                Colegiado.organization_id == member.organization_id,
                Colegiado.codigo_matricula == user_input
            ).first()
        # Por matrícula numérica (ej: 100649 → 10-0649)
        elif user_input.startswith('10'):
            resto  = user_input[2:]
            numero = ''.join(c for c in resto if c.isdigit())
            matricula = f"10-{numero.zfill(4)}"
            col = db.query(Colegiado).filter(
                Colegiado.organization_id == member.organization_id,
                Colegiado.codigo_matricula == matricula
            ).first()

    # Fallback por member_id
    if not col:
        col = db.query(Colegiado).filter(
            Colegiado.member_id == member.id
        ).first()

    # Fallback por DNI sin filtro de organización
    if not col and user_input and len(user_input) == 8 and user_input.isdigit():
        col = db.query(Colegiado).filter(
            Colegiado.dni == user_input
        ).first()

    import logging
    logger = logging.getLogger(__name__)
    logger.info(f"[Asistente] member={member.id} col={col.id if col else None} dni={user_input}")

    org_id     = member.organization_id
    col_id     = col.id if col else None
    deuda_info = calcular_deuda_total(col_id, org_id, db) if col_id else {}
    system     = _build_system_prompt(col, deuda_info)

    # DESPUÉS (usando OpenAI GPT-4o mini — mismo OPENAI_API_KEY que Whisper):
    async with httpx.AsyncClient(timeout=20) as client:
        resp = await client.post(
            "https://api.openai.com/v1/chat/completions",
            headers={
                "Authorization": f"Bearer {OPENAI_API_KEY}",
                "Content-Type":  "application/json",
            },
            json={
                "model":      "gpt-4o-mini",
                "max_tokens": 150,
                "messages":   [
                    {"role": "system",  "content": system},
                    {"role": "user",    "content": pregunta},
                ],
            }
        )
        data = resp.json()
    texto = data.get("choices", [{}])[0].get("message", {}).get("content", "...")
    return JSONResponse({"respuesta": texto})

@router.post("/api/portal/asistente/audio")
async def asistente_audio(
    request: Request,
    audio:   UploadFile = File(...),
    member:  Member     = Depends(get_current_member),
    db:      Session    = Depends(get_db),
):
    """Asistente de voz — Whisper + GPT-4o mini."""
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

    # 2. Buscar colegiado — misma lógica que dashboard.py
    col        = None
    user_input = member.user.public_id if member.user else None

    if user_input:
        user_input = user_input.strip().upper()
        if len(user_input) == 8 and user_input.isdigit():
            col = db.query(Colegiado).filter(
                Colegiado.organization_id == member.organization_id,
                Colegiado.dni == user_input
            ).first()
        elif '-' in user_input:
            col = db.query(Colegiado).filter(
                Colegiado.organization_id == member.organization_id,
                Colegiado.codigo_matricula == user_input
            ).first()
        elif user_input.startswith('10'):
            resto     = user_input[2:]
            numero    = ''.join(c for c in resto if c.isdigit())
            matricula = f"10-{numero.zfill(4)}"
            col = db.query(Colegiado).filter(
                Colegiado.organization_id == member.organization_id,
                Colegiado.codigo_matricula == matricula
            ).first()

    if not col:
        col = db.query(Colegiado).filter(
            Colegiado.member_id == member.id
        ).first()

    if not col and user_input and len(user_input) == 8 and user_input.isdigit():
        col = db.query(Colegiado).filter(
            Colegiado.dni == user_input
        ).first()

    import logging
    logger = logging.getLogger(__name__)
    logger.info(f"[Asistente audio] member={member.id} col={col.id if col else None} transcripcion='{transcripcion[:50]}'")

    # 3. Construir contexto y consultar GPT
    deuda_info = calcular_deuda_total(col.id, member.organization_id, db) if col else {}
    system     = _build_system_prompt(col, deuda_info)

    async with httpx.AsyncClient(timeout=20) as client:
        resp = await client.post(
            "https://api.openai.com/v1/chat/completions",
            headers={
                "Authorization": f"Bearer {OPENAI_API_KEY}",
                "Content-Type":  "application/json",
            },
            json={
                "model":      "gpt-4o-mini",
                "max_tokens": 150,
                "messages":   [
                    {"role": "system", "content": system},
                    {"role": "user",   "content": transcripcion},
                ],
            }
        )
        data = resp.json()

    texto = data.get("choices", [{}])[0].get("message", {}).get("content", "No pude procesar tu consulta.")
    return JSONResponse({"transcripcion": transcripcion, "respuesta": texto})