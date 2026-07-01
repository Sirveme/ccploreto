"""
app/services/aportes_junta_service.py
Módulo Aportes a la Junta de Decanos (JDCCPP) — Piezas B y C.

Cálculo automático del periodo en curso + cierre por calendario.

Hechos verificados del sistema CCPL (no cambiar supuestos sin re-verificar):
- DER-COL (Derecho de Colegiatura) NO genera Debt → la detección de "nuevos con
  pago" es directa sobre payments.notes (ILIKE '%DER-COL%'), NO vía payment_debts.
- payments.status válidos: 'approved', 'pagado' (NO 'aprobado'/'verificado'/...).
- Nuevos sin pago en sistema se detectan por colegiados.fecha_colegiatura del mes
  y se levantan como ALERTA (no suman al total hasta registrarse en Pieza F).
- Hábiles = colegiados.condicion='habil' con habilidad_vence >= fin de mes.

El cálculo NO toca periodos en estado 'cerrado' (inmutables).
"""

from datetime import datetime, date, timedelta, timezone
from calendar import monthrange
import logging

from sqlalchemy import text
from sqlalchemy.orm import Session

logger = logging.getLogger(__name__)

# Perú = UTC-5 todo el año (sin DST). Determina a qué mes pertenece "ahora" y los
# límites del periodo; las comparaciones contra columnas tz-aware (UTC) las
# resuelve Postgres correctamente por el offset.
TZ_PERU = timezone(timedelta(hours=-5))


# ════════════════════════════════════════════════════════════════
# PIEZA B — CÁLCULO DEL PERIODO EN CURSO
# ════════════════════════════════════════════════════════════════

