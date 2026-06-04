"""
app/services/bingazo_service.py
────────────────────────────────
Lógica del módulo Bingazo (zClaude-95).
- Activar evento anual.
- Generar deudas para no-vitalicios.
- Gestionar asignación de cartones.
- Pedir/devolver adicionales.

NOTA sobre el esquema real (verificado en zClaude-95):
- `Debt` vive en app.models_debt_management; `amount`/`balance` son Float;
  `due_date` es DateTime(timezone). La exigibilidad NO depende de due_date
  sino de `estado_notificacion` (es_exigible == 'notificada'/'notif_tacita').
  Por eso la deuda Bingazo se crea con estado_notificacion por defecto
  ('no_notificada'): existe desde la activación pero NO es exigible ni
  inhabilita hasta que Finanzas la notifique. Esto cumple la regla
  "antes de la fecha límite no aparece como exigible".
- La UniqueConstraint de debts es (organization_id, colegiado_id,
  concepto_cobro_id, periodo). Para que obligatorios y adicionales convivan
  en el mismo año se usan periodos distintos: "<año>" y "<año>-ADIC".
"""
import logging
from datetime import datetime, date, time, timezone
from decimal import Decimal
from typing import Optional, Dict, Any
from sqlalchemy.orm import Session

from app.models import (
    BingazoEvento, BingazoAsignacion,
    Colegiado, Organization, ConceptoCobro,
)
from app.models_debt_management import Debt

logger = logging.getLogger(__name__)

# Condiciones de colegiado que SÍ reciben deuda automática.
# Vitalicios y fallecidos quedan fuera (vitalicios pueden pedir voluntariamente).
CONDICIONES_OBLIGADAS = ("habil", "inhabil", "suspendido")


def _due_datetime(fecha_limite: date) -> datetime:
    """Convierte la fecha límite (date) al DateTime(tz) que espera debts.due_date."""
    return datetime.combine(fecha_limite, time(23, 59, 59), tzinfo=timezone.utc)


