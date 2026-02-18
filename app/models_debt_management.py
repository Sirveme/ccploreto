"""
Módulo: Gestión de Deuda — Modelos SQLAlchemy
app/models/debt_management.py

Diseñado con criterios de:
- ISO 9001:2015 (Gestión de calidad — trazabilidad, registros, evidencia)
- ISO 27001 (Seguridad de la información — integridad, no repudio)
- ISO 15489 (Gestión de documentos — conservación, autenticidad)
- Principios de Administración Tributaria (SUNAT): 
  determinación, exigibilidad, notificación, prescripción

Principios aplicados:
1. IDENTIFICABILIDAD — Cada deuda es única e inequívoca
2. EXIGIBILIDAD — Solo es exigible si fue notificada
3. TRAZABILIDAD — Toda acción queda registrada con autor, fecha, sustento
4. NO REPUDIO — Doble firma en actos administrativos, documentos en GCS
5. INMUTABILIDAD — Los registros originales no se modifican, se crean acciones
6. TEMPORALIDAD — Fechas de origen, vencimiento, notificación, prescripción
"""

from sqlalchemy import (
    Column, Integer, String, Float, Boolean, Text, DateTime, Date,
    ForeignKey, UniqueConstraint, Index, CheckConstraint, Enum as SAEnum
)
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func
from app.database import Base
import enum


# ═══════════════════════════════════════════════════════════
# ENUMS
# ═══════════════════════════════════════════════════════════

class DebtStatus(str, enum.Enum):
    """Estado de pago de la deuda."""
    PENDING = "pending"         # No pagada
    PARTIAL = "partial"         # Pago parcial
    PAID = "paid"               # Pagada totalmente

class EstadoGestion(str, enum.Enum):
    """Estado administrativo/de gestión de la deuda."""
    VIGENTE = "vigente"                 # Deuda activa, cobrable
    EN_COBRANZA = "en_cobranza"         # En gestión activa de cobro
    FRACCIONADA = "fraccionada"         # Incluida en plan de fraccionamiento
    CONDONADA = "condonada"             # Perdonada por acuerdo (total o parcial)
    EXONERADA = "exonerada"             # Liberada por norma o resolución
    COMPENSADA = "compensada"           # Compensada contra crédito a favor
    PRESCRITA = "prescrita"             # Prescrita por plazo legal
    INCOBRABLE = "incobrable"           # Declarada incobrable
    EN_RECLAMO = "en_reclamo"           # Colegiado la impugna
    SUSPENDIDA = "suspendida"           # Suspendida temporalmente

class EstadoNotificacion(str, enum.Enum):
    """Estado de notificación de la deuda."""
    NO_NOTIFICADA = "no_notificada"     # Aún no se ha notificado
    EN_PROCESO = "en_proceso"           # Notificación enviada, sin acuse
    NOTIFICADA = "notificada"           # Notificación con acuse de recibo
    NOTIF_TACITA = "notif_tacita"       # Notificación tácita (publicación, etc.)
    DEVUELTA = "devuelta"               # Notificación devuelta / no entregada

class MedioNotificacion(str, enum.Enum):
    """Medio por el cual se notificó."""
    PERSONAL = "personal"               # Entrega en mano con firma
    CORREO_ELECTRONICO = "email"        # Email con acuse de lectura
    BUZON_ELECTRONICO = "buzon"         # Buzón electrónico del sistema
    PUBLICACION = "publicacion"         # Publicación en web/periódico mural
    CARTA_CERTIFICADA = "carta"         # Carta certificada con cargo
    WHATSAPP = "whatsapp"               # WhatsApp con confirmación de lectura
    SMS = "sms"                         # Mensaje de texto
    ASAMBLEA = "asamblea"               # Lectura en asamblea (acta como sustento)

