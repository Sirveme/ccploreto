"""
Modelo: Roles, Permisos y Usuarios Administrativos
app/models/roles_permisos.py

Sistema RBAC (Role-Based Access Control) para colegios profesionales.
Soporta: admin, tesorero, cajero, secretaria, colegiado
+ centros de costo para puntos de venta (restaurante, bazar, etc.)

Uso con SaaS: cada organization_id tiene sus propios roles y usuarios.
"""

from sqlalchemy import (
    Column, Integer, String, Boolean, Text, DateTime, Float,
    ForeignKey, Table, UniqueConstraint, Index
)
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func
from app.database import Base


# ============================================================
# TABLA INTERMEDIA: rol <-> permiso (many-to-many)
# ============================================================

rol_permiso = Table(
    'rol_permiso',
    Base.metadata,
    Column('rol_id', Integer, ForeignKey('roles.id', ondelete='CASCADE'), primary_key=True),
    Column('permiso_id', Integer, ForeignKey('permisos.id', ondelete='CASCADE'), primary_key=True),
    extend_existing=True
)


# ============================================================
# PERMISOS
# ============================================================

class Permiso(Base):
    """
    Permiso atómico: modulo + accion.
    Ej: caja.cobrar, colegiados.ver, reportes.exportar
    """
    __tablename__ = "permisos"
    __table_args__ = (
        UniqueConstraint('modulo', 'accion', name='uq_modulo_accion'),
    )

    id = Column(Integer, primary_key=True, autoincrement=True)
    modulo = Column(String(50), nullable=False)      # caja, colegiados, deudas, etc.
    accion = Column(String(50), nullable=False)       # ver, crear, editar, eliminar, aprobar
    descripcion = Column(String(200))                 # "Puede realizar cobros en caja"

    @property
    def codigo(self):
        return f"{self.modulo}.{self.accion}"

    def __repr__(self):
        return f"<Permiso {self.modulo}.{self.accion}>"


# ============================================================
# ROLES
# ============================================================

class Rol(Base):
    """
    Rol del sistema. Cada organización puede tener sus propios roles,
    pero los 5 base se crean automáticamente.
    """
    __tablename__ = "roles"
    __table_args__ = (
        UniqueConstraint('organization_id', 'codigo', name='uq_org_rol_codigo'),
    )

    id = Column(Integer, primary_key=True, autoincrement=True)
    organization_id = Column(Integer, ForeignKey("organizations.id"), nullable=False)

    codigo = Column(String(30), nullable=False)         # admin, tesorero, cajero, etc.
    nombre = Column(String(100), nullable=False)         # "Administrador", "Cajero"
    descripcion = Column(Text)
    nivel = Column(Integer, default=0)                   # 100=admin, 80=tesorero, 50=cajero, etc.
    es_base = Column(Boolean, default=False)             # Roles del sistema (no eliminables)
    activo = Column(Boolean, default=True)

    created_at = Column(DateTime(timezone=True), server_default=func.now())

    # Relaciones
    permisos = relationship("Permiso", secondary=rol_permiso, backref="roles", lazy="joined")
    usuarios = relationship("UsuarioAdmin", back_populates="rol", lazy="dynamic")

    def tiene_permiso(self, modulo: str, accion: str) -> bool:
        """Verifica si el rol tiene un permiso específico"""
        return any(
            p.modulo == modulo and p.accion == accion
            for p in self.permisos
        )

    def __repr__(self):
        return f"<Rol {self.codigo} org={self.organization_id}>"


# ============================================================
# CENTRO DE COSTO (puntos de venta/cobro)
# ============================================================