def calcular_periodo_actual(db: Session, organizacion_id: int = 1):
    """Recalcula el periodo del mes en curso. Solo afecta periodos 'abierto'.

    Retorna dict con totales o None si no hay Junta/config o el periodo ya cerró.
    No hace commit parcial: confirma todo al final (el llamador puede envolver).
    """
    ahora = datetime.now(TZ_PERU)
    anio = ahora.year
    mes = ahora.month

    org = db.execute(text("""
        SELECT o.junta_id
        FROM organizations o
        WHERE o.id = :org_id
    """), {"org_id": organizacion_id}).fetchone()

    if not org or not org.junta_id:
        logger.warning(f"[aportes] Organización {organizacion_id} sin Junta asignada")
        return None

    config = db.execute(text("""
        SELECT * FROM junta_config_aporte
        WHERE junta_id = :junta_id
          AND vigencia_desde <= :hoy
          AND (vigencia_hasta IS NULL OR vigencia_hasta >= :hoy)
        ORDER BY vigencia_desde DESC LIMIT 1
    """), {"junta_id": org.junta_id, "hoy": ahora.date()}).fetchone()

    if not config:
        logger.error(f"[aportes] Sin config vigente para junta {org.junta_id}")
        return None

    periodo = db.execute(text("""
        INSERT INTO aporte_periodos (
            organizacion_id, junta_id, anio, mes, estado, created_at, updated_at
        ) VALUES (:org, :junta, :anio, :mes, 'abierto', NOW(), NOW())
        ON CONFLICT (organizacion_id, anio, mes) DO UPDATE
        SET updated_at = NOW()
        RETURNING id, estado
    """), {
        "org": organizacion_id, "junta": org.junta_id, "anio": anio, "mes": mes
    }).fetchone()

    if periodo.estado == 'cerrado':
        logger.info(f"[aportes] Periodo {anio}-{mes:02d} ya cerrado, no se recalcula")
        return None

    periodo_id = periodo.id

    # Límites del mes en hora Perú (tz-aware).
    _, ultimo_dia = monthrange(anio, mes)
    fecha_corte = datetime(anio, mes, ultimo_dia, 23, 59, 59, tzinfo=TZ_PERU)
    inicio_mes = datetime(anio, mes, 1, tzinfo=TZ_PERU)
    inicio_mes_siguiente = (
        datetime(anio + 1, 1, 1, tzinfo=TZ_PERU) if mes == 12
        else datetime(anio, mes + 1, 1, tzinfo=TZ_PERU)
    )

    codigo_lote = f"LOTE-{anio}{mes:02d}-{organizacion_id:03d}"

    # ── NUEVOS con pago DER-COL detectado en payments ──
    nuevos_con_pago = db.execute(text("""
        SELECT DISTINCT ON (c.id)
            c.id AS colegiado_id,
            c.codigo_matricula,
            c.apellidos_nombres,
            c.dni,
            c.fecha_colegiatura,
            p.id AS payment_id,
            p.created_at AS fecha_pago_der_col,
            p.amount AS monto_pagado
        FROM payments p
        JOIN colegiados c ON c.id = p.colegiado_id
        WHERE p.organization_id = :org
          AND p.created_at >= :inicio
          AND p.created_at < :fin
          AND p.status IN ('approved', 'pagado')
          AND (
            p.notes ILIKE '%DER-COL%'
            OR p.notes ILIKE '%Derecho de Colegiatura%'
          )
          AND COALESCE(c.aporta_jdccpp, TRUE) = TRUE   -- excluir exonerados (Past Decano)
          -- NOTA INSTITUCIONAL: un colegiado nuevo aporta a la JDCCPP una sola vez.
          -- Se excluye si ya está en OTRO periodo (<> :pid). Se usa "<> :pid" y no un
          -- NOT EXISTS global para no auto-excluirse en el re-cálculo del propio periodo
          -- (que borra e reinserta sus filas 'pago_automatico' más abajo).
          AND NOT EXISTS (
            SELECT 1 FROM aporte_detalle_nuevos adn
            WHERE adn.colegiado_id = c.id AND adn.aporte_periodo_id <> :pid
          )
        ORDER BY c.id, p.created_at ASC
    """), {
        "org": organizacion_id,
        "inicio": inicio_mes,
        "fin": inicio_mes_siguiente,
        "pid": periodo_id,
    }).fetchall()

    # Limpiar SOLO los automáticos del periodo (preservar manual_caja y carga_historica).
    db.execute(text("""
        DELETE FROM aporte_detalle_nuevos
        WHERE aporte_periodo_id = :pid
          AND fuente_registro = 'pago_automatico'
    """), {"pid": periodo_id})

    for n in nuevos_con_pago:
        db.execute(text("""
            INSERT INTO aporte_detalle_nuevos (
                aporte_periodo_id, colegiado_id, payment_id,
                codigo_matricula, apellidos_nombres, dni,
                fecha_pago_der_col, fecha_colegiatura,
                monto_pagado, monto_aporte, codigo_lote,
                fuente_registro, created_at
            ) VALUES (
                :pid, :cid, :payid, :mat, :nom, :dni,
                :fpago, :fcol, :mpago, :maporte, :lote,
                'pago_automatico', NOW()
            )
            ON CONFLICT (aporte_periodo_id, colegiado_id) DO NOTHING
        """), {
            "pid": periodo_id, "cid": n.colegiado_id, "payid": n.payment_id,
            "mat": n.codigo_matricula, "nom": n.apellidos_nombres, "dni": n.dni,
            "fpago": n.fecha_pago_der_col, "fcol": n.fecha_colegiatura,
            "mpago": n.monto_pagado, "maporte": config.monto_por_nuevo, "lote": codigo_lote,
        })

    # ── ALERTA: altas del mes (fecha_colegiatura) sin pago registrado ──
    pendientes_registro = db.execute(text("""
        SELECT c.id, c.codigo_matricula, c.apellidos_nombres,
               c.fecha_colegiatura, c.dni
        FROM colegiados c
        WHERE c.organization_id = :org
          AND c.fecha_colegiatura >= :inicio
          AND c.fecha_colegiatura < :fin
          -- NOT EXISTS GLOBAL (cualquier periodo): si el colegiado ya fue reportado
          -- en otro mes (ej. cargado en Mayo), no vuelve a alertar en Junio aunque su
          -- fecha_colegiatura caiga aquí. Aporte único por colegiado a la JDCCPP.
          AND NOT EXISTS (
            SELECT 1 FROM aporte_detalle_nuevos adn
            WHERE adn.colegiado_id = c.id
          )
        ORDER BY c.codigo_matricula
    """), {
        "org": organizacion_id,
        "inicio": inicio_mes,
        "fin": inicio_mes_siguiente,
        "pid": periodo_id,
    }).fetchall()

    db.execute(text("""
        DELETE FROM aporte_periodo_alerta
        WHERE aporte_periodo_id = :pid AND tipo = 'colegiado_sin_pago'
    """), {"pid": periodo_id})

    for p in pendientes_registro:
        db.execute(text("""
            INSERT INTO aporte_periodo_alerta (
                aporte_periodo_id, tipo, colegiado_id, mensaje, created_at
            ) VALUES (
                :pid, 'colegiado_sin_pago', :cid, :msg, NOW()
            )
        """), {
            "pid": periodo_id, "cid": p.id,
            "msg": (f"Colegiado {p.codigo_matricula} ({p.apellidos_nombres}) tiene "
                    f"fecha_colegiatura en este periodo pero no se encontró pago de "
                    f"DER-COL en el sistema. Registrar desde 'Registrar Aporte por "
                    f"Nuevo Colegiado'."),
        })

    # ── Totales (nuevos = lo efectivamente registrado en el detalle) ──
    totales = db.execute(text("""
        SELECT COUNT(*) AS cantidad, COALESCE(SUM(monto_aporte), 0) AS total
        FROM aporte_detalle_nuevos
        WHERE aporte_periodo_id = :pid
    """), {"pid": periodo_id}).fetchone()

    cantidad_nuevos = totales.cantidad
    monto_nuevos = float(totales.total)

    habiles_row = db.execute(text("""
        SELECT COUNT(*) AS cnt
        FROM colegiados
        WHERE organization_id = :org
          AND condicion = 'habil'
          AND habilidad_vence >= :fecha_corte
          AND COALESCE(aporta_jdccpp, TRUE) = TRUE   -- excluir Past Decanos
    """), {"org": organizacion_id, "fecha_corte": fecha_corte}).fetchone()

    cantidad_habiles = habiles_row.cnt if habiles_row else 0
    monto_habiles = cantidad_habiles * float(config.monto_por_habil)
    monto_total = monto_nuevos + monto_habiles

    db.execute(text("""
        UPDATE aporte_periodos SET
            cantidad_nuevos = :cn, monto_nuevos = :mn,
            cantidad_habiles = :ch, monto_habiles = :mh,
            monto_total = :mt, codigo_lote = :lote,
            updated_at = NOW()
        WHERE id = :pid
    """), {
        "pid": periodo_id,
        "cn": cantidad_nuevos, "mn": monto_nuevos,
        "ch": cantidad_habiles, "mh": monto_habiles,
        "mt": monto_total, "lote": codigo_lote,
    })

    db.execute(text("""
        INSERT INTO aporte_periodo_log (
            aporte_periodo_id, cantidad_nuevos, monto_nuevos,
            cantidad_habiles, monto_habiles, monto_total, evento, detalle
        ) VALUES (
            :pid, :cn, :mn, :ch, :mh, :mt, 'recalculo_automatico', :det
        )
    """), {
        "pid": periodo_id,
        "cn": cantidad_nuevos, "mn": monto_nuevos,
        "ch": cantidad_habiles, "mh": monto_habiles, "mt": monto_total,
        "det": (f"Periodo {anio}-{mes:02d}: {cantidad_nuevos} nuevos registrados + "
                f"{len(pendientes_registro)} pendientes + {cantidad_habiles} hábiles"),
    })

    db.commit()

    return {
        "periodo_id": periodo_id,
        "anio": anio, "mes": mes,
        "cantidad_nuevos": cantidad_nuevos,
        "monto_nuevos": monto_nuevos,
        "cantidad_habiles": cantidad_habiles,
        "monto_habiles": monto_habiles,
        "monto_total": monto_total,
        "pendientes_registro": len(pendientes_registro),
    }