class TipoAccion(str, enum.Enum):
    """Tipos de acción administrativa sobre la deuda."""
    CONDONACION = "condonacion"
    EXONERACION = "exoneracion"
    COMPENSACION = "compensacion"
    FRACCIONAMIENTO = "fraccionamiento"
    PERDIDA_FRACC = "perdida_fraccionamiento"
    PRESCRIPCION = "prescripcion"
    DECLARAR_INCOBRABLE = "declarar_incobrable"
    AJUSTE_MONTO = "ajuste_monto"
    COMPROMISO_PAGO = "compromiso_pago"
    SUSPENSION = "suspension"
    REACTIVACION = "reactivacion"
    NOTA = "nota"                       # Observación sin efecto contable
    RECTIFICACION = "rectificacion"     # Corrección de error material
    RECLAMO = "reclamo"                 # Colegiado impugna la deuda

class OrigenDeuda(str, enum.Enum):
    """Cómo se generó el registro de deuda."""
    GENERACION_AUTO = "generacion_auto"   # Script de generación mensual
    MIGRACION_XLSX = "migracion_xlsx"     # Importación del Excel histórico
    CAJA = "caja"                         # Creada desde caja/admin
    PORTAL = "portal"                     # Generada desde portal colegiado
    ACUERDO_ASAMBLEA = "acuerdo_asamblea" # Por acuerdo de asamblea
    RESOLUCION = "resolucion"             # Por resolución del colegio

class EstadoFraccionamiento(str, enum.Enum):
    ACTIVO = "activo"
    COMPLETADO = "completado"
    PERDIDO = "perdido"           # Pérdida por incumplimiento
    REFINANCIADO = "refinanciado" # Reemplazado por nuevo plan


# ═══════════════════════════════════════════════════════════
# TABLA: BASES LEGALES (Sustento normativo)
# ═══════════════════════════════════════════════════════════

