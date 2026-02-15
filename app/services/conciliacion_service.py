"""
Servicio: Motor de Conciliación Automática
app/services/conciliacion_service.py

Flujo:
1. Lee emails bancarios via Gmail API
2. Parsea cada email para extraer datos
3. Busca match en pagos registrados (monto + ventana de tiempo)
4. Marca como conciliado automáticamente o como "sin match"

Criterios de match:
- Mismo monto exacto
- Ventana de tiempo: ±30 minutos entre hora del pago y hora de la operación bancaria
- Método de pago compatible (yape/plin/transferencia)
"""

import logging
from datetime import datetime, timezone, timedelta
from typing import List, Optional, Tuple
from decimal import Decimal
from sqlalchemy.orm import Session
from sqlalchemy import and_, or_

logger = logging.getLogger(__name__)

TZ_PERU = timezone(timedelta(hours=-5))

# Ventana de tiempo para buscar match (minutos antes/después)
VENTANA_MATCH_MINUTOS = 30

# Mapeo tipo_operacion → payment_methods compatibles
METODO_COMPATIBLE = {
    "plin_recibido": ["plin", "digital", "billetera"],
    "plin_enviado": ["plin", "digital", "billetera"],
    "yape_recibido": ["yape", "digital", "billetera"],
    "yape_enviado": ["yape", "digital", "billetera"],
    "transferencia": ["transferencia", "deposito", "digital"],
}


