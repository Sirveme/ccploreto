from fastapi import APIRouter, Depends, Request, HTTPException
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from app.utils.templates import templates
from sqlalchemy.orm import Session
from sqlalchemy import text

from app.database import get_db
from app.models import User, Member, Colegiado
from app.routers.dashboard import get_current_member

router = APIRouter(prefix="/decano", tags=["decano"])


def require_decano(current_member: Member = Depends(get_current_member)):
    if current_member.role not in ("decano", "sote"):
        raise HTTPException(status_code=403, detail="Acceso restringido al Decanato")
    return current_member


@router.get("", response_class=HTMLResponse)
async def decano_dashboard(
    request: Request,
    db: Session = Depends(get_db),
    current_member: Member = Depends(require_decano),
):
    user = db.query(User).filter(User.id == current_member.user_id).first()
    return templates.TemplateResponse("pages/decano/dashboard.html", {
        "request": request,
        "user": current_member,   # base.html espera user.organization
        "user_name": user.name,
        "org": getattr(request.state, "org", {}),
    })


# ── Consultas / Reportes (solo lectura). Primera: Historial de NC. ──
@router.get("/consultas/nc", response_class=HTMLResponse)
async def decano_consultas_nc(
    request: Request,
    fecha_desde: str = None, fecha_hasta: str = None,
    motivo: str = None, q_comprobante: str = None, q_colegiado: str = None,
    db: Session = Depends(get_db),
    current_member: Member = Depends(require_decano),
):
    from app.services.anulacion_service import listar_historial_nc
    historial = listar_historial_nc(
        db, current_member.organization_id,
        fecha_desde=fecha_desde or None, fecha_hasta=fecha_hasta or None,
        motivo=motivo or None, q_comprobante=q_comprobante or None,
        q_colegiado=q_colegiado or None,
    )
    return templates.TemplateResponse("pages/decano/partials/historial_nc.html", {
        "request": request, "historial": historial,
    })


@router.get("/kpis", response_class=HTMLResponse)
async def decano_kpis(
    request: Request,
    db: Session = Depends(get_db),
    current_member: Member = Depends(require_decano),
):
    org_id = current_member.organization_id

    # Mismo conteo que el Padrón del Centro de Reportes (una sola fuente).
    from app.services.colegiados_padron_service import composicion_padron
    comp = composicion_padron(db, org_id)
    por = {b["key"]: b["n"] for b in comp["buckets"]}

    r2 = db.execute(text("""
        SELECT COALESCE(SUM(amount),0) as total_mes, COUNT(*) as pagos_mes
        FROM payments
        WHERE organization_id = :org
          AND created_at >= date_trunc('month', now())
    """), {"org": org_id}).fetchone()

    # Deuda pendiente = la deuda total única (la que usa la habilidad), sumada sobre
    # el padrón. Antes filtraba status='pendiente', un valor que no existe: daba S/ 0.00.
    from app.services.conciliacion_deuda_service import deuda_total_padron
    deuda = deuda_total_padron(db, org_id)

    kpis = {
        "total_colegiados": comp["total"],
        "habiles": por.get("habil", 0),
        "vitalicios": por.get("vitalicio", 0),
        "inhabiles": por.get("inhabil", 0),
        "otros": comp["total"] - por.get("habil", 0) - por.get("vitalicio", 0) - por.get("inhabil", 0),
        "recaudado_mes": float(r2[0]),
        "pagos_mes": r2[1],
        "deuda_pendiente": deuda["total"],
        "deudores": deuda["colegiados_con_deuda"],
    }

    html = f"""
    <div class="kpi-grid">
      <div class="kpi-card">
        <div class="kpi-label">Total Colegiados</div>
        <div class="kpi-value">{kpis['total_colegiados']:,}</div>
        <div class="kpi-detail">{kpis['habiles']:,} hábiles · {kpis['vitalicios']:,} vitalicios · {kpis['inhabiles']:,} inhábiles · {kpis['otros']:,} otros</div>
      </div>
      <div class="kpi-card">
        <div class="kpi-label">Recaudado Este Mes</div>
        <div class="kpi-value" style="font-size:24px;">S/ {kpis['recaudado_mes']:,.2f}</div>
        <div class="kpi-detail">{kpis['pagos_mes']} pagos registrados</div>
      </div>
      <div class="kpi-card">
        <div class="kpi-label">Deuda Pendiente</div>
        <div class="kpi-value" style="font-size:24px;color:var(--dec-red);">S/ {kpis['deuda_pendiente']:,.2f}</div>
        <div class="kpi-detail">saldo por cobrar de {kpis['deudores']:,} colegiados</div>
      </div>
    </div>
    """
    return HTMLResponse(html)


@router.get("/mi-estado", response_class=HTMLResponse)
async def decano_mi_estado(
    request: Request,
    db: Session = Depends(get_db),
    current_member: Member = Depends(require_decano),
):
    col = db.query(Colegiado).filter(
        Colegiado.member_id == current_member.id
    ).first()

    if not col:
        return HTMLResponse('<p style="color:var(--dec-muted);font-style:italic;">Sin vínculo de colegiado asociado.</p>')

    condicion_color = {
        "habil":    "var(--dec-green)",
        "vitalicio":"var(--dec-gold)",
    }.get(col.condicion, "var(--dec-red)")

    mes  = col.mes_pagado_hasta  or "—"
    anio = col.anio_pagado_hasta or ""

    return HTMLResponse(f"""
    <table class="dec-table">
      <tr>
        <td class="label">Matrícula</td>
        <td class="value">{col.codigo_matricula or "—"}</td>
      </tr>
      <tr>
        <td class="label">Condición</td>
        <td class="value" style="color:{condicion_color};text-transform:uppercase;">{col.condicion}</td>
      </tr>
      <tr>
        <td class="label">Cuota al día hasta</td>
        <td class="value">{mes} / {anio}</td>
      </tr>
    </table>
    """)