class BaseLegal(Base):
    """
    Catálogo de sustentos normativos para la generación de deuda.
    Cada deuda debe poder rastrearse a su origen legal.
    
    ISO 9001:2015 §7.5 — Información documentada
    ISO 15489 — Autenticidad y fiabilidad de registros
    """
    __tablename__ = "bases_legales"
    __table_args__ = (
        UniqueConstraint('organization_id', 'codigo', name='uq_org_codigo_base_legal'),
    )

    id = Column(Integer, primary_key=True, autoincrement=True)
    organization_id = Column(Integer, ForeignKey("organizations.id"), nullable=False)

    codigo = Column(String(30), nullable=False)       # "EST-ART52", "AA-2024-003"
    tipo = Column(String(30), nullable=False)
    # estatuto, reglamento, acuerdo_asamblea, resolucion_directiva,
    # resolucion_decanato, norma_legal, otro

    titulo = Column(String(200), nullable=False)
    descripcion = Column(Text)
    
    # Referencia al documento
    numero_documento = Column(String(50))              # "Acta N° 003-2024-AG"
    fecha_documento = Column(Date)                     # Fecha del documento
    fecha_vigencia = Column(Date)                      # Desde cuándo aplica
    fecha_fin_vigencia = Column(Date, nullable=True)   # Null = vigente indefinidamente

    # Archivo sustentatorio (GCS)
    documento_url = Column(String(500), nullable=True) # gs://bucket/bases_legales/...
    documento_hash = Column(String(64), nullable=True) # SHA-256 para integridad

    activo = Column(Boolean, default=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    created_by = Column(Integer, ForeignKey("users.id"), nullable=True)

    organization = relationship("Organization")


# ═══════════════════════════════════════════════════════════
# TABLA: DEBTS (Mejorada — una fila por concepto por periodo)
# ═══════════════════════════════════════════════════════════

class Debt(Base):
    """
    Registro individual de deuda. UNA FILA POR MES POR CONCEPTO.
    
    Principios:
    - IDENTIFICABILIDAD: concepto + periodo + colegiado = único
    - EXIGIBILIDAD: solo exigible si estado_notificacion != 'no_notificada'
    - INMUTABILIDAD: amount original no cambia; ajustes van a debt_actions
    - TEMPORALIDAD: created_at (generación), due_date (vencimiento),
                    fecha_notificacion (exigibilidad), fecha_prescripcion
    """
    __tablename__ = "debts"
    __table_args__ = (
        # Una sola deuda por concepto+periodo+colegiado
        UniqueConstraint(
            'organization_id', 'colegiado_id', 'concepto_cobro_id', 'periodo',
            name='uq_deuda_concepto_periodo_colegiado'
        ),
        Index('ix_debts_colegiado_status', 'colegiado_id', 'status'),
        Index('ix_debts_periodo', 'periodo'),
        Index('ix_debts_estado_gestion', 'estado_gestion'),
    )

    id = Column(Integer, primary_key=True, autoincrement=True)
    organization_id = Column(Integer, ForeignKey("organizations.id"), nullable=False)
    
    # === SUJETO (Quién debe) ===
    member_id = Column(Integer, ForeignKey("members.id"), nullable=True)
    colegiado_id = Column(Integer, ForeignKey("colegiados.id"), nullable=True)

    # === IDENTIFICACIÓN DEL CONCEPTO ===
    concepto_cobro_id = Column(Integer, ForeignKey("conceptos_cobro.id"), nullable=True)
    # nullable para deuda histórica migrada que no mapea exactamente
    
    concept = Column(String(200), nullable=False)      # Descripción legible: "Cuota Ordinaria"
    periodo = Column(String(10), nullable=True)         # '2024-01', '2024-02', '2024' (anual)
    period_label = Column(String(50), nullable=True)    # "Enero 2024" (para display)
    debt_type = Column(String(30), default="cuota_ordinaria")
    # cuota_ordinaria, cuota_extraordinaria, multa, evento, derecho, otro

    # === MONTOS (Inmutables una vez generados) ===
    amount = Column(Float, nullable=False)              # Monto original determinado
    balance = Column(Float, nullable=False)             # Saldo pendiente (se reduce con pagos)

    # === ESTADOS ===
    status = Column(String(20), default="pending")      # pending, partial, paid
    estado_gestion = Column(
        String(30), default="vigente"
    )  # vigente, en_cobranza, fraccionada, condonada, etc.

    # === BASE LEGAL (Qué origina esta deuda) ===
    base_legal_id = Column(Integer, ForeignKey("bases_legales.id"), nullable=True)
    base_legal_referencia = Column(String(100), nullable=True)
    # Texto libre si no hay registro en bases_legales aún
    # Ej: "Estatuto Art. 52", "Acuerdo Asamblea 12/04/2025"

    # === TEMPORALIDAD ===
    fecha_generacion = Column(Date, nullable=True)      # Cuándo se generó/determinó la deuda
    due_date = Column(DateTime(timezone=True), nullable=True)  # Fecha de vencimiento
    fecha_prescripcion = Column(Date, nullable=True)    # Fecha en que prescribiría
    # Para colegios profesionales, revisar estatuto; típicamente 5 años

    # === NOTIFICACIÓN (Exigibilidad) ===
    estado_notificacion = Column(
        String(20), default="no_notificada"
    )  # no_notificada, en_proceso, notificada, notif_tacita, devuelta
    fecha_notificacion = Column(DateTime(timezone=True), nullable=True)
    medio_notificacion = Column(String(20), nullable=True)
    # personal, email, buzon, publicacion, carta, whatsapp, sms, asamblea
    acuse_recibo = Column(Boolean, default=False)       # ¿Se tiene confirmación de recepción?
    notificacion_documento_url = Column(String(500), nullable=True)  # Cargo/acuse en GCS

    # === FRACCIONAMIENTO ===
    fraccionamiento_id = Column(Integer, ForeignKey("fraccionamientos.id"), nullable=True)

    # === ORIGEN Y TRAZABILIDAD ===
    origen = Column(String(30), default="generacion_auto")
    # generacion_auto, migracion_xlsx, caja, portal, acuerdo_asamblea, resolucion
    
    lote_migracion = Column(String(50), nullable=True)  # ID del batch de importación
    concepto_original = Column(String(200), nullable=True)
    # Texto original del Excel, preservado para auditoría
    
    notes = Column(Text, nullable=True)                 # Notas internas
    attachment_url = Column(String(500), nullable=True)

    # === AUDITORÍA ===
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())
    created_by = Column(Integer, ForeignKey("users.id"), nullable=True)
    updated_by = Column(Integer, ForeignKey("users.id"), nullable=True)

    # === RELACIONES ===
    member = relationship("Member", foreign_keys=[member_id])
    colegiado = relationship("Colegiado", foreign_keys=[colegiado_id])
    organization = relationship("Organization")
    concepto_cobro = relationship("ConceptoCobro", foreign_keys=[concepto_cobro_id])
    base_legal = relationship("BaseLegal", foreign_keys=[base_legal_id])
    fraccionamiento = relationship("Fraccionamiento", foreign_keys=[fraccionamiento_id],
                                   back_populates="deudas")
    acciones = relationship("DebtAction", back_populates="debt",
                           order_by="DebtAction.created_at")
    notificaciones = relationship("DebtNotification", back_populates="debt",
                                  order_by="DebtNotification.fecha_envio")

    @property
    def es_exigible(self):
        """Una deuda es exigible solo si fue notificada al sujeto."""
        return self.estado_notificacion in ('notificada', 'notif_tacita')

    @property
    def esta_vencida(self):
        """¿Pasó la fecha de vencimiento?"""
        from datetime import datetime, timezone
        if not self.due_date:
            return False
        return datetime.now(timezone.utc) > self.due_date

    @property
    def dias_mora(self):
        """Días transcurridos desde el vencimiento."""
        from datetime import datetime, timezone
        if not self.due_date or not self.esta_vencida:
            return 0
        return (datetime.now(timezone.utc) - self.due_date).days