class CentroCosto(Base):
    """
    Punto de venta/cobro: Oficina Principal, Restaurante, Cafetín,
    Hotel, Bazar, Centro Recreacional, etc.
    """
    __tablename__ = "centros_costo"
    __table_args__ = (
        UniqueConstraint('organization_id', 'codigo', name='uq_org_centro_codigo'),
    )

    id = Column(Integer, primary_key=True, autoincrement=True)
    organization_id = Column(Integer, ForeignKey("organizations.id"), nullable=False)

    codigo = Column(String(20), nullable=False)        # "OFI-PRINC", "REST", "BAZAR"
    nombre = Column(String(100), nullable=False)        # "Oficina Principal"
    direccion = Column(String(200))                     # Ubicación física
    tipo = Column(String(30), default="oficina")        # oficina, restaurante, tienda, recreacion

    # Serie de comprobante asignada (si tiene caja propia)
    serie_boleta = Column(String(4))                    # "B001", "B002"
    serie_factura = Column(String(4))                   # "F001", "F002"

    activo = Column(Boolean, default=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    # Relaciones
    organization = relationship("Organization", backref="centros_costo")
    usuarios = relationship("UsuarioAdmin", back_populates="centro_costo")

    def __repr__(self):
        return f"<CentroCosto {self.codigo} - {self.nombre}>"


# ============================================================
# USUARIO ADMINISTRATIVO
# ============================================================

class UsuarioAdmin(Base):
    """
    Usuario del sistema (administrativo o colegiado con acceso).
    Separado de la tabla auth/users para mantener clean el auth.
    Se vincula a users.id para login.
    """
    __tablename__ = "usuarios_admin"
    __table_args__ = (
        UniqueConstraint('organization_id', 'user_id', name='uq_org_user'),
        Index('ix_usuario_admin_org_activo', 'organization_id', 'activo'),
    )

    id = Column(Integer, primary_key=True, autoincrement=True)
    organization_id = Column(Integer, ForeignKey("organizations.id"), nullable=False)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)

    # Rol asignado
    rol_id = Column(Integer, ForeignKey("roles.id"), nullable=False)

    # Centro de costo asignado (opcional: None = acceso a todos)
    centro_costo_id = Column(Integer, ForeignKey("centros_costo.id"), nullable=True)

    # Vínculo con colegiado (si es directivo/colegiado)
    colegiado_id = Column(Integer, ForeignKey("colegiados.id"), nullable=True)

    # Datos del usuario
    nombre_completo = Column(String(200), nullable=False)
    email = Column(String(150))
    telefono = Column(String(20))
    cargo = Column(String(100))                          # "Cajera", "Tesorero", "Decano"

    # Config de caja (para cajeros)
    monto_maximo_sin_aprobacion = Column(Float, default=0)  # Monto máximo que puede cobrar sin autorización
    puede_anular = Column(Boolean, default=False)            # ¿Puede anular comprobantes?
    puede_hacer_descuentos = Column(Boolean, default=False)  # ¿Puede aplicar descuentos?

    # Estado
    activo = Column(Boolean, default=True)
    ultimo_acceso = Column(DateTime(timezone=True))

    # Auditoría
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())
    created_by = Column(Integer, ForeignKey("users.id"), nullable=True)

    # Relaciones
    rol = relationship("Rol", back_populates="usuarios")
    centro_costo = relationship("CentroCosto", back_populates="usuarios")
    organization = relationship("Organization", backref="usuarios_admin")

    def tiene_permiso(self, modulo: str, accion: str) -> bool:
        """Verifica si el usuario tiene un permiso a través de su rol"""
        if not self.activo or not self.rol:
            return False
        return self.rol.tiene_permiso(modulo, accion)

    def es_admin(self) -> bool:
        return self.rol and self.rol.codigo == "admin"

    def es_cajero(self) -> bool:
        return self.rol and self.rol.codigo == "cajero"

    def __repr__(self):
        return f"<UsuarioAdmin {self.nombre_completo} rol={self.rol.codigo if self.rol else '?'}>"


# ============================================================
# DEFINICIÓN DE PERMISOS POR MÓDULO
# ============================================================

