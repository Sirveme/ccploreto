"""
app/routers/junta.py
Vista del Representante de la JDCCPP (role='junta_jdccpp') — SOLO LECTURA.

Pieza F: /junta/reporte lista solo periodos APROBADOS + firmante + descargas.
Pieza G: descargas registran en junta_descarga_log y respetan el límite de
         junta_acceso_config.max_descargas_por_periodo (0 = ilimitado) → 429.
El blindaje de rutas (que este rol no acceda a nada fuera de /junta) vive en el
middleware de app/main.py (Pieza J).
"""

from datetime import datetime, timezone, timedelta

from fastapi import APIRouter, Depends, Request, HTTPException
from fastapi.responses import HTMLResponse, Response
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import Member
from app.routers.dashboard import get_current_member
from app.utils.templates import templates

router = APIRouter(prefix="/junta", tags=["junta-jdccpp"])

ORG_CCPL = 1
TZ_PERU = timezone(timedelta(hours=-5))
MESES_ES = ["", "Enero", "Febrero", "Marzo", "Abril", "Mayo", "Junio",
            "Julio", "Agosto", "Septiembre", "Octubre", "Noviembre", "Diciembre"]


def require_junta_jdccpp(current_member: Member = Depends(get_current_member)) -> Member:
    if current_member is None or current_member.role != "junta_jdccpp":
        raise HTTPException(status_code=403, detail="Acceso exclusivo del representante JDCCPP")
    return current_member


def _max_descargas(db: Session) -> int:
    row = db.execute(text("""
        SELECT max_descargas_por_periodo FROM junta_acceso_config WHERE organizacion_id = :o
    """), {"o": ORG_CCPL}).fetchone()
    return int(row.max_descargas_por_periodo) if row and row.max_descargas_por_periodo is not None else 10


@router.get("/reporte", response_class=HTMLResponse)
async def junta_reporte(
    request: Request,
    db: Session = Depends(get_db),
    current_member: Member = Depends(require_junta_jdccpp),
):
    maxd = _max_descargas(db)
    aprobados = db.execute(text("""
        SELECT ap.id, ap.anio, ap.mes, ap.monto_total,
               ap.aprobado_admin_nombre, ap.aprobado_admin_dni, ap.aprobado_at,
               dep.numero_voucher,
               (SELECT COUNT(*) FROM junta_descarga_log l
                  WHERE l.aporte_periodo_id = ap.id AND l.user_id = :uid) AS descargas
        FROM aporte_periodos ap
        LEFT JOIN aporte_deposito dep ON dep.aporte_periodo_id = ap.id
        WHERE ap.organizacion_id = :org AND ap.aprobado = TRUE
        ORDER BY ap.anio DESC, ap.mes DESC
    """), {"org": ORG_CCPL, "uid": current_member.user_id}).fetchall()

    ahora = datetime.now(TZ_PERU)
    pendiente = db.execute(text("""
        SELECT anio, mes FROM aporte_periodos
        WHERE organizacion_id = :org AND anio = :a AND mes = :m AND aprobado IS NOT TRUE
    """), {"org": ORG_CCPL, "a": ahora.year, "m": ahora.month}).fetchone()

    periodos = [{
        "id": r.id,
        "label": f"{MESES_ES[r.mes]} {r.anio}",
        "monto_total": float(r.monto_total or 0),
        "firmante": r.aprobado_admin_nombre,
        "firmante_dni": r.aprobado_admin_dni,
        "aprobado_at": r.aprobado_at,
        "voucher": r.numero_voucher,
        "descargas": r.descargas or 0,
        "restantes": (max(0, maxd - (r.descargas or 0)) if maxd and maxd > 0 else None),
    } for r in aprobados]

    return templates.TemplateResponse("pages/junta/reporte.html", {
        "request": request,
        "periodos": periodos,
        "pendiente_label": (f"{MESES_ES[pendiente.mes]} {pendiente.anio}" if pendiente else None),
        "max_descargas": maxd,
    })


def _registrar_descarga(db: Session, periodo_id: int, current_member: Member,
                        request: Request, tipo: str):
    periodo = db.execute(text("""
        SELECT id, anio, mes FROM aporte_periodos WHERE id = :p AND aprobado = TRUE
    """), {"p": periodo_id}).fetchone()
    if not periodo:
        raise HTTPException(404, "Periodo no encontrado o no aprobado")

    maxd = _max_descargas(db)
    if maxd and maxd > 0:
        cnt = db.execute(text("""
            SELECT COUNT(*) AS c FROM junta_descarga_log
            WHERE aporte_periodo_id = :p AND user_id = :u
        """), {"p": periodo_id, "u": current_member.user_id}).fetchone().c
        if cnt >= maxd:
            raise HTTPException(429, "Alcanzaste el máximo de descargas para este periodo. "
                                     "Comunícate con el CCPL si necesitas más.")

    db.execute(text("""
        INSERT INTO junta_descarga_log (
            aporte_periodo_id, user_id, tipo_descarga, ip_origen, user_agent, descargado_at
        ) VALUES (:p, :u, :t, :ip, :ua, NOW())
    """), {"p": periodo_id, "u": current_member.user_id, "t": tipo,
           "ip": request.client.host if request.client else None,
           "ua": request.headers.get("user-agent", "")[:500]})
    db.commit()
    return periodo


@router.get("/reporte/{periodo_id}/pdf")
async def junta_pdf(
    periodo_id: int,
    request: Request,
    db: Session = Depends(get_db),
    current_member: Member = Depends(require_junta_jdccpp),
):
    periodo = _registrar_descarga(db, periodo_id, current_member, request, "pdf")
    from app.services.aportes_pdf import generar_pdf
    pdf = generar_pdf(db, periodo_id, show_footer=False, org_id=ORG_CCPL)
    fname = f"CCPL_Aporte_JDCCPP_{periodo.anio}_{periodo.mes:02d}.pdf"
    return Response(content=pdf, media_type="application/pdf",
                    headers={"Content-Disposition": f'attachment; filename="{fname}"'})


@router.get("/reporte/{periodo_id}/excel")
async def junta_excel(
    periodo_id: int,
    request: Request,
    db: Session = Depends(get_db),
    current_member: Member = Depends(require_junta_jdccpp),
):
    periodo = _registrar_descarga(db, periodo_id, current_member, request, "excel")
    from app.services.aportes_pdf import generar_excel
    xls = generar_excel(db, periodo_id, show_footer=False, org_id=ORG_CCPL)
    fname = f"CCPL_Aporte_JDCCPP_{periodo.anio}_{periodo.mes:02d}.xlsx"
    return Response(
        content=xls,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f'attachment; filename="{fname}"'})