# ═══════════════════════════════════════════════════════════
# TABLA: NOTIFICACIONES DE DEUDA
# ═══════════════════════════════════════════════════════════

class DebtNotification(Base):
    """
    Registro de cada intento de notificación de deuda.
    
    ISO 9001:2015 §7.5 — Información documentada
    Principio tributario: La deuda no es exigible sin notificación válida.
    
    La notificación puede ser:
    - Individual (a un colegiado específico)
    - Masiva (publicación que notifica a múltiples colegiados)
    
    Se registra CADA intento, incluyendo fallidos (devuelta, sin acuse).
    Solo se actualiza estado_notificacion en Debt cuando hay acuse válido.
    """
    __tablename__ = "debt_notifications"
    __table_args__ = (
        Index('ix_debt_notif_debt', 'debt_id'),
        Index('ix_debt_notif_colegiado', 'colegiado_id'),
    )

    id = Column(Integer, primary_key=True, autoincrement=True)
    organization_id = Column(Integer, ForeignKey("organizations.id"), nullable=False)

    # Puede notificar una deuda individual o un lote
    debt_id = Column(Integer, ForeignKey("debts.id"), nullable=True)
    colegiado_id = Column(Integer, ForeignKey("colegiados.id"), nullable=False)
    
    # Si es notificación masiva, referencia al lote
    lote_notificacion = Column(String(50), nullable=True)  # "NOTIF-2025-001"

    # === CONTENIDO ===
    tipo = Column(String(30), nullable=False)
    # estado_cuenta, requerimiento_pago, pre_coactiva, recordatorio,
    # aviso_inhabilidad, publicacion_morosos
    
    asunto = Column(String(200))                         # "Estado de cuenta Enero 2025"
    contenido_resumen = Column(Text, nullable=True)      # Resumen del contenido enviado
    monto_notificado = Column(Float, nullable=True)      # Monto total en la notificación

    # === SUSTENTO LEGAL ===
    base_legal_id = Column(Integer, ForeignKey("bases_legales.id"), nullable=True)
    base_legal_referencia = Column(String(100), nullable=True)
    # "Estatuto Art. 52", "Reglamento de Cobranza Art. 15"

    # === ENVÍO ===
    medio = Column(String(20), nullable=False)
    # personal, email, buzon, publicacion, carta, whatsapp, sms, asamblea
    
    destino = Column(String(200), nullable=True)         # Email, teléfono, dirección
    fecha_envio = Column(DateTime(timezone=True), nullable=False)
    
    # === ACUSE DE RECIBO ===
    acuse_recibo = Column(Boolean, default=False)
    fecha_acuse = Column(DateTime(timezone=True), nullable=True)
    medio_acuse = Column(String(50), nullable=True)
    # firma_cargo, confirmacion_lectura, log_sistema, acta_asamblea, 
    # sello_recepcion, captura_pantalla
    
    acuse_documento_url = Column(String(500), nullable=True)  # GCS: cargo firmado, screenshot
    acuse_documento_hash = Column(String(64), nullable=True)  # SHA-256

    # === RESULTADO ===
    estado = Column(String(20), default="enviada")
    # enviada, recibida, leida, devuelta, fallida, publicada
    
    observacion = Column(Text, nullable=True)
    # "Dirección incorrecta", "Email rebotó", "Buzón lleno", etc.

    # === NOTIFICACIÓN TÁCITA ===
    es_notificacion_tacita = Column(Boolean, default=False)
    # True cuando se notifica por publicación (web, periódico mural)
    # La notificación tácita aplica cuando no se puede notificar personalmente
    
    publicacion_url = Column(String(500), nullable=True)  # URL donde se publicó
    publicacion_medio = Column(String(100), nullable=True)
    # "Página web institucional", "Periódico mural sede", "Panel vitrina"
    publicacion_fecha_inicio = Column(Date, nullable=True)
    publicacion_fecha_fin = Column(Date, nullable=True)
    # La notificación tácita surte efecto al día siguiente de publicada

    # === AUDITORÍA ===
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    created_by = Column(Integer, ForeignKey("users.id"), nullable=True)
    
    # Quien autoriza la notificación (para requerimientos formales)
    autorizado_por = Column(Integer, ForeignKey("users.id"), nullable=True)

    # === RELACIONES ===
    debt = relationship("Debt", back_populates="notificaciones")
    colegiado = relationship("Colegiado")
    organization = relationship("Organization")
    base_legal = relationship("BaseLegal")