PERMISOS_SISTEMA = [
    # ── CAJA ──
    ("caja", "ver", "Ver pantalla de caja"),
    ("caja", "cobrar", "Realizar cobros"),
    ("caja", "anular", "Anular cobros/comprobantes"),
    ("caja", "descuento", "Aplicar descuentos"),
    ("caja", "cierre", "Realizar cierre de caja"),
    ("caja", "egresos", "Registrar egresos de dinero"),

    # ── COLEGIADOS ──
    ("colegiados", "ver", "Ver lista de colegiados"),
    ("colegiados", "crear", "Registrar nuevos colegiados"),
    ("colegiados", "editar", "Editar datos de colegiados"),
    ("colegiados", "eliminar", "Eliminar colegiados"),
    ("colegiados", "habilitar", "Cambiar estado hábil/inhábil"),

    # ── DEUDAS ──
    ("deudas", "ver", "Ver deudas de colegiados"),
    ("deudas", "crear", "Generar deudas (cuotas, multas)"),
    ("deudas", "editar", "Modificar deudas"),
    ("deudas", "eliminar", "Eliminar deudas"),
    ("deudas", "masiva", "Generación masiva de deudas"),
    ("deudas", "condonar", "Condonar deudas"),

    # ── COMPROBANTES ──
    ("comprobantes", "ver", "Ver comprobantes emitidos"),
    ("comprobantes", "emitir", "Emitir comprobantes"),
    ("comprobantes", "anular", "Anular comprobantes"),
    ("comprobantes", "reenviar", "Reenviar comprobante por email"),

    # ── CONCEPTOS ──
    ("conceptos", "ver", "Ver catálogo de conceptos"),
    ("conceptos", "crear", "Crear nuevos conceptos de cobro"),
    ("conceptos", "editar", "Editar conceptos"),
    ("conceptos", "eliminar", "Eliminar conceptos"),

    # ── PAGOS ──
    ("pagos", "ver", "Ver pagos registrados"),
    ("pagos", "aprobar", "Aprobar pagos pendientes"),
    ("pagos", "rechazar", "Rechazar pagos"),

    # ── REPORTES ──
    ("reportes", "ver", "Ver reportes"),
    ("reportes", "financiero", "Reportes financieros detallados"),
    ("reportes", "exportar", "Exportar reportes (Excel/PDF)"),
    ("reportes", "dashboard", "Ver dashboard general"),

    # ── TRAMITES / MESA DE PARTES ──
    ("tramites", "ver", "Ver trámites"),
    ("tramites", "crear", "Registrar trámites"),
    ("tramites", "editar", "Editar/derivar trámites"),
    ("tramites", "resolver", "Resolver trámites"),

    # ── COMUNICACIONES ──
    ("comunicaciones", "ver", "Ver comunicaciones"),
    ("comunicaciones", "enviar", "Enviar notificaciones"),
    ("comunicaciones", "masiva", "Envío masivo de comunicaciones"),

    # ── CONSTANCIAS ──
    ("constancias", "ver", "Ver constancias emitidas"),
    ("constancias", "emitir", "Emitir constancias"),

    # ── CONFIGURACIÓN ──
    ("configuracion", "ver", "Ver configuración"),
    ("configuracion", "editar", "Editar configuración del sistema"),

    # ── USUARIOS ──
    ("usuarios", "ver", "Ver usuarios del sistema"),
    ("usuarios", "crear", "Crear usuarios"),
    ("usuarios", "editar", "Editar usuarios"),
    ("usuarios", "eliminar", "Desactivar usuarios"),
]


# ============================================================
# PERMISOS POR ROL (qué puede hacer cada uno)
# ============================================================

PERMISOS_POR_ROL = {
    "admin": "*",   # TODOS los permisos

    "tesorero": [
        "caja.*",                # Todo en caja
        "colegiados.ver",
        "deudas.*",              # Todo en deudas
        "comprobantes.*",        # Todo en comprobantes
        "conceptos.*",           # Todo en conceptos
        "pagos.*",               # Todo en pagos
        "reportes.*",            # Todo en reportes
        "constancias.*",
        "comunicaciones.ver",
        "configuracion.ver",
        "usuarios.ver",
    ],

    "cajero": [
        "caja.ver",
        "caja.cobrar",
        "colegiados.ver",
        "deudas.ver",
        "comprobantes.ver",
        "comprobantes.emitir",
        "conceptos.ver",
        "pagos.ver",
        "constancias.ver",
        "constancias.emitir",
    ],

    "secretaria": [
        "colegiados.ver",
        "colegiados.crear",
        "colegiados.editar",
        "tramites.*",            # Todo en trámites
        "comunicaciones.*",      # Todo en comunicaciones
        "constancias.*",
        "deudas.ver",
        "pagos.ver",
        "comprobantes.ver",
        "reportes.ver",
    ],

    "colegiado": [
        "caja.ver",              # Ve su estado de cuenta
        "deudas.ver",            # Ve sus deudas
        "pagos.ver",             # Ve sus pagos
        "comprobantes.ver",      # Ve sus comprobantes
        "constancias.ver",       # Ve sus constancias
        "tramites.ver",          # Ve sus trámites
        "tramites.crear",        # Puede iniciar trámites
        "comunicaciones.ver",    # Ve comunicaciones que le llegan
    ],
}


# ============================================================
# ROLES BASE
# ============================================================

ROLES_BASE = [
    {
        "codigo": "admin",
        "nombre": "Administrador",
        "descripcion": "Acceso total al sistema. Para Decano y directivos designados.",
        "nivel": 100,
    },
    {
        "codigo": "tesorero",
        "nombre": "Tesorero / Finanzas",
        "descripcion": "Gestión financiera: cobros, pagos, comprobantes, reportes, deudas.",
        "nivel": 80,
    },
    {
        "codigo": "cajero",
        "nombre": "Cajero",
        "descripcion": "Cobros presenciales y emisión de comprobantes. Sin acceso a reportes ni configuración.",
        "nivel": 50,
    },
    {
        "codigo": "secretaria",
        "nombre": "Secretaría / Mesa de Partes",
        "descripcion": "Trámites, documentos, comunicaciones, registro de colegiados.",
        "nivel": 40,
    },
    {
        "codigo": "colegiado",
        "nombre": "Colegiado",
        "descripcion": "Acceso personal: ver deudas, pagar, solicitar constancias, trámites.",
        "nivel": 10,
    },
]