class BingazoService:
    """Servicio para el manejo del Bingazo anual."""

    def __init__(self, db: Session, organization_id: int):
        self.db = db
        self.org_id = organization_id

    # ────────────────────────────────────────────────────────────────
    # Helpers internos
    # ────────────────────────────────────────────────────────────────
    def _concepto_bingazo_id(self) -> Optional[int]:
        """Devuelve el id del concepto EVT-BIN de la organización (o None)."""
        concepto = self.db.query(ConceptoCobro).filter(
            ConceptoCobro.organization_id == self.org_id,
            ConceptoCobro.codigo == "EVT-BIN",
        ).first()
        return concepto.id if concepto else None

    def _crear_debt(self, *, colegiado_id, concept, periodo, period_label,
                    monto: float, fecha_limite: date, concepto_id) -> Debt:
        deuda = Debt(
            colegiado_id        = colegiado_id,
            organization_id     = self.org_id,
            concepto_cobro_id   = concepto_id,
            concept             = concept,
            debt_type           = "bingazo",
            periodo             = periodo,
            period_label        = period_label,
            amount              = float(monto),
            balance             = float(monto),
            status              = "pending",
            estado_gestion      = "vigente",
            due_date            = _due_datetime(fecha_limite),
            fecha_generacion    = datetime.now(timezone.utc).date(),
            origen              = "caja",
            created_at          = datetime.now(timezone.utc),
        )
        self.db.add(deuda)
        self.db.flush()
        return deuda

    # ────────────────────────────────────────────────────────────────
    # ACTIVACIÓN
    # ────────────────────────────────────────────────────────────────
    def activar_evento(
        self,
        año: int,
        precio_unitario: Decimal,
        min_cartones: int,
        comision_pct: Decimal,
        fecha_limite: date,
        activado_por: str = "",
    ) -> Dict[str, Any]:
        """
        Activa el Bingazo del año indicado:
        - Crea fila en bingazo_evento (si ya existe, retorna error).
        - Para cada colegiado NO vitalicio: genera deuda y fila asignación.
        - Para vitalicios: NO se les genera nada (pueden pedir voluntariamente después).
        """
        # 1. Validar que no exista
        existente = self.db.query(BingazoEvento).filter(
            BingazoEvento.organization_id == self.org_id,
            BingazoEvento.año == año,
        ).first()
        if existente:
            return {
                "success": False,
                "error": f"Bingazo {año} ya está activado",
                "codigo": "YA_ACTIVADO",
                "evento_id": existente.id,
            }

        # 2. Crear evento
        evento = BingazoEvento(
            organization_id=self.org_id,
            año=año,
            precio_unitario=precio_unitario,
            min_cartones=min_cartones,
            comision_pct=comision_pct,
            fecha_limite=fecha_limite,
            estado="activo",
            activado_por=activado_por or "sistema",
        )
        self.db.add(evento)
        self.db.flush()

        # 3. Monto obligatorio por colegiado
        monto_oblig = float(Decimal(precio_unitario) * Decimal(min_cartones))
        concepto_id = self._concepto_bingazo_id()

        # 4. Colegiados obligados (hábiles + inhábiles + suspendidos; NO vitalicios/fallecidos)
        colegiados = self.db.query(Colegiado).filter(
            Colegiado.organization_id == self.org_id,
            Colegiado.condicion.in_(CONDICIONES_OBLIGADAS),
        ).all()

        creados = 0
        for col in colegiados:
            deuda = self._crear_debt(
                colegiado_id = col.id,
                concept      = f"Bingazo del Contador {año}",
                periodo      = str(año),
                period_label = f"Bingazo {año}",
                monto        = monto_oblig,
                fecha_limite = fecha_limite,
                concepto_id  = concepto_id,
            )
            asig = BingazoAsignacion(
                evento_id            = evento.id,
                colegiado_id         = col.id,
                debt_id_obligatorios = deuda.id,
                es_voluntario        = False,
            )
            self.db.add(asig)
            creados += 1

        self.db.commit()
        logger.info(f"Bingazo {año} activado: {creados} deudas generadas")
        return {
            "success": True,
            "evento_id": evento.id,
            "deudas_generadas": creados,
            "monto_total": float(monto_oblig * creados),
        }

    # ────────────────────────────────────────────────────────────────
    # OBTENER ESTADO POR COLEGIADO
    # ────────────────────────────────────────────────────────────────
    def obtener_estado_colegiado(self, colegiado_id: int, año: Optional[int] = None) -> Dict[str, Any]:
        """
        Estado del Bingazo para un colegiado:
        evento + asignación + deudas (obligatorios/adicionales) + cartones.
        """
        if año is None:
            año = datetime.now(timezone.utc).year

        evento = self.db.query(BingazoEvento).filter(
            BingazoEvento.organization_id == self.org_id,
            BingazoEvento.año == año,
        ).first()

        if not evento:
            return {"success": False, "error": f"No hay Bingazo {año} activado"}

        colegiado = self.db.query(Colegiado).filter(Colegiado.id == colegiado_id).first()
        if not colegiado:
            return {"success": False, "error": "Colegiado no encontrado"}

        asig = self.db.query(BingazoAsignacion).filter(
            BingazoAsignacion.evento_id == evento.id,
            BingazoAsignacion.colegiado_id == colegiado_id,
        ).first()

        es_vitalicio = colegiado.condicion == "vitalicio"
        evento_dict = {
            "id": evento.id, "año": evento.año,
            "precio_unitario": float(evento.precio_unitario),
            "min_cartones": evento.min_cartones,
            "comision_pct": float(evento.comision_pct),
            "fecha_limite": evento.fecha_limite.isoformat(),
            "estado": evento.estado,
        }

        # Vitalicio sin asignación: puede solicitar voluntariamente.
        if not asig and es_vitalicio:
            return {
                "success": True,
                "evento": evento_dict,
                "asignacion": None,
                "es_vitalicio": True,
                "tiene_asignacion": False,
            }

        if not asig:
            return {"success": False, "error": "Colegiado sin asignación en este evento"}

        deuda_oblig = self.db.query(Debt).filter(Debt.id == asig.debt_id_obligatorios).first() if asig.debt_id_obligatorios else None
        deuda_adic = self.db.query(Debt).filter(Debt.id == asig.debt_id_adicionales).first() if asig.debt_id_adicionales else None

        return {
            "success": True,
            "evento": evento_dict,
            "asignacion": {
                "id": asig.id,
                "cartones_obligatorios_rango": asig.cartones_obligatorios_rango,
                "cartones_obligatorios_entregados": asig.cartones_obligatorios_entregados,
                "cartones_adicionales_pedidos": asig.cartones_adicionales_pedidos,
                "cartones_adicionales_rango": asig.cartones_adicionales_rango,
                "cartones_adicionales_devueltos": asig.cartones_adicionales_devueltos,
                "cartones_adicionales_vendidos": asig.cartones_adicionales_vendidos,
                "es_voluntario": asig.es_voluntario,
            },
            "deuda_obligatorios": {
                "id": deuda_oblig.id,
                "monto": float(deuda_oblig.amount),
                "balance": float(deuda_oblig.balance),
                "status": deuda_oblig.status,
            } if deuda_oblig else None,
            "deuda_adicionales": {
                "id": deuda_adic.id,
                "monto": float(deuda_adic.amount),
                "balance": float(deuda_adic.balance),
                "status": deuda_adic.status,
            } if deuda_adic else None,
            "es_vitalicio": es_vitalicio,
            "tiene_asignacion": True,
        }

    # ────────────────────────────────────────────────────────────────
    # ENTREGAR OBLIGATORIOS
    # ────────────────────────────────────────────────────────────────
    def entregar_obligatorios(self, asignacion_id: int, rango: str = "", entregados: bool = True) -> Dict[str, Any]:
        """Marca como entregados los obligatorios. Rango es texto libre."""
        asig = self.db.query(BingazoAsignacion).filter(BingazoAsignacion.id == asignacion_id).first()
        if not asig:
            return {"success": False, "error": "Asignación no encontrada"}
        asig.cartones_obligatorios_rango = (rango or "").strip() or None
        asig.cartones_obligatorios_entregados = entregados
        asig.updated_at = datetime.now(timezone.utc)
        self.db.commit()
        return {"success": True, "asignacion_id": asig.id}

    # ────────────────────────────────────────────────────────────────
    # PEDIR ADICIONALES
    # ────────────────────────────────────────────────────────────────
    def pedir_adicionales(self, asignacion_id: int, cantidad: int, rango: str = "") -> Dict[str, Any]:
        """
        Aumenta cartones adicionales pedidos y ajusta/crea la deuda adicional.
        Precio unitario con comisión = precio_evento * (1 - comision_pct/100).
        Preserva lo ya pagado.
        """
        if cantidad < 1:
            return {"success": False, "error": "Cantidad inválida"}

        asig = self.db.query(BingazoAsignacion).filter(BingazoAsignacion.id == asignacion_id).first()
        if not asig:
            return {"success": False, "error": "Asignación no encontrada"}

        evento = self.db.query(BingazoEvento).filter(BingazoEvento.id == asig.evento_id).first()
        precio_con_desc = Decimal(evento.precio_unitario) * (Decimal("1") - Decimal(evento.comision_pct) / Decimal("100"))

        nuevo_total = (asig.cartones_adicionales_pedidos or 0) + cantidad
        nuevo_rango = ((asig.cartones_adicionales_rango or "") + (", " if asig.cartones_adicionales_rango else "") + (rango or "")).strip(", ") or None
        vendidos = nuevo_total - (asig.cartones_adicionales_devueltos or 0)
        monto_adic = float(precio_con_desc * Decimal(vendidos))

        if asig.debt_id_adicionales:
            deuda_adic = self.db.query(Debt).filter(Debt.id == asig.debt_id_adicionales).first()
            ya_pagado = float(deuda_adic.amount or 0) - float(deuda_adic.balance or 0)
            deuda_adic.amount = monto_adic
            deuda_adic.balance = max(0.0, monto_adic - ya_pagado)
        else:
            deuda_adic = self._crear_debt(
                colegiado_id = asig.colegiado_id,
                concept      = f"Bingazo {evento.año} — Cartones Adicionales",
                periodo      = f"{evento.año}-ADIC",
                period_label = f"Bingazo {evento.año} adic.",
                monto        = monto_adic,
                fecha_limite = evento.fecha_limite,
                concepto_id  = self._concepto_bingazo_id(),
            )
            asig.debt_id_adicionales = deuda_adic.id

        asig.cartones_adicionales_pedidos = nuevo_total
        asig.cartones_adicionales_rango = nuevo_rango
        asig.updated_at = datetime.now(timezone.utc)
        self.db.commit()
        return {"success": True, "total_pedidos": nuevo_total, "monto_adicionales": monto_adic}

    # ────────────────────────────────────────────────────────────────
    # DEVOLVER ADICIONALES
    # ────────────────────────────────────────────────────────────────
    def devolver_adicionales(self, asignacion_id: int, cantidad: int) -> Dict[str, Any]:
        """Devuelve N cartones adicionales no vendidos. Reduce la deuda."""
        if cantidad < 1:
            return {"success": False, "error": "Cantidad inválida"}

        asig = self.db.query(BingazoAsignacion).filter(BingazoAsignacion.id == asignacion_id).first()
        if not asig:
            return {"success": False, "error": "Asignación no encontrada"}

        max_devolvible = (asig.cartones_adicionales_pedidos or 0) - (asig.cartones_adicionales_devueltos or 0)
        if cantidad > max_devolvible:
            return {"success": False, "error": f"Solo puede devolver hasta {max_devolvible} cartones adicionales"}

        evento = self.db.query(BingazoEvento).filter(BingazoEvento.id == asig.evento_id).first()
        precio_con_desc = Decimal(evento.precio_unitario) * (Decimal("1") - Decimal(evento.comision_pct) / Decimal("100"))

        nuevo_devueltos = (asig.cartones_adicionales_devueltos or 0) + cantidad
        vendidos = (asig.cartones_adicionales_pedidos or 0) - nuevo_devueltos
        nuevo_monto = float(precio_con_desc * Decimal(vendidos))

        if asig.debt_id_adicionales:
            deuda_adic = self.db.query(Debt).filter(Debt.id == asig.debt_id_adicionales).first()
            ya_pagado = float(deuda_adic.amount or 0) - float(deuda_adic.balance or 0)
            deuda_adic.amount = nuevo_monto
            deuda_adic.balance = max(0.0, nuevo_monto - ya_pagado)
            if nuevo_monto == 0:
                deuda_adic.status = "anulada"
                deuda_adic.estado_gestion = "anulada"

        asig.cartones_adicionales_devueltos = nuevo_devueltos
        asig.updated_at = datetime.now(timezone.utc)
        self.db.commit()
        return {"success": True, "devueltos_total": nuevo_devueltos, "vendidos": vendidos, "nuevo_monto": nuevo_monto}

    # ────────────────────────────────────────────────────────────────
    # ASIGNAR A VITALICIO (voluntario)
    # ────────────────────────────────────────────────────────────────
    def asignar_voluntario(self, evento_id: int, colegiado_id: int, cartones: int = 0, rango: str = "") -> Dict[str, Any]:
        """Para vitalicios que voluntariamente solicitan cartones."""
        colegiado = self.db.query(Colegiado).filter(Colegiado.id == colegiado_id).first()
        if not colegiado:
            return {"success": False, "error": "Colegiado no encontrado"}
        if colegiado.condicion != "vitalicio":
            return {"success": False, "error": "Solo aplicable a vitalicios"}

        existente = self.db.query(BingazoAsignacion).filter(
            BingazoAsignacion.evento_id == evento_id,
            BingazoAsignacion.colegiado_id == colegiado_id,
        ).first()
        if existente:
            return {"success": False, "error": "Ya tiene asignación"}

        asig = BingazoAsignacion(
            evento_id     = evento_id,
            colegiado_id  = colegiado_id,
            es_voluntario = True,
        )
        self.db.add(asig)
        self.db.flush()

        if cartones > 0:
            res = self.pedir_adicionales(asig.id, cartones, rango)
            res["asignacion_id"] = asig.id
            return res

        self.db.commit()
        return {"success": True, "asignacion_id": asig.id}

    # ────────────────────────────────────────────────────────────────
    # ASIGNAR MANUAL (colegiado registrado después de activar)
    # ────────────────────────────────────────────────────────────────
    def asignar_manual(self, evento_id: int, colegiado_id: int) -> Dict[str, Any]:
        """Genera deuda obligatoria + asignación para un colegiado que no la tenía."""
        evento = self.db.query(BingazoEvento).filter(BingazoEvento.id == evento_id).first()
        if not evento:
            return {"success": False, "error": "Evento no encontrado"}

        existente = self.db.query(BingazoAsignacion).filter(
            BingazoAsignacion.evento_id == evento_id,
            BingazoAsignacion.colegiado_id == colegiado_id,
        ).first()
        if existente:
            return {"success": False, "error": "Ya tiene asignación", "asignacion_id": existente.id}

        monto_oblig = float(Decimal(evento.precio_unitario) * Decimal(evento.min_cartones))
        deuda = self._crear_debt(
            colegiado_id = colegiado_id,
            concept      = f"Bingazo del Contador {evento.año}",
            periodo      = str(evento.año),
            period_label = f"Bingazo {evento.año}",
            monto        = monto_oblig,
            fecha_limite = evento.fecha_limite,
            concepto_id  = self._concepto_bingazo_id(),
        )
        asig = BingazoAsignacion(
            evento_id            = evento_id,
            colegiado_id         = colegiado_id,
            debt_id_obligatorios = deuda.id,
            es_voluntario        = False,
        )
        self.db.add(asig)
        self.db.commit()
        return {"success": True, "asignacion_id": asig.id, "debt_id": deuda.id}