# ═══════════════════════════════════════════════════════════
# TABLA: ACCIONES SOBRE DEUDA (Auditoría ISO)
# ═══════════════════════════════════════════════════════════

class DebtAction(Base):
    """
    Registro inmutable de toda acción administrativa sobre una deuda.
    
    ISO 9001:2015 §7.5.3 — Control de información documentada
    Principios:
    - INMUTABILIDAD: Una vez creado, el registro NO se modifica ni elimina
    - DOBLE FIRMA: Actos con efecto contable requieren created_by + approved_by
    - SUSTENTO DOCUMENTAL: Toda acción debe tener documento de respaldo (GCS)
    - TRAZABILIDAD: Cadena completa de acciones sobre cada deuda
    """
    __tablename__ = "debt_actions"
    __table_args__ = (
        Index('ix_debt_actions_debt', 'debt_id'),
        Index('ix_debt_actions_tipo', 'tipo'),
    )

    id = Column(Integer, primary_key=True, autoincrement=True)
    organization_id = Column(Integer, ForeignKey("organizations.id"), nullable=False)

    debt_id = Column(Integer, ForeignKey("debts.id"), nullable=False)
    fraccionamiento_id = Column(Integer, ForeignKey("fraccionamientos.id"), nullable=True)

    # === TIPO DE ACCIÓN ===
    tipo = Column(String(30), nullable=False)
    # condonacion, exoneracion, compensacion, fraccionamiento,
    # perdida_fraccionamiento, prescripcion, declarar_incobrable,
    # ajuste_monto, compromiso_pago, suspension, reactivacion,
    # nota, rectificacion, reclamo

    # === DETALLE ===
    descripcion = Column(Text, nullable=False)
    # "Condonación del 50% por Acuerdo de Asamblea AA-2025-003"
    # "Ajuste de monto: error material en determinación original"
    
    monto_afectado = Column(Float, nullable=True)       # Monto que afecta esta acción
    balance_anterior = Column(Float, nullable=True)     # Balance antes de la acción
    balance_nuevo = Column(Float, nullable=True)        # Balance después de la acción
    
    estado_gestion_anterior = Column(String(30), nullable=True)
    estado_gestion_nuevo = Column(String(30), nullable=True)

    # === SUSTENTO ===
    base_legal_id = Column(Integer, ForeignKey("bases_legales.id"), nullable=True)
    base_legal_referencia = Column(String(100), nullable=True)
    
    # Documento sustentatorio en GCS (resolución, acta, solicitud, etc.)
    documento_url = Column(String(500), nullable=True)
    documento_hash = Column(String(64), nullable=True)  # SHA-256 integridad
    documento_nombre = Column(String(200), nullable=True)

    # === DOBLE FIRMA (actos con efecto contable) ===
    created_by = Column(Integer, ForeignKey("users.id"), nullable=False)
    approved_by = Column(Integer, ForeignKey("users.id"), nullable=True)
    # approved_by es OBLIGATORIO para: condonacion, exoneracion, compensacion,
    # prescripcion, declarar_incobrable, ajuste_monto, rectificacion
    
    fecha_aprobacion = Column(DateTime(timezone=True), nullable=True)
    
    # Para compromisos de pago
    compromiso_fecha_limite = Column(Date, nullable=True)
    compromiso_monto = Column(Float, nullable=True)

    # === AUDITORÍA (inmutable) ===
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    ip_address = Column(String(45), nullable=True)      # IPv4 o IPv6
    user_agent = Column(String(300), nullable=True)      # Navegador/dispositivo

    # === RELACIONES ===
    debt = relationship("Debt", back_populates="acciones")
    organization = relationship("Organization")
    
    # Acciones que requieren doble firma
    REQUIERE_APROBACION = {
        'condonacion', 'exoneracion', 'compensacion',
        'prescripcion', 'declarar_incobrable',
        'ajuste_monto', 'rectificacion'
    }

    @property
    def requiere_aprobacion(self):
        return self.tipo in self.REQUIERE_APROBACION

    @property
    def esta_aprobada(self):
        if not self.requiere_aprobacion:
            return True
        return self.approved_by is not None