class ConciliacionService:
    """Motor de conciliación automática de pagos digitales."""

    def __init__(self, db: Session):
        self.db = db

    def procesar_emails(self, organization_id: int, emails: List[dict]) -> dict:
        """
        Procesa una lista de emails bancarios.

        Args:
            organization_id: ID de la organización
            emails: Lista de dicts del GmailService

        Returns:
            Resumen: nuevos, duplicados, conciliados, sin_match
        """
        from app.models import NotificacionBancaria
        from app.services.email_parsers import detectar_y_parsear

        stats = {"nuevos": 0, "duplicados": 0, "conciliados": 0, "sin_match": 0, "errores": 0}

        for email_data in emails:
            message_id = email_data.get("message_id")

            # Verificar si ya procesamos este email
            existe = self.db.query(NotificacionBancaria).filter(
                NotificacionBancaria.email_message_id == message_id
            ).first()

            if existe:
                stats["duplicados"] += 1
                continue

            # Parsear
            email_from = email_data.get("from", "")
            body = email_data.get("body", "") or email_data.get("snippet", "")
            subject = email_data.get("subject", "")

            resultado = detectar_y_parsear(email_from, body, subject)

            if not resultado.parsed or resultado.monto <= 0:
                logger.warning(f"Email {message_id} no parseado: {resultado.error}")
                stats["errores"] += 1
                continue

            # Crear notificación
            notif = NotificacionBancaria(
                organization_id=organization_id,
                email_message_id=message_id,
                email_from=email_from,
                email_subject=subject,
                email_date=email_data.get("date"),
                banco=resultado.banco,
                tipo_operacion=resultado.tipo_operacion,
                monto=Decimal(str(resultado.monto)),
                moneda=resultado.moneda,
                fecha_operacion=resultado.fecha_operacion,
                codigo_operacion=resultado.codigo_operacion,
                remitente_nombre=resultado.remitente_nombre,
                cuenta_destino=resultado.cuenta_destino,
                destino_tipo=resultado.destino_tipo,
                estado="pendiente",
                raw_body=body[:2000] if body else None,
            )

            # Vincular con cuenta receptora si hay match
            notif.cuenta_receptora_id = self._buscar_cuenta_receptora(
                organization_id, email_from
            )

            self.db.add(notif)
            self.db.flush()  # Obtener ID
            stats["nuevos"] += 1

            # Intentar auto-conciliar
            payment = self._buscar_match(notif, organization_id)
            if payment:
                notif.payment_id = payment.id
                notif.estado = "conciliado"
                notif.conciliado_por = "auto"
                notif.conciliado_at = datetime.now(TZ_PERU)
                stats["conciliados"] += 1
                logger.info(
                    f"Auto-conciliado: Notif #{notif.id} (S/{notif.monto}) → "
                    f"Payment #{payment.id}"
                )
            else:
                notif.estado = "sin_match"
                stats["sin_match"] += 1

        self.db.commit()
        logger.info(f"Conciliación: {stats}")
        return stats

    def _buscar_match(self, notif, organization_id: int):
        """
        Busca un pago que coincida con la notificación bancaria.

        Criterios:
        1. Mismo monto exacto
        2. Dentro de ventana de tiempo (±30 min)
        3. Método de pago compatible
        4. No conciliado previamente
        5. Status approved
        """
        from app.models import Payment, NotificacionBancaria

        if not notif.fecha_operacion:
            # Sin fecha de operación, buscar por monto en últimas 24h
            fecha_desde = datetime.now(timezone.utc) - timedelta(hours=24)
            fecha_hasta = datetime.now(timezone.utc)
        else:
            # Convertir fecha operación a UTC para comparar
            fecha_op = notif.fecha_operacion
            if fecha_op.tzinfo is None:
                fecha_op = fecha_op.replace(tzinfo=TZ_PERU)
            fecha_op_utc = fecha_op.astimezone(timezone.utc)

            fecha_desde = fecha_op_utc - timedelta(minutes=VENTANA_MATCH_MINUTOS)
            fecha_hasta = fecha_op_utc + timedelta(minutes=VENTANA_MATCH_MINUTOS)

        # IDs de pagos ya conciliados (excluir)
        ya_conciliados = self.db.query(NotificacionBancaria.payment_id).filter(
            NotificacionBancaria.payment_id.isnot(None),
            NotificacionBancaria.id != notif.id,
        ).subquery()

        # Métodos de pago compatibles
        metodos = METODO_COMPATIBLE.get(notif.tipo_operacion, [])

        # Buscar pago
        monto_decimal = Decimal(str(notif.monto))

        query = self.db.query(Payment).filter(
            Payment.status == "approved",
            Payment.amount == monto_decimal,
            Payment.created_at >= fecha_desde,
            Payment.created_at <= fecha_hasta,
            ~Payment.id.in_(ya_conciliados),
        )

        # Filtrar por método de pago si tenemos métodos compatibles
        if metodos:
            query = query.filter(Payment.payment_method.in_(metodos))

        # Ordenar por cercanía temporal
        pagos = query.order_by(Payment.created_at.desc()).all()

        if len(pagos) == 1:
            return pagos[0]
        elif len(pagos) > 1:
            # Múltiples matches — tomar el más cercano en tiempo
            if notif.fecha_operacion:
                fecha_ref = notif.fecha_operacion
                if fecha_ref.tzinfo is None:
                    fecha_ref = fecha_ref.replace(tzinfo=TZ_PERU)
                fecha_ref_utc = fecha_ref.astimezone(timezone.utc)

                mejor = min(pagos, key=lambda p: abs(
                    (p.created_at.replace(tzinfo=timezone.utc) if p.created_at.tzinfo is None else p.created_at)
                    - fecha_ref_utc
                ).total_seconds())
                return mejor
            return pagos[0]

        return None

    def _buscar_cuenta_receptora(self, organization_id: int, email_from: str) -> Optional[int]:
        """Busca la cuenta receptora por el remitente del email."""
        from app.models import CuentaReceptora

        email_lower = email_from.lower()
        cuentas = self.db.query(CuentaReceptora).filter(
            CuentaReceptora.organization_id == organization_id,
            CuentaReceptora.activo == True,
        ).all()

        for c in cuentas:
            if c.email_remitente and c.email_remitente.lower() in email_lower:
                return c.id
        return None

    def conciliar_manual(
        self,
        notificacion_id: int,
        payment_id: int,
        usuario: str,
    ) -> bool:
        """Concilia manualmente una notificación con un pago."""
        from app.models import NotificacionBancaria

        notif = self.db.query(NotificacionBancaria).filter(
            NotificacionBancaria.id == notificacion_id
        ).first()

        if not notif:
            return False

        notif.payment_id = payment_id
        notif.estado = "conciliado"
        notif.conciliado_por = usuario
        notif.conciliado_at = datetime.now(TZ_PERU)
        self.db.commit()
        return True

    def ignorar_notificacion(self, notificacion_id: int, observacion: str = "") -> bool:
        """Marca una notificación como ignorada (no es un pago del colegio)."""
        from app.models import NotificacionBancaria

        notif = self.db.query(NotificacionBancaria).filter(
            NotificacionBancaria.id == notificacion_id
        ).first()

        if not notif:
            return False

        notif.estado = "ignorado"
        notif.observaciones = observacion
        self.db.commit()
        return True

    def obtener_resumen(self, organization_id: int) -> dict:
        """Resumen de conciliación para el dashboard."""
        from app.models import NotificacionBancaria, Payment

        notifs = self.db.query(NotificacionBancaria).filter(
            NotificacionBancaria.organization_id == organization_id,
        )

        total = notifs.count()
        conciliados = notifs.filter(NotificacionBancaria.estado == "conciliado").count()
        pendientes = notifs.filter(NotificacionBancaria.estado == "pendiente").count()
        sin_match = notifs.filter(NotificacionBancaria.estado == "sin_match").count()
        ignorados = notifs.filter(NotificacionBancaria.estado == "ignorado").count()

        # Pagos digitales sin verificar (no tienen notificación conciliada)
        pagos_digitales = self.db.query(Payment).filter(
            Payment.status == "approved",
            Payment.payment_method.in_(["yape", "plin", "transferencia", "digital"]),
        ).count()

        pagos_verificados = self.db.query(NotificacionBancaria).filter(
            NotificacionBancaria.organization_id == organization_id,
            NotificacionBancaria.estado == "conciliado",
            NotificacionBancaria.payment_id.isnot(None),
        ).count()

        return {
            "notificaciones_total": total,
            "conciliados": conciliados,
            "pendientes": pendientes,
            "sin_match": sin_match,
            "ignorados": ignorados,
            "pagos_digitales_total": pagos_digitales,
            "pagos_verificados": pagos_verificados,
            "pagos_sin_verificar": pagos_digitales - pagos_verificados,
            "tasa_verificacion": round(pagos_verificados / pagos_digitales * 100, 1) if pagos_digitales > 0 else 0,
        }