# ════════════════════════════════════════════════════════════════
# PIEZA C — CIERRE POR CALENDARIO
# ════════════════════════════════════════════════════════════════

def cerrar_periodos_vencidos(db: Session) -> int:
    """Cierra periodos abiertos cuyo (fin de mes + días de gracia) ya pasó.

    Un periodo cerrado queda inmutable: se toma snapshot de la config aplicada.
    Retorna cuántos periodos se cerraron.
    """
    ahora = datetime.now(TZ_PERU).date()

    pendientes = db.execute(text("""
        SELECT ap.id, ap.anio, ap.mes,
               ap.cantidad_nuevos, ap.monto_nuevos,
               ap.cantidad_habiles, ap.monto_habiles, ap.monto_total,
               jca.dia_cierre_gracia, jca.monto_por_nuevo, jca.monto_por_habil,
               jca.pct_sobre_uit_nuevo, jca.pct_sobre_cuota_habil,
               jca.base_uit, jca.base_cuota_ordinaria
        FROM aporte_periodos ap
        JOIN junta_config_aporte jca ON jca.junta_id = ap.junta_id
        WHERE ap.estado = 'abierto'
    """)).fetchall()

    cerrados = 0
    for p in pendientes:
        _, ultimo_dia = monthrange(p.anio, p.mes)
        fin_mes = date(p.anio, p.mes, ultimo_dia)
        cierre_efectivo = fin_mes + timedelta(days=p.dia_cierre_gracia or 5)

        if ahora > cierre_efectivo:
            db.execute(text("""
                UPDATE aporte_periodos SET
                    estado = 'cerrado',
                    cerrado_en = NOW(),
                    cerrado_por = 'automatico',
                    uit_aplicada = :uit,
                    monto_por_nuevo_aplicado = :mpn,
                    monto_por_habil_aplicado = :mph,
                    pct_nuevo_aplicado = :pn,
                    pct_habil_aplicado = :ph,
                    base_cuota_aplicada = :bc,
                    updated_at = NOW()
                WHERE id = :pid
            """), {
                "pid": p.id, "uit": p.base_uit,
                "mpn": p.monto_por_nuevo, "mph": p.monto_por_habil,
                "pn": p.pct_sobre_uit_nuevo, "ph": p.pct_sobre_cuota_habil,
                "bc": p.base_cuota_ordinaria,
            })

            db.execute(text("""
                INSERT INTO aporte_periodo_log (
                    aporte_periodo_id, cantidad_nuevos, monto_nuevos,
                    cantidad_habiles, monto_habiles, monto_total, evento, detalle
                ) VALUES (
                    :pid, :cn, :mn, :ch, :mh, :mt,
                    'cierre_automatico', 'Cerrado por calendario'
                )
            """), {
                "pid": p.id, "cn": p.cantidad_nuevos, "mn": p.monto_nuevos,
                "ch": p.cantidad_habiles, "mh": p.monto_habiles, "mt": p.monto_total,
            })
            cerrados += 1

    db.commit()
    if cerrados:
        logger.info(f"[aportes] {cerrados} periodo(s) cerrado(s) por calendario")
    return cerrados