# ═══════════════════════════════════════════════════════════
# TABLA: FRACCIONAMIENTOS
# ═══════════════════════════════════════════════════════════

class Fraccionamiento(Base):
    """
    Plan de fraccionamiento de deuda.
    
    Reglas del CCPL:
    - Deuda mínima: S/ 500
    - Cuota inicial: 20% de la deuda total
    - Cuota mínima mensual: S/ 100
    - Máximo 12 cuotas
    - Constancia se renueva mes a mes al pagar cada cuota
    - Pérdida: 2 cuotas consecutivas impagas
    
    ISO 9001:2015 §8.2.1 — Comunicación con el cliente
    """
    __tablename__ = "fraccionamientos"
    __table_args__ = (
        Index('ix_fracc_colegiado', 'colegiado_id'),
        Index('ix_fracc_estado', 'estado'),
    )

    id = Column(Integer, primary_key=True, autoincrement=True)
    organization_id = Column(Integer, ForeignKey("organizations.id"), nullable=False)
    colegiado_id = Column(Integer, ForeignKey("colegiados.id"), nullable=False)

    # === SOLICITUD ===
    numero_solicitud = Column(String(30))   # "FRACC-2025-0001"
    fecha_solicitud = Column(Date, nullable=False)

    # === MONTOS ===
    deuda_total_original = Column(Float, nullable=False)  # Total de deuda al momento
    cuota_inicial = Column(Float, nullable=False)          # 20% mínimo
    cuota_inicial_pagada = Column(Boolean, default=False)
    saldo_a_fraccionar = Column(Float, nullable=False)     # deuda_total - cuota_inicial
    
    num_cuotas = Column(Integer, nullable=False)           # Máx 12
    monto_cuota = Column(Float, nullable=False)            # Mín S/100
    
    # === SEGUIMIENTO ===
    cuotas_pagadas = Column(Integer, default=0)
    cuotas_atrasadas = Column(Integer, default=0)
    saldo_pendiente = Column(Float, nullable=False)        # Se actualiza con cada pago
    
    fecha_inicio = Column(Date, nullable=False)
    fecha_fin_estimada = Column(Date, nullable=False)
    proxima_cuota_fecha = Column(Date, nullable=True)
    proxima_cuota_numero = Column(Integer, default=1)

    # === ESTADO ===
    estado = Column(String(20), default="activo")
    # activo, completado, perdido, refinanciado
    
    fecha_perdida = Column(Date, nullable=True)
    motivo_perdida = Column(Text, nullable=True)
    # "2 cuotas consecutivas impagas (Oct y Nov 2025)"

    # === SUSTENTO ===
    base_legal_id = Column(Integer, ForeignKey("bases_legales.id"), nullable=True)
    base_legal_referencia = Column(String(100), nullable=True)
    # "Reglamento de Fraccionamiento, aprobado en AA-2024-005"
    
    documento_solicitud_url = Column(String(500), nullable=True)  # GCS
    documento_resolucion_url = Column(String(500), nullable=True) # GCS

    # === DOBLE FIRMA ===
    created_by = Column(Integer, ForeignKey("users.id"), nullable=False)
    approved_by = Column(Integer, ForeignKey("users.id"), nullable=True)
    fecha_aprobacion = Column(DateTime(timezone=True), nullable=True)

    # === AUDITORÍA ===
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())

    # === RELACIONES ===
    colegiado = relationship("Colegiado")
    organization = relationship("Organization")
    deudas = relationship("Debt", back_populates="fraccionamiento")
    cuotas = relationship("FraccionamientoCuota", back_populates="fraccionamiento",
                         order_by="FraccionamientoCuota.numero_cuota")