# ============================================================
# CENTROS DE COSTO INICIALES CCPL
# ============================================================

CENTROS_COSTO_CCPL = [
    {
        "codigo": "OFI-PRINC",
        "nombre": "Oficina Principal",
        "direccion": "Calle Echenique N° 451, Iquitos",
        "tipo": "oficina",
        "serie_boleta": "B001",
        "serie_factura": "F001",
    },
    {
        "codigo": "REST",
        "nombre": "Restaurante",
        "direccion": "Centro Recreacional CCPL",
        "tipo": "restaurante",
        "serie_boleta": "B002",
    },
    {
        "codigo": "CAFET",
        "nombre": "Cafetín",
        "direccion": "Centro Recreacional CCPL",
        "tipo": "restaurante",
        "serie_boleta": "B003",
    },
    {
        "codigo": "HOTEL",
        "nombre": "Hotel",
        "direccion": "Centro Recreacional CCPL",
        "tipo": "tienda",
        "serie_boleta": "B004",
    },
    {
        "codigo": "BAZAR",
        "nombre": "Bazar / Merchandising",
        "direccion": "Oficina Principal CCPL",
        "tipo": "tienda",
        "serie_boleta": "B005",
    },
    {
        "codigo": "RECREAC",
        "nombre": "Centro Recreacional (Piscina, Canchas)",
        "direccion": "Centro Recreacional CCPL",
        "tipo": "recreacion",
        "serie_boleta": "B006",
    },
]


# ============================================================
# FUNCIÓN SEED: Crear roles, permisos y centros de costo
# ============================================================

def seed_roles_y_permisos(db, organization_id: int):
    """
    Crea los permisos, roles base y centros de costo para una organización.

    Uso:
        from app.models.roles_permisos import seed_roles_y_permisos
        seed_roles_y_permisos(db, org_id=1)
    """
    from sqlalchemy.orm import Session

    # 1. Crear permisos globales (si no existen)
    permisos_existentes = db.query(Permiso).count()
    permisos_map = {}

    if permisos_existentes == 0:
        print("Creando permisos del sistema...")
        for modulo, accion, desc in PERMISOS_SISTEMA:
            p = Permiso(modulo=modulo, accion=accion, descripcion=desc)
            db.add(p)
            db.flush()
            permisos_map[f"{modulo}.{accion}"] = p
        print(f"  → {len(PERMISOS_SISTEMA)} permisos creados")
    else:
        for p in db.query(Permiso).all():
            permisos_map[f"{p.modulo}.{p.accion}"] = p
        print(f"  → {permisos_existentes} permisos existentes")

    # 2. Crear roles para la organización
    roles_existentes = db.query(Rol).filter(
        Rol.organization_id == organization_id
    ).count()

    if roles_existentes > 0:
        print(f"Ya existen {roles_existentes} roles para org {organization_id}. Saltando.")
    else:
        print("Creando roles base...")
        for rol_data in ROLES_BASE:
            rol = Rol(
                organization_id=organization_id,
                codigo=rol_data["codigo"],
                nombre=rol_data["nombre"],
                descripcion=rol_data["descripcion"],
                nivel=rol_data["nivel"],
                es_base=True,
            )

            # Asignar permisos según PERMISOS_POR_ROL
            permisos_del_rol = PERMISOS_POR_ROL.get(rol_data["codigo"], [])

            if permisos_del_rol == "*":
                # Admin: todos los permisos
                rol.permisos = list(permisos_map.values())
            else:
                for permiso_pattern in permisos_del_rol:
                    if permiso_pattern.endswith(".*"):
                        # Wildcard: todas las acciones del módulo
                        modulo = permiso_pattern.replace(".*", "")
                        for key, p in permisos_map.items():
                            if key.startswith(f"{modulo}."):
                                rol.permisos.append(p)
                    elif permiso_pattern in permisos_map:
                        rol.permisos.append(permisos_map[permiso_pattern])

            db.add(rol)
            print(f"  → Rol '{rol_data['codigo']}' con {len(rol.permisos)} permisos")

    # 3. Crear centros de costo
    centros_existentes = db.query(CentroCosto).filter(
        CentroCosto.organization_id == organization_id
    ).count()

    if centros_existentes > 0:
        print(f"Ya existen {centros_existentes} centros de costo. Saltando.")
    else:
        print("Creando centros de costo...")
        for cc_data in CENTROS_COSTO_CCPL:
            cc = CentroCosto(
                organization_id=organization_id,
                **cc_data
            )
            db.add(cc)
            print(f"  → Centro '{cc_data['nombre']}'")

    db.commit()
    print("✓ Seed completado")