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
- Hábil aportante (CRITERIO ÚNICO, Fase 1) = condicion='habil'
    AND COALESCE(aporta_jdccpp, TRUE)
    AND (habilidad_vence IS NULL OR habilidad_vence >= fecha_corte)
  NULL en habilidad_vence CUENTA (hábil sin corte registrado; ej. alta reciente).
  'vitalicio' NO cuenta (queda fuera por condición). Un colegiado nuevo su primer
  periodo puede computar como hábil Y como nuevo (doble cómputo, no excluyente).

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

# ── CRITERIO ÚNICO DE HÁBIL APORTANTE (Fase 1) ──────────────────────────────
# Única fuente de verdad. Reemplaza el criterio antiguo (que exigía
# habilidad_vence >= corte y por tanto excluía a los NULL). Usar SIEMPRE con el
# bind :fecha_corte y organization_id = :org.
HABIL_WHERE = (
    "condicion = 'habil' "
    "AND COALESCE(aporta_jdccpp, TRUE) = TRUE "
    "AND (habilidad_vence IS NULL OR habilidad_vence >= :fecha_corte)"
)
# Criterio ANTIGUO (solo para medir y registrar la diferencia al recalcular).
HABIL_WHERE_LEGACY = (
    "condicion = 'habil' "
    "AND COALESCE(aporta_jdccpp, TRUE) = TRUE "
    "AND habilidad_vence >= :fecha_corte"
)


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

    # ── NUEVOS: DER-COL PAGADO AL 100% (por estado de deuda, no por texto de notes) ──
    # Fase 1 DER-COL: DER-COL ahora es una Debt con saldo. Un colegiado cuenta como
    # "nuevo" SOLO cuando su deuda DER-COL está totalmente pagada (status='paid').
    # Un pago PARCIAL de DER-COL NO habilita como nuevo. El periodo al que pertenece
    # es el mes del ÚLTIMO pago aplicado (el que completó el 100%).
    nuevos_con_pago = db.execute(text("""
        SELECT
            c.id AS colegiado_id,
            c.codigo_matricula,
            c.apellidos_nombres,
            c.dni,
            c.fecha_colegiatura,
            MAX(p.id) AS payment_id,
            MAX(p.created_at) AS fecha_pago_der_col,
            d.amount AS monto_pagado
        FROM debts d
        JOIN colegiados c ON c.id = d.colegiado_id
        JOIN conceptos_cobro cc ON cc.id = d.concepto_cobro_id AND cc.codigo = 'DER-COL'
        JOIN payment_debts pd ON pd.debt_id = d.id
        JOIN payments p ON p.id = pd.payment_id AND p.status IN ('approved', 'pagado')
        WHERE d.organization_id = :org
          AND d.status = 'paid'                         -- 100% pagado (saldo 0)
          AND COALESCE(c.aporta_jdccpp, TRUE) = TRUE    -- excluir exonerados (Past Decano)
          -- Fase 1 aportes (D): transeúnte CON colegio de origen NO genera aporte por nuevo.
          AND NOT (COALESCE(c.es_transeunte, FALSE) = TRUE AND c.colegio_origen IS NOT NULL)
          -- Aporte único por colegiado: excluir si ya está en OTRO periodo (<> :pid).
          AND NOT EXISTS (
            SELECT 1 FROM aporte_detalle_nuevos adn
            WHERE adn.colegiado_id = c.id AND adn.aporte_periodo_id <> :pid
          )
        GROUP BY c.id, c.codigo_matricula, c.apellidos_nombres, c.dni,
                 c.fecha_colegiatura, d.amount
        -- El mes de completado (último pago) debe caer en este periodo.
        HAVING MAX(p.created_at) >= :inicio AND MAX(p.created_at) < :fin
        ORDER BY c.id
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
          -- Fase 1 aportes (D): un transeúnte con colegio de origen no debe
          -- alertarse como "nuevo sin pago": no genera aporte por nuevo.
          AND NOT (COALESCE(c.es_transeunte, FALSE) = TRUE AND c.colegio_origen IS NOT NULL)
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
                    f"fecha_colegiatura en este periodo pero su DER-COL NO está pagado "
                    f"al 100% (pendiente o parcial). No cuenta como nuevo hasta "
                    f"completar el saldo."),
        })

    # ── Totales (nuevos = lo efectivamente registrado en el detalle) ──
    totales = db.execute(text("""
        SELECT COUNT(*) AS cantidad, COALESCE(SUM(monto_aporte), 0) AS total
        FROM aporte_detalle_nuevos
        WHERE aporte_periodo_id = :pid
    """), {"pid": periodo_id}).fetchone()

    cantidad_nuevos = totales.cantidad
    monto_nuevos = float(totales.total)

    # Criterio ÚNICO de hábil (NULL en habilidad_vence cuenta).
    habiles_row = db.execute(text(f"""
        SELECT COUNT(*) AS cnt
        FROM colegiados
        WHERE organization_id = :org AND {HABIL_WHERE}
    """), {"org": organizacion_id, "fecha_corte": fecha_corte}).fetchone()

    cantidad_habiles = habiles_row.cnt if habiles_row else 0
    monto_habiles = cantidad_habiles * float(config.monto_por_habil)
    monto_total = monto_nuevos + monto_habiles

    # Diferencia vs criterio antiguo (los NULL de habilidad_vence que ahora
    # entran). No se esconde: se anota en el detalle del log de recálculo.
    legacy_row = db.execute(text(f"""
        SELECT COUNT(*) AS cnt
        FROM colegiados
        WHERE organization_id = :org AND {HABIL_WHERE_LEGACY}
    """), {"org": organizacion_id, "fecha_corte": fecha_corte}).fetchone()
    cantidad_habiles_legacy = legacy_row.cnt if legacy_row else 0
    delta_habiles = cantidad_habiles - cantidad_habiles_legacy

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
                f"{len(pendientes_registro)} pendientes + {cantidad_habiles} hábiles"
                + (f" (criterio nuevo: +{delta_habiles} con habilidad_vence NULL vs "
                   f"criterio antiguo {cantidad_habiles_legacy})" if delta_habiles else "")),
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
# PIEZA C — VENCIMIENTO POR CALENDARIO (Opción M: SOLO ALERTA)
# ════════════════════════════════════════════════════════════════
# El cron YA NO cierra periodos. Al pasar (fin de mes + días de gracia) solo
# marca el periodo como vencido levantando una alerta 'cierre_vencido' (sin
# cambiar estado). TODO cierre es MANUAL, con panel de revisión previa y acuse
# del Administrador (ver cerrar_periodo_manual). Ningún periodo llega a 'cerrado'
# sin usuario en cerrado_por.

def cerrar_periodos_vencidos(db: Session) -> int:
    """Cron diario: NO cierra. Marca los periodos abiertos ya vencidos con una
    alerta 'cierre_vencido' (idempotente: no duplica si ya hay una sin resolver).

    Retorna cuántas alertas de vencimiento se levantaron en esta corrida.
    (Se conserva el nombre por compatibilidad con el scheduler.)
    """
    ahora = datetime.now(TZ_PERU).date()

    pendientes = db.execute(text("""
        SELECT ap.id, ap.anio, ap.mes, jca.dia_cierre_gracia
        FROM aporte_periodos ap
        JOIN junta_config_aporte jca ON jca.junta_id = ap.junta_id
        WHERE ap.estado = 'abierto'
    """)).fetchall()

    alertados = 0
    for p in pendientes:
        _, ultimo_dia = monthrange(p.anio, p.mes)
        fin_mes = date(p.anio, p.mes, ultimo_dia)
        cierre_efectivo = fin_mes + timedelta(days=p.dia_cierre_gracia or 5)
        if ahora <= cierre_efectivo:
            continue

        ya = db.execute(text("""
            SELECT 1 FROM aporte_periodo_alerta
            WHERE aporte_periodo_id = :pid AND tipo = 'cierre_vencido' AND resuelto = FALSE
            LIMIT 1
        """), {"pid": p.id}).fetchone()
        if ya:
            continue

        dias_vencido = (ahora - cierre_efectivo).days
        db.execute(text("""
            INSERT INTO aporte_periodo_alerta (
                aporte_periodo_id, tipo, colegiado_id, mensaje, created_at
            ) VALUES (:pid, 'cierre_vencido', NULL, :msg, NOW())
        """), {
            "pid": p.id,
            "msg": (f"Periodo {p.anio}-{p.mes:02d} vencido hace {dias_vencido} día(s) "
                    f"(límite {cierre_efectivo.isoformat()}). Pendiente de cierre manual "
                    f"con revisión previa del Administrador."),
        })
        alertados += 1

    db.commit()
    if alertados:
        logger.info(f"[aportes] {alertados} periodo(s) marcado(s) como vencido(s) (sin cerrar)")
    return alertados


# ════════════════════════════════════════════════════════════════
# ETAPA DEL PERIODO (B2) — una sola etapa derivada, sin columna 'pagado'
# ════════════════════════════════════════════════════════════════

def etapa_periodo(estado, aprobado, monto_total, deposito_monto):
    """Deriva la etapa única del periodo: Abierto / Cerrado / Aprobado / Pagado.

    - pagado = COALESCE(SUM(depósitos),0) >= monto_total  (con monto_total > 0)
    - 'Pagado' SOLO si aprobado=TRUE. Depósito suficiente pero SIN aprobación →
      etapa 'Cerrado' con inconsistencia=True (nunca 'Pagado').
    Retorna dict {etapa, inconsistencia, nota}.
    """
    total = float(monto_total or 0)
    dep = float(deposito_monto or 0)
    pagado = total > 0 and dep >= total

    if (estado or "").lower() == "abierto":
        return {"etapa": "Abierto", "inconsistencia": False, "nota": None}

    # estado == 'cerrado' (o cualquier no-abierto)
    if not aprobado:
        if dep > 0:
            return {"etapa": "Cerrado", "inconsistencia": True,
                    "nota": "Depósito registrado sin aprobación del Administrador."}
        return {"etapa": "Cerrado", "inconsistencia": False, "nota": None}

    if pagado:
        return {"etapa": "Pagado", "inconsistencia": False, "nota": None}
    return {"etapa": "Aprobado", "inconsistencia": False, "nota": None}


# ════════════════════════════════════════════════════════════════
# PANEL DE REVISIÓN PREVIA AL CIERRE (B8) — solo lectura
# ════════════════════════════════════════════════════════════════

def datos_revision_cierre(db: Session, periodo_id: int, organizacion_id: int = 1,
                          umbral_variacion: float = 5.0):
    """Reúne lo que el Administrador debe acusar antes de cerrar (no muta nada):
    (a) alertas de nuevos sin pago; (b) hábiles con habilidad_vence NULL que el
    criterio nuevo va a contar; (c) total de aportantes y variación vs el periodo
    anterior. Retorna dict o None si el periodo no existe."""
    per = db.execute(text("""
        SELECT ap.id, ap.anio, ap.mes, ap.estado,
               ap.cantidad_nuevos, ap.cantidad_habiles
        FROM aporte_periodos ap
        WHERE ap.id = :pid AND ap.organizacion_id = :org
    """), {"pid": periodo_id, "org": organizacion_id}).fetchone()
    if not per:
        return None

    _, ultimo_dia = monthrange(per.anio, per.mes)
    fecha_corte = datetime(per.anio, per.mes, ultimo_dia, 23, 59, 59, tzinfo=TZ_PERU)

    # (a) alertas de nuevos sin pago aún sin resolver
    alertas = db.execute(text("""
        SELECT id, colegiado_id, mensaje, created_at
        FROM aporte_periodo_alerta
        WHERE aporte_periodo_id = :pid AND tipo = 'colegiado_sin_pago' AND resuelto = FALSE
        ORDER BY created_at
    """), {"pid": periodo_id}).fetchall()

    # (b) hábiles con habilidad_vence NULL que el criterio nuevo va a contar
    habiles_null = db.execute(text("""
        SELECT id, codigo_matricula, apellidos_nombres, dni
        FROM colegiados
        WHERE organization_id = :org
          AND condicion = 'habil'
          AND COALESCE(aporta_jdccpp, TRUE) = TRUE
          AND habilidad_vence IS NULL
        ORDER BY apellidos_nombres
    """), {"org": organizacion_id}).fetchall()

    # (c) total de aportantes de ESTE periodo (hábiles criterio nuevo + nuevos)
    habiles_row = db.execute(text(f"""
        SELECT COUNT(*) AS cnt FROM colegiados
        WHERE organization_id = :org AND {HABIL_WHERE}
    """), {"org": organizacion_id, "fecha_corte": fecha_corte}).fetchone()
    total_habiles = habiles_row.cnt if habiles_row else 0
    total_nuevos = per.cantidad_nuevos or 0
    total_actual = total_habiles + total_nuevos

    # periodo anterior (mes-1) para la variación
    if per.mes == 1:
        pa_anio, pa_mes = per.anio - 1, 12
    else:
        pa_anio, pa_mes = per.anio, per.mes - 1
    prev = db.execute(text("""
        SELECT COALESCE(cantidad_habiles, 0) + COALESCE(cantidad_nuevos, 0) AS total
        FROM aporte_periodos
        WHERE organizacion_id = :org AND anio = :a AND mes = :m
    """), {"org": organizacion_id, "a": pa_anio, "m": pa_mes}).fetchone()
    total_anterior = prev.total if prev else None

    variacion_pct = None
    supera_umbral = False
    if total_anterior:
        variacion_pct = round((total_actual - total_anterior) * 100.0 / total_anterior, 1)
        supera_umbral = abs(variacion_pct) > umbral_variacion

    return {
        "periodo_id": periodo_id,
        "estado": per.estado,
        "alertas": [{"id": a.id, "colegiado_id": a.colegiado_id, "mensaje": a.mensaje}
                    for a in alertas],
        "habiles_null_vence": [{"id": h.id, "codigo_matricula": h.codigo_matricula,
                                "apellidos_nombres": h.apellidos_nombres, "dni": h.dni}
                               for h in habiles_null],
        "total_actual": total_actual,
        "total_anterior": total_anterior,
        "periodo_anterior_label": f"{pa_anio}-{pa_mes:02d}",
        "variacion_pct": variacion_pct,
        "umbral": umbral_variacion,
        "supera_umbral": supera_umbral,
    }


# ════════════════════════════════════════════════════════════════
# CIERRE MANUAL CON CONGELADO DEL NOMINAL + RESOLUCIÓN DE ALERTAS + ACUSE
# ════════════════════════════════════════════════════════════════
# Causales válidas para resolver una alerta 'colegiado_sin_pago' (B5).
_CAUSAS_ALERTA = ("pago_fuera", "pago_incompleto", "transeunte_con_origen", "otro")


def cerrar_periodo_manual(db: Session, periodo_id: int, user_id: int,
                          causas: dict | None = None, organizacion_id: int = 1) -> dict:
    """Cierra un periodo abierto de forma MANUAL (Opción M). Orden:
      1) valida periodo abierto,
      2) exige causal para CADA alerta de nuevo-sin-pago (B5) y las resuelve,
      3) recalcula totales con el criterio único de hábil,
      4) CONGELA el nominal (hábiles + nuevos) en aporte_detalle_habiles (B3/B4:
         doble cómputo — un nuevo lleva computa_habil y computa_nuevo),
      5) marca estado='cerrado', cerrado_por=user_id, snapshot de config,
         detalle_habiles_disponible=TRUE, fecha_corte si faltaba,
      6) registra el acuse 'revision_previa_acuse' + el 'cierre_manual' en el log.

    Lanza ValueError con mensaje si algo impide cerrar (el router lo traduce a 400).
    """
    causas = causas or {}

    per = db.execute(text("""
        SELECT ap.*, org.junta_id
        FROM aporte_periodos ap
        JOIN organizations org ON org.id = ap.organizacion_id
        WHERE ap.id = :pid AND ap.organizacion_id = :org
    """), {"pid": periodo_id, "org": organizacion_id}).fetchone()
    if not per:
        raise ValueError("Periodo no encontrado")
    if (per.estado or "").lower() == "cerrado":
        raise ValueError("El periodo ya está cerrado (inmutable)")

    cfg = db.execute(text("""
        SELECT * FROM junta_config_aporte
        WHERE junta_id = :j AND vigencia_desde <= :hoy
          AND (vigencia_hasta IS NULL OR vigencia_hasta >= :hoy)
        ORDER BY vigencia_desde DESC LIMIT 1
    """), {"j": per.junta_id, "hoy": datetime.now(TZ_PERU).date()}).fetchone()
    if not cfg:
        raise ValueError("Sin configuración de aporte vigente")

    # 2) Resolver TODAS las alertas de nuevo-sin-pago con causal (B5).
    alertas = db.execute(text("""
        SELECT id FROM aporte_periodo_alerta
        WHERE aporte_periodo_id = :pid AND tipo = 'colegiado_sin_pago' AND resuelto = FALSE
    """), {"pid": periodo_id}).fetchall()
    faltan = [a.id for a in alertas if str(a.id) not in {str(k) for k in causas}]
    if faltan:
        raise ValueError(f"Faltan causales para {len(faltan)} alerta(s) de nuevos sin pago")

    for a in alertas:
        c = causas.get(str(a.id)) or causas.get(a.id) or {}
        causa = (c.get("causa") or "").strip()
        detalle = (c.get("detalle") or "").strip() or None
        if causa not in _CAUSAS_ALERTA:
            raise ValueError(f"Causal inválida para la alerta {a.id}")
        db.execute(text("""
            UPDATE aporte_periodo_alerta SET
                resuelto = TRUE, resuelto_at = NOW(),
                causa_resolucion = :causa, causa_detalle = :detalle,
                resuelto_por_user_id = :uid
            WHERE id = :aid
        """), {"causa": causa, "detalle": detalle, "uid": user_id, "aid": a.id})

    # 3) Recalcular totales con el criterio único.
    _, ultimo_dia = monthrange(per.anio, per.mes)
    fin_mes = date(per.anio, per.mes, ultimo_dia)
    fecha_corte = datetime(per.anio, per.mes, ultimo_dia, 23, 59, 59, tzinfo=TZ_PERU)
    monto_por_habil = float(cfg.monto_por_habil)

    tot_nuevos = db.execute(text("""
        SELECT COUNT(*) AS c, COALESCE(SUM(monto_aporte), 0) AS s
        FROM aporte_detalle_nuevos WHERE aporte_periodo_id = :pid
    """), {"pid": periodo_id}).fetchone()
    cn, mn = tot_nuevos.c, float(tot_nuevos.s)

    habiles = db.execute(text(f"""
        SELECT id AS colegiado_id, codigo_matricula, apellidos_nombres, dni,
               condicion, habilidad_vence
        FROM colegiados
        WHERE organization_id = :org AND {HABIL_WHERE}
        ORDER BY apellidos_nombres
    """), {"org": organizacion_id, "fecha_corte": fecha_corte}).fetchall()
    ch = len(habiles)
    mh = ch * monto_por_habil
    monto_total = mn + mh

    # 4) Congelar el nominal en aporte_detalle_habiles (idempotente).
    ids_nuevos = {r.colegiado_id for r in db.execute(text("""
        SELECT colegiado_id FROM aporte_detalle_nuevos
        WHERE aporte_periodo_id = :pid AND colegiado_id IS NOT NULL
    """), {"pid": periodo_id}).fetchall()}

    db.execute(text("DELETE FROM aporte_detalle_habiles WHERE aporte_periodo_id = :pid"),
               {"pid": periodo_id})

    ids_habiles = set()
    for h in habiles:
        ids_habiles.add(h.colegiado_id)
        es_nuevo = h.colegiado_id in ids_nuevos
        motivo = "Hábil al corte" + (" + nuevo del periodo (doble cómputo)" if es_nuevo else "")
        # Doble cómputo: si además es nuevo, suma el aporte de nuevo al hábil.
        monto_fila = monto_por_habil + (float(cfg.monto_por_nuevo) if es_nuevo else 0.0)
        db.execute(text("""
            INSERT INTO aporte_detalle_habiles (
                aporte_periodo_id, colegiado_id, codigo_matricula, apellidos_nombres,
                dni, condicion, habilidad_vence, computa_habil, computa_nuevo,
                motivo_inclusion, monto_aplicado, created_at
            ) VALUES (
                :pid, :cid, :mat, :nom, :dni, :cond, :hv, TRUE, :cn, :mot, :monto, NOW()
            )
        """), {
            "pid": periodo_id, "cid": h.colegiado_id, "mat": h.codigo_matricula,
            "nom": h.apellidos_nombres, "dni": h.dni, "cond": h.condicion,
            "hv": h.habilidad_vence, "cn": es_nuevo, "mot": motivo,
            "monto": monto_fila,
        })

    # Nuevos que NO cayeron en el roster de hábiles (raro: nuevo no-hábil):
    # se congelan igual con computa_nuevo=TRUE para no perder el aporte de nuevo.
    nuevos_sueltos = db.execute(text("""
        SELECT colegiado_id, codigo_matricula, apellidos_nombres, dni, monto_aporte
        FROM aporte_detalle_nuevos
        WHERE aporte_periodo_id = :pid AND colegiado_id IS NOT NULL
    """), {"pid": periodo_id}).fetchall()
    for n in nuevos_sueltos:
        if n.colegiado_id in ids_habiles:
            continue
        db.execute(text("""
            INSERT INTO aporte_detalle_habiles (
                aporte_periodo_id, colegiado_id, codigo_matricula, apellidos_nombres,
                dni, condicion, habilidad_vence, computa_habil, computa_nuevo,
                motivo_inclusion, monto_aplicado, created_at
            ) VALUES (
                :pid, :cid, :mat, :nom, :dni, NULL, NULL, FALSE, TRUE,
                'Nuevo del periodo (no hábil al corte)', :monto, NOW()
            )
        """), {"pid": periodo_id, "cid": n.colegiado_id, "mat": n.codigo_matricula,
               "nom": n.apellidos_nombres, "dni": n.dni,
               "monto": float(n.monto_aporte or 0)})

    # 5) Cerrar con snapshot de config + detalle disponible + fecha_corte.
    db.execute(text("""
        UPDATE aporte_periodos SET
            cantidad_nuevos = :cn, monto_nuevos = :mn,
            cantidad_habiles = :ch, monto_habiles = :mh, monto_total = :mt,
            estado = 'cerrado', cerrado_en = NOW(), cerrado_por = :uid,
            uit_aplicada = :uit, monto_por_nuevo_aplicado = :mpn, monto_por_habil_aplicado = :mph,
            pct_nuevo_aplicado = :pn, pct_habil_aplicado = :ph, base_cuota_aplicada = :bc,
            detalle_habiles_disponible = TRUE,
            fecha_corte = COALESCE(fecha_corte, :fcorte),
            updated_at = NOW()
        WHERE id = :pid
    """), {
        "cn": cn, "mn": mn, "ch": ch, "mh": mh, "mt": monto_total,
        "uid": str(user_id), "uit": cfg.base_uit,
        "mpn": cfg.monto_por_nuevo, "mph": cfg.monto_por_habil,
        "pn": cfg.pct_sobre_uit_nuevo, "ph": cfg.pct_sobre_cuota_habil,
        "bc": cfg.base_cuota_ordinaria, "fcorte": fin_mes, "pid": periodo_id,
    })

    # 6) Log: acuse de revisión previa + cierre manual.
    db.execute(text("""
        INSERT INTO aporte_periodo_log (
            aporte_periodo_id, cantidad_nuevos, monto_nuevos, cantidad_habiles,
            monto_habiles, monto_total, evento, detalle
        ) VALUES (:pid, :cn, :mn, :ch, :mh, :mt, 'revision_previa_acuse', :det)
    """), {"pid": periodo_id, "cn": cn, "mn": mn, "ch": ch, "mh": mh, "mt": monto_total,
           "det": f"Revisión previa acusada por user_id={user_id}"})
    db.execute(text("""
        INSERT INTO aporte_periodo_log (
            aporte_periodo_id, cantidad_nuevos, monto_nuevos, cantidad_habiles,
            monto_habiles, monto_total, evento, detalle
        ) VALUES (:pid, :cn, :mn, :ch, :mh, :mt, 'cierre_manual', :det)
    """), {"pid": periodo_id, "cn": cn, "mn": mn, "ch": ch, "mh": mh, "mt": monto_total,
           "det": (f"Cierre manual {per.anio}-{per.mes:02d} por user_id={user_id}: "
                   f"{ch} hábiles + {cn} nuevos, nominal congelado")})

    # Resolver también la alerta de vencimiento si existía.
    db.execute(text("""
        UPDATE aporte_periodo_alerta SET resuelto = TRUE, resuelto_at = NOW(),
            resuelto_por_user_id = :uid
        WHERE aporte_periodo_id = :pid AND tipo = 'cierre_vencido' AND resuelto = FALSE
    """), {"pid": periodo_id, "uid": user_id})

    db.commit()
    return {"periodo_id": periodo_id, "cantidad_habiles": ch, "cantidad_nuevos": cn,
            "monto_total": monto_total}