class FraccionamientoCuota(Base):
    """
    Detalle de cada cuota de un plan de fraccionamiento.
    Permite tracking individual de pagos y genera habilidad mes a mes.
    """
    __tablename__ = "fraccionamiento_cuotas"

    id = Column(Integer, primary_key=True, autoincrement=True)
    fraccionamiento_id = Column(Integer, ForeignKey("fraccionamientos.id"), nullable=False)
    
    numero_cuota = Column(Integer, nullable=False)       # 0=inicial, 1..12
    monto = Column(Float, nullable=False)
    fecha_vencimiento = Column(Date, nullable=False)
    
    # Estado de pago
    pagada = Column(Boolean, default=False)
    fecha_pago = Column(Date, nullable=True)
    payment_id = Column(Integer, ForeignKey("payments.id"), nullable=True)
    
    # Si paga esta cuota, ¿le da habilidad hasta?
    habilidad_hasta = Column(Date, nullable=True)
    
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    
    fraccionamiento = relationship("Fraccionamiento", back_populates="cuotas")


# ═══════════════════════════════════════════════════════════
# RESUMEN DE TABLAS Y RELACIONES
# ═══════════════════════════════════════════════════════════
#
# bases_legales          ← Catálogo de normas (Estatuto, Acuerdos, Resoluciones)
#   ↓
# debts                  ← Una fila por concepto × periodo × colegiado
#   ├── debt_notifications  ← Cada intento de notificación (trazabilidad completa)
#   ├── debt_actions        ← Acciones administrativas (inmutable, doble firma)
#   └── fraccionamientos    ← Plan de pagos fraccionados
#        └── fraccionamiento_cuotas  ← Detalle de cada cuota del plan
#
# Flujo de vida de una deuda:
# 1. GENERACIÓN    → Se crea el registro (Debt) con base legal
# 2. NOTIFICACIÓN  → Se notifica al colegiado (DebtNotification)
#                     Solo con notificación válida es EXIGIBLE
# 3. GESTIÓN       → Acciones: cobranza, compromiso, reclamo (DebtAction)
# 4. RESOLUCIÓN    → Pago / Fraccionamiento / Condonación / Prescripción
# 5. ARCHIVO       → El registro permanece para auditoría futura
#
# Reglas de negocio:
# - Deuda no notificada → NO exigible, NO genera inhabilidad
# - Condonación/Exoneración → Requiere doble firma + documento sustentatorio
# - Fraccionamiento → Requiere aprobación + cuota inicial 20%
# - Pérdida de fraccionamiento → 2 cuotas consecutivas impagas
# - Prescripción → Según estatuto (revisar plazo con el Colegio)