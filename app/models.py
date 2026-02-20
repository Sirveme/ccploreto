from sqlalchemy import Column, Integer, String, ForeignKey, Boolean, DateTime, Text, JSON, Float, Enum, Date, Numeric, Table, Index, UniqueConstraint
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func
from .database import Base
import enum
from sqlalchemy.dialects.postgresql import JSONB
from datetime import datetime

# --- ENUMS (Para restringir valores y evitar errores) ---
class MemberRole(str, enum.Enum):
    ADMIN = "admin"
    SECURITY = "security"
    USER = "user"

class TicketStatus(str, enum.Enum):
    OPEN = "open"
    IN_PROGRESS = "in_progress"
    RESOLVED = "resolved"

class AccessType(str, enum.Enum):
    IN = "in"
    OUT = "out"

# --- CORE ---
class Organization(Base):
    __tablename__ = "organizations"
    id = Column(Integer, primary_key=True, index=True)
    name = Column(String, nullable=False)
    slug = Column(String, unique=True)
    type = Column(String) # condominio, colegio, club, municipio
    
    # CONFIGURACIÓN DEL PLAN (Ventas)
    # Ej: { "plan": "pro", "modules": {"panic": true, "access": true, "voting": false} }
    config = Column(JSON, default={}) 
    
    theme_color = Column(String, default="#6366f1")
    logo_url = Column(String)
    timezone = Column(String, default="America/Lima") # Para reportes
    
    members = relationship("Member", back_populates="organization")
    resources = relationship("Resource", back_populates="organization")

class Member(Base):
    __tablename__ = "members"
    id = Column(Integer, primary_key=True, index=True)
    organization_id = Column(Integer, ForeignKey("organizations.id"))
    user_id = Column(Integer, ForeignKey("users.id"))
    
    # Datos específicos de la Membresía (No de la persona)
    unit_info = Column(String) # "Torre A - 501"
    role = Column(String, default="user") # admin, staff, user
    position = Column(String) # "Propietario", "Inquilino"
    
    permissions = Column(JSON, default={})
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    # Relaciones
    user = relationship("User", back_populates="memberships")
    organization = relationship("Organization", back_populates="members")
    
    devices = relationship("Device", back_populates="member")
    tickets = relationship("Ticket", back_populates="member")
    bookings = relationship("Booking", back_populates="member")
    # pets y debts también apuntan aquí

class Device(Base):
    __tablename__ = "devices"
    id = Column(Integer, primary_key=True, index=True)
    member_id = Column(Integer, ForeignKey("members.id"))
    
    push_endpoint = Column(Text, unique=True)
    push_p256dh = Column(String)
    push_auth = Column(String)
    
    # Huella Digital
    user_agent = Column(String)
    platform = Column(String)
    browser = Column(String)
    is_pwa = Column(Boolean, default=False)
    timezone = Column(String)
    
    is_active = Column(Boolean, default=True)
    last_seen = Column(DateTime(timezone=True), server_default=func.now())
    
    member = relationship("Member", back_populates="devices")

    permission_status = Column(String, default="unknown") 
    app_version = Column(String) # Para saber si tienen la app vieja

# --- MÓDULO SEGURIDAD (Pánico & Accesos) ---
class PanicLog(Base):
    __tablename__ = "panic_logs"
    id = Column(Integer, primary_key=True)
    member_id = Column(Integer, ForeignKey("members.id"))
    organization_id = Column(Integer, ForeignKey("organizations.id"))
    
    lat = Column(Float, nullable=True)
    lon = Column(Float, nullable=True)
    address_ref = Column(String, nullable=True) # "Cerca a portería"
    
    created_at = Column(DateTime(timezone=True), server_default=func.now())

class AccessLog(Base):
    __tablename__ = "access_logs"
    id = Column(Integer, primary_key=True)
    organization_id = Column(Integer, ForeignKey("organizations.id"))
    member_id = Column(Integer, ForeignKey("members.id"), nullable=True) # Si es vecino
    
    visitor_name = Column(String, nullable=True) # Si es visita externa
    visitor_dni = Column(String, nullable=True)
    target_unit = Column(String) # "Va al 501"
    
    direction = Column(String) # IN / OUT
    method = Column(String) # QR, MANUAL, VEHICULAR
    
    created_at = Column(DateTime(timezone=True), server_default=func.now())

class VisitorPass(Base): # Invitaciones QR
    __tablename__ = "visitor_passes"
    id = Column(Integer, primary_key=True)
    member_id = Column(Integer, ForeignKey("members.id"))
    
    guest_name = Column(String)
    qr_token = Column(String, unique=True)
    valid_from = Column(DateTime(timezone=True))
    valid_until = Column(DateTime(timezone=True))
    is_used = Column(Boolean, default=False)

# --- MÓDULO LOGÍSTICA (Paquetería) ---
class Parcel(Base):
    __tablename__ = "parcels"
    id = Column(Integer, primary_key=True)
    organization_id = Column(Integer, ForeignKey("organizations.id"))
    target_unit = Column(String) # Dpto 301
    
    courier = Column(String) # Amazon, Rappi
    photo_url = Column(String, nullable=True)
    
    status = Column(String, default="received") # received, delivered
    received_at = Column(DateTime(timezone=True), server_default=func.now())
    picked_up_at = Column(DateTime(timezone=True), nullable=True)

