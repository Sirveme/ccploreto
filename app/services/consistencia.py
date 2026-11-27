"""
app/services/consistencia.py — Diagnóstico de consistencia de la deuda de un colegiado con fraccionamiento.

Solo LEE: no cambia datos. Responde, para un colegiado, por qué pueden diferir los totales de deuda entre
pantallas y qué del plan no cuadra.

Referencia (la deuda «única», la misma que usa la habilidad): `deuda_total_colegiado`
  = deudas 'pending'/'partial' con gestión 'vigente'/'en_cobranza' + saldo del plan activo.

Las deudas ORIGINALES de un plan quedan con estado_gestion='fraccionada': las representa el plan. Las cuotas
del propio plan (debt_type='fraccionamiento') TAMBIÉN llevan 'fraccionada' y sí son deuda exigible.
"""
from sqlalchemy import text
from sqlalchemy.orm import Session


def _r2(x):
    return round(float(x or 0) + 0.0, 2)


def verificar_consistencia_fraccionamiento(db: Session, colegiado_id: int, organization_id: int = 1) -> dict:
    """Devuelve:
      deuda_vigente           deudas 'vigente'/'en_cobranza' pendientes (sin cuotas de plan)
      deuda_fraccionada       deudas ORIGINALES 'fraccionada' con saldo (por estado de su plan)
      saldo_fracc             saldo_pendiente de los planes activos
      cuotas_plan_pendientes  saldo de las cuotas pendientes del plan activo (deudas debt_type='fraccionamiento')
      deuda_unica             la deuda total del sistema (misma que la habilidad)
      suma_antes / suma_despues  lo que sumaban las pantallas que totalizan Debt.balance, antes y después
                              del filtro de la tanda 19 (originales 'fraccionada' fuera)
      diferencia              suma_antes − suma_despues (originales 'fraccionada' que se colaban)
      advertencias            lista en lenguaje simple
      consistente             True si no hay advertencias
    """
    p = {"c": colegiado_id}
    q = lambda sql: db.execute(text(sql), p)

    deuda_vigente = q("""SELECT coalesce(sum(balance),0) FROM debts WHERE colegiado_id=:c
        AND status IN ('pending','partial') AND estado_gestion IN ('vigente','en_cobranza')
        AND coalesce(debt_type,'') <> 'fraccionamiento'""").scalar()

    fracc_por_plan = q("""SELECT coalesce(f.estado, CASE WHEN d.fraccionamiento_id IS NULL THEN 'sin plan' ELSE 'plan inexistente' END) AS plan,
            count(*) AS n, coalesce(sum(d.balance),0) AS s
        FROM debts d LEFT JOIN fraccionamientos f ON f.id = d.fraccionamiento_id
        WHERE d.colegiado_id=:c AND d.status IN ('pending','partial') AND d.balance > 0
          AND coalesce(d.estado_gestion,'')='fraccionada' AND coalesce(d.debt_type,'') <> 'fraccionamiento'
        GROUP BY 1""").fetchall()
    deuda_fraccionada = sum(float(r.s) for r in fracc_por_plan)

    planes = q("""SELECT id, numero_solicitud, saldo_pendiente FROM fraccionamientos
        WHERE colegiado_id=:c AND estado='activo' ORDER BY id""").fetchall()
    saldo_fracc = sum(float(x.saldo_pendiente or 0) for x in planes)
    cuotas_plan = q("""SELECT coalesce(sum(d.balance),0) FROM debts d JOIN fraccionamientos f ON f.id=d.fraccionamiento_id
        WHERE d.colegiado_id=:c AND f.estado='activo' AND d.debt_type='fraccionamiento'
          AND d.status IN ('pending','partial')""").scalar()

    # Lo que sumaban las pantallas (Debt.balance pending/partial con el filtro de absorbidas por plan activo)
    base = """SELECT coalesce(sum(d.balance),0) FROM debts d WHERE d.colegiado_id=:c AND d.status IN ('pending','partial')
        AND NOT (d.fraccionamiento_id IS NOT NULL AND coalesce(d.debt_type,'') <> 'fraccionamiento'
                 AND EXISTS (SELECT 1 FROM fraccionamientos f WHERE f.id=d.fraccionamiento_id AND f.estado='activo'))"""
    suma_antes = q(base).scalar()
    suma_despues = q(base + """ AND NOT (coalesce(d.estado_gestion,'')='fraccionada'
        AND coalesce(d.debt_type,'') <> 'fraccionamiento')""").scalar()

    condonada = q("""SELECT count(*) AS n, coalesce(sum(balance),0) AS s FROM debts WHERE colegiado_id=:c
        AND status IN ('pending','partial') AND balance > 0 AND estado_gestion='condonada'""").fetchone()

    from app.services.conciliacion_deuda_service import deuda_total_colegiado
    deuda_unica = deuda_total_colegiado(db, colegiado_id, organization_id)

    adv = []
    for r in fracc_por_plan:
        if r.plan != "activo":
            adv.append("%d deuda(s) original(es) ya fraccionada(s) (plan %s) por S/ %.2f se sumaban como deuda; "
                       "desde la tanda 19 ya no." % (r.n, r.plan, float(r.s)))
    if len(planes) > 1:
        adv.append("Tiene %d planes activos a la vez (%s)." % (len(planes), ", ".join(x.numero_solicitud or str(x.id) for x in planes)))
    if planes and abs(saldo_fracc - float(cuotas_plan or 0)) > 0.01:
        adv.append("El saldo del plan (S/ %.2f) no coincide con sus cuotas pendientes (S/ %.2f)." % (saldo_fracc, float(cuotas_plan or 0)))
    if condonada and float(condonada.s) > 0:
        adv.append("%d deuda(s) condonada(s) conservan saldo (S/ %.2f): no cuentan en la deuda del sistema."
                   % (condonada.n, float(condonada.s)))
    despues_vs_unica = _r2(float(suma_despues) - float(deuda_unica))
    if abs(despues_vs_unica) > 0.01:
        adv.append("Las pantallas que suman deudas muestran S/ %.2f y la deuda del sistema es S/ %.2f (diferencia S/ %.2f: "
                   "condonadas con saldo, cuotas ordinarias no computables o cuotas de plan desalineadas)."
                   % (float(suma_despues), float(deuda_unica), despues_vs_unica))

    return {
        "colegiado_id": colegiado_id,
        "deuda_vigente": _r2(deuda_vigente),
        "deuda_fraccionada": _r2(deuda_fraccionada),
        "saldo_fracc": _r2(saldo_fracc),
        "cuotas_plan_pendientes": _r2(cuotas_plan),
        "deuda_unica": _r2(deuda_unica),
        "suma_antes": _r2(suma_antes),
        "suma_despues": _r2(suma_despues),
        "diferencia": _r2(float(suma_antes) - float(suma_despues)),
        "advertencias": adv,
        "consistente": not adv,
    }
