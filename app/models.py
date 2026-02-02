from sqlalchemy import Column, Integer, String, ForeignKey, Boolean, DateTime, Text, JSON, Float, Enum, Date
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func
from .database import Base
import enum
from sqlalchemy.dialects.postgresql import JSONB

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


class Debt(Base):
    __tablename__ = "debts"
    id = Column(Integer, primary_key=True)
    organization_id = Column(Integer, ForeignKey("organizations.id"))
    member_id = Column(Integer, ForeignKey("members.id"), nullable=True)  # Para condominios
    colegiado_id = Column(Integer, ForeignKey("colegiados.id"), nullable=True)  # Para colegios profesionales
    
    concept = Column(String)
    periodo = Column(String, nullable=True)  # '2024-01', '2024-02'
    amount = Column(Float)
    balance = Column(Float)
    status = Column(String, default="pending")  # pending, partial, paid
    due_date = Column(DateTime(timezone=True), nullable=True)
    attachment_url = Column(String, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    
    # Relaciones
    member = relationship("Member")
    colegiado = relationship("Colegiado", foreign_keys=[colegiado_id])
    organization = relationship("Organization")


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
    
    # Credenciales Únicas (Para entrar al sistema)
    public_id = Column(String, unique=True, index=True) # DNI
    access_code = Column(String) # Hash del Password
    
    name = Column(String) # Nombre Real (Juan Pérez)
    email = Column(String, nullable=True)
    phone = Column(String, nullable=True)
    photo_url = Column(String, nullable=True) # Foto de perfil global
    
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    
    # Relación: Un usuario puede ser miembro de muchos lugares
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

    @property
    def es_habil(self):
        return self.condicion in ('habil', 'vitalicio')