# --- MÓDULO HELPDESK (Tickets/Incidencias) ---
class Ticket(Base):
    __tablename__ = "tickets"
    id = Column(Integer, primary_key=True)
    member_id = Column(Integer, ForeignKey("members.id"))
    organization_id = Column(Integer, ForeignKey("organizations.id"))
    
    title = Column(String)
    description = Column(Text)
    category = Column(String) # Mantenimiento, Seguridad, Limpieza
    status = Column(String, default="open") # open, in_progress, resolved
    priority = Column(String, default="medium")
    
    image_url = Column(String, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    
    member = relationship("Member", back_populates="tickets")

# --- MÓDULO RESERVAS (Clubes/Condominios) ---
class Resource(Base):
    __tablename__ = "resources"
    id = Column(Integer, primary_key=True)
    organization_id = Column(Integer, ForeignKey("organizations.id"))
    
    name = Column(String) # Zona Parrilla 1, Cancha Tenis
    rules = Column(JSON) # { "max_hours": 2, "cost": 20.00 }
    is_active = Column(Boolean, default=True)
    
    organization = relationship("Organization", back_populates="resources")
    bookings = relationship("Booking", back_populates="resource")

class Booking(Base):
    __tablename__ = "bookings"
    id = Column(Integer, primary_key=True)
    resource_id = Column(Integer, ForeignKey("resources.id"))
    member_id = Column(Integer, ForeignKey("members.id"))
    
    start_time = Column(DateTime(timezone=True))
    end_time = Column(DateTime(timezone=True))
    status = Column(String, default="confirmed") # confirmed, cancelled
    
    member = relationship("Member", back_populates="bookings")
    resource = relationship("Resource", back_populates="bookings")

# --- MÓDULO PROFESIONAL (Bolsa de Trabajo) ---
class JobPost(Base):
    __tablename__ = "job_posts"
    id = Column(Integer, primary_key=True)
    organization_id = Column(Integer, ForeignKey("organizations.id"))
    
    title = Column(String)
    company = Column(String)
    description = Column(Text)
    contact_email = Column(String)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    expires_at = Column(DateTime(timezone=True))


# FINANZAS
class FinancialSummary(Base):
    __tablename__ = "financial_summaries"
    id = Column(Integer, primary_key=True)
    organization_id = Column(Integer, ForeignKey("organizations.id"))
    period = Column(String)
    total_income = Column(Float)
    total_expenses = Column(Float)
    current_balance = Column(Float)
    pdf_url = Column(String)
    notes = Column(Text)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

# CHAT
class Conversation(Base):
    __tablename__ = "conversations"
    id = Column(Integer, primary_key=True)
    organization_id = Column(Integer, ForeignKey("organizations.id"))
    type = Column(String) # SUPPORT, SECURITY
    updated_at = Column(DateTime(timezone=True), server_default=func.now())
    
    messages = relationship("Message", back_populates="conversation")
    # participants = relationship... (Complejo, lo manejaremos por query)

class Message(Base):
    __tablename__ = "messages"
    id = Column(Integer, primary_key=True)
    conversation_id = Column(Integer, ForeignKey("conversations.id"))
    sender_id = Column(Integer, ForeignKey("members.id"))
    content = Column(Text)
    message_type = Column(String) # text, image, audio
    is_read = Column(Boolean, default=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    
    conversation = relationship("Conversation", back_populates="messages")

# --- MÓDULO COMUNICACIÓN (Megáfono) ---

class Bulletin(Base):
    __tablename__ = "bulletins"
    id = Column(Integer, primary_key=True, index=True)
    organization_id = Column(Integer, ForeignKey("organizations.id"))
    author_id = Column(Integer, ForeignKey("members.id")) # Quién lo escribió (Admin/Profesor)
    
    title = Column(String, nullable=False)
    content = Column(Text, nullable=False) # Puede ser HTML simple o Texto
    image_url = Column(String, nullable=True) # Foto del comunicado/afiche
    file_url = Column(String, nullable=True) # PDF adjunto (Reglamento)
    
    # Segmentación Universal
    # Ej: {"torre": "A"} o {"grado": "5", "seccion": "B"} o {"all": true}
    target_criteria = Column(JSON, default={}) 
    
    # Configuración de Comportamiento
    priority = Column(String, default="info") # info, warning, alert (rojo)
    interaction_type = Column(String, default="read_only") # read_only, confirm (firma), link
    action_payload = Column(String, nullable=True) # URL del link si interaction_type es 'link'
    
    expires_at = Column(DateTime(timezone=True), nullable=True) # Cuándo desaparece del muro
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    
    # Relaciones
    organization = relationship("Organization")
    events = relationship("BulletinEvent", back_populates="bulletin")

class BulletinEvent(Base):
    __tablename__ = "bulletin_events"
    id = Column(Integer, primary_key=True)
    bulletin_id = Column(Integer, ForeignKey("bulletins.id"))
    member_id = Column(Integer, ForeignKey("members.id"))
    
    status = Column(String) # 'sent', 'read', 'confirmed'
    interacted_at = Column(DateTime(timezone=True), server_default=func.now())
    
    bulletin = relationship("Bulletin", back_populates="events")
    member = relationship("Member")


# --- MÓDULO VIDA SOCIAL ---

class Pet(Base):
    __tablename__ = "pets"
    id = Column(Integer, primary_key=True)
    organization_id = Column(Integer, ForeignKey("organizations.id"))
    owner_id = Column(Integer, ForeignKey("members.id"))
    
    name = Column(String)
    species = Column(String)
    breed = Column(String, nullable=True)
    
    # CAMBIO IMPORTANTE: Usamos 'photos' (JSON) en lugar de 'photo_url'
    # Para guardar varias fotos en el futuro
    photos = Column(JSON, default=[]) 
    
    # Detalles
    habits = Column(Text, nullable=True)
    health_issues = Column(String, nullable=True)
    notes = Column(Text, nullable=True) # <--- AQUÍ ESTABA EL ERROR (Faltaba esto)
    
    # Estado Perdido
    is_lost = Column(Boolean, default=False)
    lost_date = Column(DateTime(timezone=True), nullable=True)
    last_seen_location = Column(String, nullable=True)
    reward_amount = Column(String, nullable=True)
    contact_phone = Column(String, nullable=True)
    
    owner = relationship("Member")


# MÓDULO SOCIAL
class Reaction(Base):
    __tablename__ = "reactions"
    id = Column(Integer, primary_key=True)
    member_id = Column(Integer, ForeignKey("members.id"))
    target_type = Column(String) # 'pet'
    target_id = Column(Integer)
    reaction_type = Column(String) # 'like'
    

class Comment(Base):
    __tablename__ = "comments"
    id = Column(Integer, primary_key=True)
    member_id = Column(Integer, ForeignKey("members.id"))
    target_type = Column(String) # 'pet'
    target_id = Column(Integer)
    content = Column(Text)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    
    member = relationship("Member") # Para saber quién comentó


# NUEVA TABLA: La Persona Real
# --- NIVEL 1: IDENTIDAD GLOBAL (La Persona) ---
class User(Base):
    __tablename__ = "users"
    id = Column(Integer, primary_key=True, index=True)
    
    public_id = Column(String, unique=True, index=True)  # DNI
    access_code = Column(String)  # Hash del Password
    
    name = Column(String)
    email = Column(String, nullable=True)
    phone = Column(String, nullable=True)
    photo_url = Column(String, nullable=True)
    
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    
    # NUEVOS CAMPOS
    debe_cambiar_clave = Column(Boolean, default=True)
    login_count = Column(Integer, default=0)
    ultimo_login = Column(DateTime(timezone=True), nullable=True)
    
    memberships = relationship("Member", back_populates="user")


# --- MÓDULO FINANZAS AVANZADO ---

class Payment(Base):

    __tablename__ = "payments"
    id = Column(Integer, primary_key=True)
    organization_id = Column(Integer, ForeignKey("organizations.id"))
    member_id = Column(Integer, ForeignKey("members.id"), nullable=True)  # Para condominios
    colegiado_id = Column(Integer, ForeignKey("colegiados.id"), nullable=True)  # Para colegios profesionales
    
    # Detalle del Pago
    amount = Column(Float)
    currency = Column(String, default="PEN") # PEN, USD
    payment_method = Column(String) # Yape, Plin, Transferencia, Efectivo
    operation_code = Column(String, nullable=True) # Nro de Operación del banco
    voucher_url = Column(String, nullable=True) # Foto
    
    # Quién paga (puede ser tercero/empresa)
    pagador_tipo = Column(String, default="titular")  # titular, empresa, tercero
    pagador_nombre = Column(String, nullable=True)
    pagador_documento = Column(String, nullable=True)  # RUC o DNI del pagador

    # Estado del Pago
    status = Column(String, default="review") # review (esperando a Julieth), approved, rejected
    rejection_reason = Column(Text, nullable=True)
    
    # Relación con Deuda (Opcional: puede ser pago adelantado sin deuda específica)
    related_debt_id = Column(Integer, ForeignKey("debts.id"), nullable=True)
    notes = Column(Text, nullable=True) # "Pago de Enero y Febrero"
    
    reviewed_by = Column(Integer, ForeignKey("members.id"), nullable=True) # Quién aprobó (Auditoría)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    reviewed_at = Column(DateTime(timezone=True), nullable=True)

    # Relaciones
    member = relationship("Member", foreign_keys=[member_id])
    colegiado = relationship("Colegiado", foreign_keys=[colegiado_id])
    organization = relationship("Organization")


class Partner(Base):
    __tablename__ = "partners"
    id = Column(Integer, primary_key=True)
    organization_id = Column(Integer, ForeignKey("organizations.id"), nullable=True)
    
    name = Column(String)
    category = Column(String)
    description = Column(Text)
    
    logo_url = Column(String)
    cover_url = Column(String)
    
    phone = Column(String)
    whatsapp = Column(String)
    website_url = Column(String)
    
    is_verified = Column(Boolean, default=False)
    is_promoted = Column(Boolean, default=False)


class AuditLog(Base):
    __tablename__ = "audit_logs"
    id = Column(Integer, primary_key=True)
    organization_id = Column(Integer, ForeignKey("organizations.id"))
    user_id = Column(Integer, ForeignKey("users.id"))
    
    action_type = Column(String)
    command_text = Column(Text)
    ai_response = Column(JSON)
    status = Column(String)
    ip_address = Column(String)
    
    created_at = Column(DateTime(timezone=True), server_default=func.now())


# --- MÓDULO COLEGIOS PROFESIONALES ---

class Colegiado(Base):
    __tablename__ = "colegiados"
    id = Column(Integer, primary_key=True, index=True)
    organization_id = Column(Integer, ForeignKey("organizations.id"), nullable=False)
    member_id = Column(Integer, ForeignKey("members.id"), nullable=True)  # Se vincula cuando se registra
    
    # Datos de importación (Excel)
    dni = Column(String(30), index=True)  # Era 15
    codigo_matricula = Column(String(50), index=True)  # Era 20
    apellidos_nombres = Column(String(500))  # Era 255
    sexo = Column(String(1), nullable=True)
    
    # Estado de Habilidad
    condicion = Column(String, default="inhabil")  # habil, inhabil, suspendido, fallecido
    fecha_actualizacion_condicion = Column(DateTime(timezone=True), server_default=func.now())
    motivo_inhabilidad = Column(String, nullable=True)
    
    # Datos adicionales (para cuando actualicen su perfil)
    email = Column(String, nullable=True)
    telefono = Column(String, nullable=True)
    direccion = Column(String, nullable=True)
    foto_url = Column(String, nullable=True)
    fecha_colegiatura = Column(DateTime(timezone=True), nullable=True)
    especialidad = Column(String, nullable=True)
    
    # Control
    tiene_dni_real = Column(Boolean, default=True)  # False si es código ficticio
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    # Nuevos campos
    fecha_nacimiento = Column(Date)
    lugar_nacimiento = Column(String(200))
    estado_civil = Column(String(20))
    tipo_documento = Column(String(20), default='DNI')
    tipo_sangre = Column(String(5), nullable=True)  # A+, A-, B+, B-, AB+, AB-, O+, O-
    
    universidad = Column(String(300))
    fecha_titulo = Column(Date)
    grado_academico = Column(String(50))
    otros_estudios = Column(JSONB, default=[])
    
    situacion_laboral = Column(String(30))
    centro_trabajo = Column(String(300))
    cargo = Column(String(200))
    ruc_empleador = Column(String(20))
    direccion_trabajo = Column(String(500))
    telefono_trabajo = Column(String(50))
    
    nombre_conyuge = Column(String(200))
    cantidad_hijos = Column(Integer, default=0)
    contacto_emergencia_nombre = Column(String(200))
    contacto_emergencia_telefono = Column(String(50))
    contacto_emergencia_parentesco = Column(String(50))
    
    sitio_web = Column(String(300))
    linkedin = Column(String(300))
    facebook = Column(String(300))
    instagram = Column(String(300))
    tiktok = Column(String(300))
    
    datos_actualizados_at = Column(DateTime)
    datos_completos = Column(Boolean, default=False)

    habilidad_vence = Column(DateTime(timezone=True), nullable=True)
    tiene_fraccionamiento = Column(Boolean, default=False)

    # Referencias de domicilio
    referencia_domicilio = Column(String(500), nullable=True)
    referencia_trabajo = Column(String(500), nullable=True)

    # Comité Funcional (estándar Colegios de Contadores)
    comite_funcional = Column(String(100), nullable=True)

    # Página web del colegiado
    sobre_mi = Column(Text, nullable=True)
    experiencia_laboral = Column(JSONB, default=[])
    
    # Relaciones
    organization = relationship("Organization")
    member = relationship("Member", foreign_keys=[member_id])

    certificados = relationship("CertificadoEmitido", back_populates="colegiado")

    @property
    def es_habil(self):
        return self.condicion in ('habil', 'vitalicio')


class CertificadoEmitido(Base):
    """Certificados de Habilitación Digital emitidos"""
    
    __tablename__ = "certificados_emitidos"
    
    id = Column(Integer, primary_key=True)
    
    # Código de verificación único (YYYY-NNNNNNN)
    codigo_verificacion = Column(String(20), unique=True, nullable=False, index=True)
    
    # Colegiado
    colegiado_id = Column(Integer, ForeignKey("colegiados.id"), nullable=False)
    
    # Snapshot de datos al momento de emisión
    nombres = Column(String(200), nullable=False)
    apellidos = Column(String(200), nullable=False)
    matricula = Column(String(20), nullable=False)
    
    # Vigencia
    fecha_emision = Column(DateTime(timezone=True), server_default=func.now())
    fecha_vigencia_hasta = Column(Date, nullable=False)
    en_fraccionamiento = Column(Boolean, default=False)
    
    # Pago que habilitó este certificado
    payment_id = Column(Integer, ForeignKey("payments.id"), nullable=True)
    
    # Estado: vigente, vencido, anulado
    estado = Column(String(20), default="vigente")
    
    # Auditoría
    emitido_por = Column(Integer, ForeignKey("members.id"), nullable=True)
    ip_emision = Column(String(45), nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    
    # Relaciones
    colegiado = relationship("Colegiado", back_populates="certificados")
    payment = relationship("Payment", foreign_keys=[payment_id])
    emitido_por_member = relationship("Member", foreign_keys=[emitido_por])
    
    @property
    def nombre_completo(self) -> str:
        return f"CPC. {self.nombres} {self.apellidos}"
    
    @property
    def esta_vigente(self) -> bool:
        from datetime import date
        return self.estado == "vigente" and self.fecha_vigencia_hasta >= date.today()
    
    @property
    def estado_actual(self) -> str:
        from datetime import date
        if self.estado == "anulado":
            return "ANULADO"
        elif self.fecha_vigencia_hasta < date.today():
            return "VENCIDO"
        return "VIGENTE"



# Al final de app/models.py agregar:

class ConfiguracionFacturacion(Base):
    __tablename__ = "configuracion_facturacion"
    
    id = Column(Integer, primary_key=True)
    organization_id = Column(Integer, ForeignKey("organizations.id"), nullable=False)
    ruc = Column(String(11))
    razon_social = Column(String(255))
    nombre_comercial = Column(String(255))
    direccion = Column(String(500))
    ubigeo = Column(String(6))
    serie_boleta = Column(String(10), default="B001")
    serie_factura = Column(String(10), default="F001")
    ultimo_numero_boleta = Column(Integer, default=0)
    ultimo_numero_factura = Column(Integer, default=0)
    facturalo_url = Column(String(255))
    facturalo_token = Column(String(255))
    facturalo_secret = Column(String(255))
    facturalo_empresa_id = Column(String(50))
    tipo_afectacion_igv = Column(String(2), default="20")  # 20=Exonerado
    porcentaje_igv = Column(Integer, default=0)
    emitir_automatico = Column(Boolean, default=False)
    activo = Column(Boolean, default=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())

    # Relación
    organization = relationship("Organization")


class Comprobante(Base):
    __tablename__ = "comprobantes"
    
    id = Column(Integer, primary_key=True)
    organization_id = Column(Integer, ForeignKey("organizations.id"), nullable=False)
    payment_id = Column(Integer, ForeignKey("payments.id"))
    tipo = Column(String(2))  # 01=Factura, 03=Boleta
    serie = Column(String(10))
    numero = Column(Integer)
    fecha_emision = Column(DateTime(timezone=True), server_default=func.now())
    fecha_vencimiento = Column(DateTime(timezone=True), nullable=True)
    moneda = Column(String(3), default="PEN")
    subtotal = Column(Numeric(12, 2))
    igv = Column(Numeric(12, 2), default=0)
    total = Column(Numeric(12, 2))
    cliente_tipo_doc = Column(String(1))
    cliente_num_doc = Column(String(15))
    cliente_nombre = Column(String(255))
    cliente_direccion = Column(String(500))
    cliente_email = Column(String(255))
    items = Column(JSON)
    status = Column(String(20), default="pending")
    facturalo_id = Column(String(100))
    facturalo_response = Column(JSON)
    sunat_response_code = Column(String(10))
    sunat_response_description = Column(Text)
    sunat_hash = Column(String(100))
    pdf_url = Column(String(500))
    xml_url = Column(String(500))
    cdr_url = Column(String(500))
    observaciones = Column(Text)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())
    comprobante_ref_id = Column(Integer, ForeignKey("comprobantes.id"), nullable=True)

    # Relaciones
    payment = relationship("Payment", backref="comprobante")
    organization = relationship("Organization")


# ============================================================
# SISTEMA RBAC: Roles, Permisos, Usuarios Administrativos
# Centros de Costo y Catálogo de Conceptos de Cobro
# Agregado: 2026-02-10
# ============================================================

# Tabla intermedia rol <-> permiso (many-to-many)
rol_permiso = Table(
    'rol_permiso',
    Base.metadata,
    Column('rol_id', Integer, ForeignKey('roles.id', ondelete='CASCADE'), primary_key=True),
    Column('permiso_id', Integer, ForeignKey('permisos.id', ondelete='CASCADE'), primary_key=True),
)


class Permiso(Base):
    """Permiso atómico: modulo.accion (ej: caja.cobrar, deudas.crear)"""
    __tablename__ = "permisos"
    __table_args__ = (
        UniqueConstraint('modulo', 'accion', name='uq_modulo_accion'),
    )

    id = Column(Integer, primary_key=True, autoincrement=True)
    modulo = Column(String(50), nullable=False)
    accion = Column(String(50), nullable=False)
    descripcion = Column(String(200))

    @property
    def codigo(self):
        return f"{self.modulo}.{self.accion}"


class Rol(Base):
    """Rol con permisos asignados. 5 roles base por organización."""
    __tablename__ = "roles"
    __table_args__ = (
        UniqueConstraint('organization_id', 'codigo', name='uq_org_rol_codigo'),
    )

    id = Column(Integer, primary_key=True, autoincrement=True)
    organization_id = Column(Integer, ForeignKey("organizations.id"), nullable=False)
    codigo = Column(String(30), nullable=False)
    nombre = Column(String(100), nullable=False)
    descripcion = Column(Text)
    nivel = Column(Integer, default=0)          # admin=100, tesorero=80, cajero=50, secretaria=40, colegiado=10
    es_base = Column(Boolean, default=False)
    activo = Column(Boolean, default=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    permisos = relationship("Permiso", secondary=rol_permiso, backref="roles", lazy="joined")
    usuarios_admin = relationship("UsuarioAdmin", back_populates="rol", lazy="dynamic")

    def tiene_permiso(self, modulo: str, accion: str) -> bool:
        return any(p.modulo == modulo and p.accion == accion for p in self.permisos)


class CentroCosto(Base):
    """Punto de venta/cobro: Oficina, Restaurante, Bazar, etc."""
    __tablename__ = "centros_costo"
    __table_args__ = (
        UniqueConstraint('organization_id', 'codigo', name='uq_org_centro_codigo'),
    )

    id = Column(Integer, primary_key=True, autoincrement=True)
    organization_id = Column(Integer, ForeignKey("organizations.id"), nullable=False)
    codigo = Column(String(20), nullable=False)
    nombre = Column(String(100), nullable=False)
    direccion = Column(String(200))
    tipo = Column(String(30), default="oficina")
    serie_boleta = Column(String(4))
    serie_factura = Column(String(4))
    activo = Column(Boolean, default=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    organization = relationship("Organization", backref="centros_costo")
    usuarios_admin = relationship("UsuarioAdmin", back_populates="centro_costo")


class UsuarioAdmin(Base):
    """Usuario administrativo: vincula user -> rol -> centro de costo"""
    __tablename__ = "usuarios_admin"
    __table_args__ = (
        UniqueConstraint('organization_id', 'user_id', name='uq_org_user'),
        Index('ix_usuario_admin_org_activo', 'organization_id', 'activo'),
    )

    id = Column(Integer, primary_key=True, autoincrement=True)
    organization_id = Column(Integer, ForeignKey("organizations.id"), nullable=False)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    rol_id = Column(Integer, ForeignKey("roles.id"), nullable=False)
    centro_costo_id = Column(Integer, ForeignKey("centros_costo.id"), nullable=True)
    colegiado_id = Column(Integer, ForeignKey("colegiados.id"), nullable=True)

    nombre_completo = Column(String(200), nullable=False)
    email = Column(String(150))
    telefono = Column(String(20))
    cargo = Column(String(100))

    # Controles de caja
    monto_maximo_sin_aprobacion = Column(Float, default=0)
    puede_anular = Column(Boolean, default=False)
    puede_hacer_descuentos = Column(Boolean, default=False)

    activo = Column(Boolean, default=True)
    ultimo_acceso = Column(DateTime(timezone=True))
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())
    created_by = Column(Integer, ForeignKey("users.id"), nullable=True)

    rol = relationship("Rol", back_populates="usuarios_admin")
    centro_costo = relationship("CentroCosto", back_populates="usuarios_admin")
    organization = relationship("Organization", backref="usuarios_admin")

    def tiene_permiso(self, modulo: str, accion: str) -> bool:
        if not self.activo or not self.rol:
            return False
        return self.rol.tiene_permiso(modulo, accion)

    def es_admin(self) -> bool:
        return self.rol and self.rol.codigo == "admin"


class ConceptoCobro(Base):
    """Catálogo de conceptos de cobro: cuotas, constancias, alquileres, mercadería, multas, etc."""
    __tablename__ = "conceptos_cobro"
    __table_args__ = (
        UniqueConstraint('organization_id', 'codigo', name='uq_org_codigo_concepto'),
    )

    id = Column(Integer, primary_key=True, autoincrement=True)
    organization_id = Column(Integer, ForeignKey("organizations.id"), nullable=False)

    codigo = Column(String(20), nullable=False)
    nombre = Column(String(150), nullable=False)
    nombre_corto = Column(String(50))
    descripcion = Column(Text)

    # Clasificación
    categoria = Column(String(30), nullable=False, default="otros")
    # cuotas, constancias, derechos, capacitacion, alquileres, recreacion, mercaderia, multas, eventos, otros
    periodicidad = Column(String(20), nullable=False, default="unico")
    # mensual, anual, unico, por_uso, variable

    # Montos
    monto_base = Column(Float, nullable=False, default=0)
    monto_minimo = Column(Float, default=0)
    monto_maximo = Column(Float, default=0)
    permite_monto_libre = Column(Boolean, default=False)

    # Impuestos
    afecto_igv = Column(Boolean, default=False)
    tipo_afectacion_igv = Column(String(2), default="20")  # 10=gravado, 20=exonerado

    # Comprobante
    genera_comprobante = Column(Boolean, default=True)
    tipo_comprobante_default = Column(String(2), default="03")

    # Comportamiento
    requiere_colegiado = Column(Boolean, default=True)
    aplica_a_publico = Column(Boolean, default=False)
    genera_deuda = Column(Boolean, default=False)
    requiere_aprobacion = Column(Boolean, default=False)

    # Cuotas mensuales
    es_cuota_mensual = Column(Boolean, default=False)
    dia_vencimiento = Column(Integer, default=0)
    meses_aplicables = Column(String(50))

    # Stock (mercadería)
    maneja_stock = Column(Boolean, default=False)
    stock_actual = Column(Integer, default=0)
    stock_minimo = Column(Integer, default=0)

    # Estado
    activo = Column(Boolean, default=True)
    orden = Column(Integer, default=0)

    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())
    created_by = Column(Integer, ForeignKey("users.id"), nullable=True)

    organization = relationship("Organization", backref="conceptos_cobro")



# ============================================================
# SESIÓN DE CAJA: Apertura, Cierre, Cuadre
# ============================================================

class SesionCaja(Base):
    """Sesión de caja: apertura → operaciones → cierre/cuadre"""
    __tablename__ = "sesiones_caja"
    __table_args__ = (
        Index('ix_sesion_caja_centro_estado', 'centro_costo_id', 'estado'),
    )

    id = Column(Integer, primary_key=True, autoincrement=True)
    organization_id = Column(Integer, ForeignKey("organizations.id"), nullable=False)
    centro_costo_id = Column(Integer, ForeignKey("centros_costo.id"), nullable=False)
    usuario_admin_id = Column(Integer, ForeignKey("usuarios_admin.id"), nullable=False)

    fecha = Column(DateTime(timezone=True), nullable=False)
    estado = Column(String(20), default="abierta")  # abierta, cerrada, cuadrada

    # Apertura
    monto_apertura = Column(Numeric(12, 2), default=0)
    hora_apertura = Column(DateTime(timezone=True))

    # Totales calculados al cierre
    total_cobros_efectivo = Column(Numeric(12, 2), default=0)
    total_cobros_digital = Column(Numeric(12, 2), default=0)   # Yape, Plin, tarjeta, transferencia
    total_egresos = Column(Numeric(12, 2), default=0)
    cantidad_operaciones = Column(Integer, default=0)

    # Cierre
    total_esperado = Column(Numeric(12, 2), default=0)    # apertura + efectivo - egresos
    monto_cierre = Column(Numeric(12, 2), nullable=True)  # Lo que declara el cajero
    diferencia = Column(Numeric(12, 2), nullable=True)     # cierre - esperado
    hora_cierre = Column(DateTime(timezone=True), nullable=True)
    observaciones_cierre = Column(Text, nullable=True)

    cerrado_por_id = Column(Integer, ForeignKey("usuarios_admin.id"), nullable=True)

    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())

    # Relaciones
    organization = relationship("Organization")
    centro_costo = relationship("CentroCosto")
    cajero = relationship("UsuarioAdmin", foreign_keys=[usuario_admin_id])
    cerrado_por = relationship("UsuarioAdmin", foreign_keys=[cerrado_por_id])
    egresos = relationship("EgresoCaja", back_populates="sesion_caja", lazy="dynamic")


class EgresoCaja(Base):
    """Egresos/gastos durante una sesión de caja con liquidación"""
    __tablename__ = "egresos_caja"

    id = Column(Integer, primary_key=True, autoincrement=True)
    sesion_caja_id = Column(Integer, ForeignKey("sesiones_caja.id"), nullable=False)
    organization_id = Column(Integer, ForeignKey("organizations.id"), nullable=False)

    # Registro inicial: entrega de dinero
    monto = Column(Numeric(12, 2), nullable=False)       # Lo que se entregó
    concepto = Column(String(200), nullable=False)        # Motivo / sustento
    detalle = Column(Text, nullable=True)                 # Notas adicionales
    tipo = Column(String(30), default="gasto")            # gasto, devolucion, retiro_fondo
    responsable = Column(String(150), nullable=True)      # Quién recibe el dinero

    # Liquidación: cuando traen la factura y el vuelto
    monto_factura = Column(Numeric(12, 2), nullable=True)    # Lo que dice la factura
    monto_devuelto = Column(Numeric(12, 2), default=0)       # Vuelto regresado a caja
    estado = Column(String(20), default="pendiente")         # pendiente, liquidado
    liquidado_at = Column(DateTime(timezone=True), nullable=True)
    numero_documento = Column(String(50), nullable=True)     # Nro de boleta/factura

    autorizado_por_id = Column(Integer, ForeignKey("usuarios_admin.id"), nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    # Relaciones
    sesion_caja = relationship("SesionCaja", back_populates="egresos")
    autorizado_por = relationship("UsuarioAdmin")



class ComprobanteElectronico(Base):
    __tablename__ = "comprobantes_electronicos"

    id = Column(Integer, primary_key=True)
    organization_id = Column(Integer, nullable=False, default=1)

    # Referencia al pago
    payment_id = Column(Integer, ForeignKey("payments.id"))

    # Tipo y numeración
    tipo_comprobante = Column(String(2), nullable=False)      # 01=Factura, 03=Boleta, 07=NC, 08=ND
    serie = Column(String(4), nullable=False)                  # B001, F001, BC01, FC01
    numero = Column(Integer)                                   # Correlativo
    numero_formato = Column(String(15))                        # B001-00000001

    # Cliente
    cliente_tipo_doc = Column(String(2))                       # 0=Sin doc, 1=DNI, 6=RUC
    cliente_numero_doc = Column(String(15))
    cliente_razon_social = Column(String(200))
    cliente_direccion = Column(String(300))
    cliente_email = Column(String(150))

    # Detalle
    items = Column(JSON, default=[])                           # [{descripcion, cantidad, monto...}]
    subtotal = Column(Numeric(12, 2), default=0)
    igv = Column(Numeric(12, 2), default=0)
    total = Column(Numeric(12, 2), nullable=False, default=0)
    moneda = Column(String(3), default="PEN")

    # Estado: pendiente → aceptado | rechazado | anulado | error
    estado = Column(String(30), default="pendiente")
    hash_cpe = Column(String(100))
    codigo_sunat = Column(String(10))
    mensaje_sunat = Column(Text)

    # facturalo.pro
    facturalo_id = Column(String(50))                          # UUID en facturalo.pro
    pdf_url = Column(Text)
    xml_url = Column(Text)
    cdr_url = Column(Text)

    # Referencia cruzada
    referencia_externa = Column(String(50))                    # PAY-{id}
    observaciones = Column(Text)
    metodo_pago = Column(String(30))

    # Para Notas de Crédito/Débito
    doc_referencia_tipo = Column(String(2))
    doc_referencia_serie = Column(String(4))
    doc_referencia_numero = Column(Integer)
    doc_referencia_formato = Column(String(15))
    motivo_nota = Column(String(200))

    # Auditoría
    emitido_por = Column(Integer)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())
    anulado_at = Column(DateTime(timezone=True))

    # Relación
    payment = relationship("Payment", backref="comprobantes")

    def __repr__(self):
        return f"<Comprobante {self.numero_formato} [{self.estado}]>"


"""
Modelos: Verificación y Conciliación de Pagos Digitales
Agregar a app/models.py

Tablas:
- CuentaReceptora: Cuentas Yape/Plin/BBVA donde reciben pagos
- NotificacionBancaria: Emails parseados de los bancos
- VerificacionPago: Vinculación notificación ↔ pago
"""

# ══════════════════════════════════════════════════════════
# AGREGAR estos modelos a app/models.py
# ══════════════════════════════════════════════════════════


class CuentaReceptora(Base):
    """Cuentas donde el colegio recibe pagos digitales"""
    __tablename__ = "cuentas_receptoras"

    id = Column(Integer, primary_key=True, autoincrement=True)
    organization_id = Column(Integer, ForeignKey("organizations.id"), nullable=False)

    nombre = Column(String(100), nullable=False)          # "Yape Milagros", "Plin Paulo", "BBVA Institucional"
    tipo = Column(String(30), nullable=False)              # yape, plin, transferencia, deposito
    banco = Column(String(50))                             # BCP, Scotiabank, Interbank, BBVA
    titular = Column(String(200))                          # Nombre del titular
    numero_cuenta = Column(String(50))                     # Últimos dígitos o número parcial
    telefono = Column(String(15))                          # Número asociado a Yape/Plin

    # Email de notificaciones de este banco
    email_remitente = Column(String(150))                  # bancadigital@scotiabank.com.pe
    email_destinatario = Column(String(150))               # colegiocontadoresp.loreto@gmail.com

    activo = Column(Boolean, default=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    organization = relationship("Organization")


class NotificacionBancaria(Base):
    """Emails de notificación parseados automáticamente"""
    __tablename__ = "notificaciones_bancarias"
    __table_args__ = (
        Index('ix_notif_fecha_monto', 'fecha_operacion', 'monto'),
        Index('ix_notif_estado', 'estado'),
        Index('ix_notif_email_id', 'email_message_id', unique=True),
    )

    id = Column(Integer, primary_key=True, autoincrement=True)
    organization_id = Column(Integer, ForeignKey("organizations.id"), nullable=False)
    cuenta_receptora_id = Column(Integer, ForeignKey("cuentas_receptoras.id"), nullable=True)

    # Datos del email
    email_message_id = Column(String(200), unique=True)    # Gmail message ID (evita duplicados)
    email_from = Column(String(200))                        # bancadigital@scotiabank.com.pe
    email_subject = Column(String(500))
    email_date = Column(DateTime(timezone=True))            # Fecha del email

    # Datos parseados de la notificación
    banco = Column(String(50))                              # scotiabank, interbank, bcp, bbva
    tipo_operacion = Column(String(50))                     # plin_recibido, yape_recibido, transferencia
    monto = Column(Numeric(12, 2), nullable=False)
    moneda = Column(String(3), default="PEN")
    fecha_operacion = Column(DateTime(timezone=True))       # Fecha/hora de la operación bancaria
    codigo_operacion = Column(String(50))                   # Código de operación del banco
    remitente_nombre = Column(String(200))                  # Quien envió el dinero
    cuenta_destino = Column(String(100))                    # Cuenta que recibió (parcial)
    destino_tipo = Column(String(30))                       # "Yape", "Plin", "Cuenta"

    # Estado de conciliación
    estado = Column(String(20), default="pendiente")        # pendiente, conciliado, sin_match, ignorado
    payment_id = Column(Integer, ForeignKey("payments.id"), nullable=True)  # Pago matcheado
    conciliado_por = Column(String(50))                     # "auto" o nombre del usuario
    conciliado_at = Column(DateTime(timezone=True))
    observaciones = Column(Text)

    # Raw data para auditoría
    raw_body = Column(Text)                                 # Cuerpo del email original

    created_at = Column(DateTime(timezone=True), server_default=func.now())

    organization = relationship("Organization")
    cuenta = relationship("CuentaReceptora")
    payment = relationship("Payment")