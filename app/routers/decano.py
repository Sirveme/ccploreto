from fastapi import APIRouter, Depends, Request, HTTPException
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session
from sqlalchemy import text

from app.database import get_db
from app.models import User, Member, Colegiado
from app.routers.dashboard import get_current_member

templates = Jinja2Templates(directory="app/templates")
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


@router.get("/kpis", response_class=HTMLResponse)
async def decano_kpis(
    request: Request,
    db: Session = Depends(get_db),
    current_member: Member = Depends(require_decano),
):
    org_id = current_member.organization_id

    r = db.execute(text("""
        SELECT
          COUNT(*) as total,
          COUNT(*) FILTER (WHERE condicion IN ('habil','vitalicio')) as al_dia,
          COUNT(*) FILTER (WHERE condicion NOT IN ('habil','vitalicio')) as inhabiles
        FROM colegiados WHERE organization_id = :org
    """), {"org": org_id}).fetchone()

    r2 = db.execute(text("""
        SELECT COALESCE(SUM(amount),0) as total_mes, COUNT(*) as pagos_mes
        FROM payments
        WHERE organization_id = :org
          AND created_at >= date_trunc('month', now())
    """), {"org": org_id}).fetchone()

    r3 = db.execute(text("""
        SELECT COALESCE(SUM(balance),0)
        FROM debts
        WHERE organization_id = :org AND status = 'pendiente'
    """), {"org": org_id}).fetchone()

    kpis = {
        "total_colegiados": r[0],
        "al_dia": r[1],
        "inhabiles": r[2],
        "recaudado_mes": float(r2[0]),
        "pagos_mes": r2[1],
        "deuda_pendiente": float(r3[0]),
    }

    html = f"""
    <div class="kpi-grid">
      <div class="kpi-card">
        <div class="kpi-label">Total Colegiados</div>
        <div class="kpi-value">{kpis['total_colegiados']}</div>
        <div class="kpi-detail">{kpis['al_dia']} al día · {kpis['inhabiles']} inhábiles</div>
      </div>
      <div class="kpi-card">
        <div class="kpi-label">Recaudado Este Mes</div>
        <div class="kpi-value" style="font-size:24px;">S/ {kpis['recaudado_mes']:,.2f}</div>
        <div class="kpi-detail">{kpis['pagos_mes']} pagos registrados</div>
      </div>
      <div class="kpi-card">
        <div class="kpi-label">Deuda Pendiente</div>
        <div class="kpi-value" style="font-size:24px;color:var(--dec-red);">S/ {kpis['deuda_pendiente']:,.2f}</div>
        <div class="kpi-detail">saldo por cobrar</div>
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