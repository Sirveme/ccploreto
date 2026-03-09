"""
Modelo: Catálogo de Conceptos de Cobro
app/models/concepto_cobro.py

Permite al CCPL (y a cualquier colegio profesional en el SaaS)
gestionar sus propios conceptos de cobro: cuotas, constancias,
alquileres, mercadería, multas, eventos, etc.
"""

from sqlalchemy import (
    Column, Integer, String, Float, Boolean, Text, DateTime,
    ForeignKey, Enum as SAEnum, UniqueConstraint
)
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func
from app.database import Base
import enum


class CategoriaConcepto(str, enum.Enum):
    """Categorías para agrupar conceptos en la UI"""
    CUOTAS = "cuotas"                    # Cuotas ordinarias, extraordinarias, fraccionamiento
    CONSTANCIAS = "constancias"          # Habilidad, sufragio, no adeudo, otras
    DERECHOS = "derechos"                # Colegiatura, auditor, sociedad auditora
    CAPACITACION = "capacitacion"        # Certificados, programas, especializaciones
    ALQUILERES = "alquileres"            # Auditorio, salón, cancha
    RECREACION = "recreacion"            # Centro recreacional, piscina, deportes
    MERCADERIA = "mercaderia"            # Polos, pines, medallas, folders
    MULTAS = "multas"                    # Multas, inasistencias
    EVENTOS = "eventos"                  # Campeonatos, bingos, naviniño
    OTROS = "otros"                      # Ingresos varios


class TipoPeriodicidad(str, enum.Enum):
    """Cómo se cobra"""
    MENSUAL = "mensual"       # Cuotas mensuales
    ANUAL = "anual"           # Cuotas anuales
    UNICO = "unico"          # Pago único (constancia, derecho)
    POR_USO = "por_uso"      # Cada vez que se usa (alquiler, ingreso)
    VARIABLE = "variable"    # Monto variable (multas, mercadería)


class ConceptoCobro(Base):
    __tablename__ = "conceptos_cobro"
    __table_args__ = (
        UniqueConstraint('organization_id', 'codigo', name='uq_org_codigo_concepto'),
    )

    id = Column(Integer, primary_key=True, autoincrement=True)
    organization_id = Column(Integer, ForeignKey("organizations.id"), nullable=False)

    # Identificación
    codigo = Column(String(20), nullable=False)          # Ej: "CUOT-ORD", "CONST-HAB"
    nombre = Column(String(150), nullable=False)          # Ej: "Cuota Ordinaria Mensual"
    nombre_corto = Column(String(50))                     # Ej: "Cuota Mensual" (para tickets)
    descripcion = Column(Text)                            # Descripción larga

    # Clasificación
    categoria = Column(SAEnum(CategoriaConcepto), nullable=False, default=CategoriaConcepto.OTROS)
    periodicidad = Column(SAEnum(TipoPeriodicidad), nullable=False, default=TipoPeriodicidad.UNICO)

    # Montos
    monto_base = Column(Float, nullable=False, default=0)       # Precio estándar
    monto_minimo = Column(Float, default=0)                      # Para conceptos variables
    monto_maximo = Column(Float, default=0)                      # Para conceptos variables
    permite_monto_libre = Column(Boolean, default=False)         # Cajero puede cambiar monto

    # Impuestos
    afecto_igv = Column(Boolean, default=False)                  # ¿Gravado con IGV?
    tipo_afectacion_igv = Column(String(2), default="20")        # 10=gravado, 20=exonerado, 30=inafecto

    # Comprobante
    genera_comprobante = Column(Boolean, default=True)           # ¿Emitir boleta/factura?
    tipo_comprobante_default = Column(String(2), default="03")   # 03=boleta, 01=factura

    # Comportamiento
    requiere_colegiado = Column(Boolean, default=True)           # ¿Solo para colegiados?
    aplica_a_publico = Column(Boolean, default=False)            # ¿Cualquier persona puede pagar?
    genera_deuda = Column(Boolean, default=False)                # ¿Crea registro en tabla deudas?
    requiere_aprobacion = Column(Boolean, default=False)         # ¿Necesita aprobación de admin?

    # Para cuotas mensuales
    es_cuota_mensual = Column(Boolean, default=False)            # Marca especial para cuotas
    dia_vencimiento = Column(Integer, default=0)                 # Día del mes que vence (0=no aplica)
    meses_aplicables = Column(String(50))                        # "1,2,3,4,5,6,7,8,9,10,11,12" o subset

    # Stock (para mercadería)
    maneja_stock = Column(Boolean, default=False)
    stock_actual = Column(Integer, default=0)
    stock_minimo = Column(Integer, default=0)

    # Estado
    activo = Column(Boolean, default=True)
    orden = Column(Integer, default=0)                           # Para ordenar en la UI

    # Auditoría
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())
    created_by = Column(Integer, ForeignKey("users.id"), nullable=True)

    # Relaciones
    organization = relationship("Organization", backref="conceptos_cobro")


# ============================================================
# SEED DATA: Catálogo inicial del CCPL
# ============================================================

CATALOGO_CCPL = [
    # ── CUOTAS ──
    {
        "codigo": "CUOT-ORD",
        "nombre": "Cuota Ordinaria Mensual",
        "nombre_corto": "Cuota Mensual",
        "categoria": "cuotas",
        "periodicidad": "mensual",
        "monto_base": 20.00,
        "tipo_afectacion_igv": "20",
        "genera_deuda": True,
        "es_cuota_mensual": True,
        "requiere_colegiado": True,
        "dia_vencimiento": 30,
        "meses_aplicables": "1,2,3,4,5,6,7,8,9,10,11,12",
        "orden": 1,
    },
    {
        "codigo": "CUOT-EXT",
        "nombre": "Cuota Extraordinaria",
        "nombre_corto": "Cuota Extraord.",
        "categoria": "cuotas",
        "periodicidad": "unico",
        "monto_base": 0,
        "permite_monto_libre": True,
        "tipo_afectacion_igv": "20",
        "genera_deuda": True,
        "requiere_colegiado": True,
        "orden": 2,
    },
    {
        "codigo": "CUOT-FRAC",
        "nombre": "Cuota de Fraccionamiento",
        "nombre_corto": "Fraccionamiento",
        "categoria": "cuotas",
        "periodicidad": "mensual",
        "monto_base": 0,
        "permite_monto_libre": True,
        "tipo_afectacion_igv": "20",
        "genera_deuda": True,
        "requiere_colegiado": True,
        "orden": 3,
    },

    # ── CONSTANCIAS ──
    {
        "codigo": "CONST-HAB",
        "nombre": "Constancia de Habilidad",
        "nombre_corto": "Const. Habilidad",
        "categoria": "constancias",
        "periodicidad": "unico",
        "monto_base": 30.00,
        "tipo_afectacion_igv": "20",
        "requiere_colegiado": True,
        "orden": 10,
    },
    {
        "codigo": "CONST-SUF",
        "nombre": "Constancia de Sufragio",
        "nombre_corto": "Const. Sufragio",
        "categoria": "constancias",
        "periodicidad": "unico",
        "monto_base": 20.00,
        "tipo_afectacion_igv": "20",
        "requiere_colegiado": True,
        "orden": 11,
    },
    {
        "codigo": "CONST-NAD",
        "nombre": "Constancia de No Adeudo",
        "nombre_corto": "Const. No Adeudo",
        "categoria": "constancias",
        "periodicidad": "unico",
        "monto_base": 20.00,
        "tipo_afectacion_igv": "20",
        "requiere_colegiado": True,
        "orden": 12,
    },
    {
        "codigo": "CONST-OTR",
        "nombre": "Otras Constancias",
        "nombre_corto": "Otra Constancia",
        "categoria": "constancias",
        "periodicidad": "unico",
        "monto_base": 20.00,
        "permite_monto_libre": True,
        "tipo_afectacion_igv": "20",
        "requiere_colegiado": True,
        "orden": 13,
    },

    # ── DERECHOS ──
    {
        "codigo": "DER-COL",
        "nombre": "Derecho de Colegiatura",
        "nombre_corto": "Colegiatura",
        "categoria": "derechos",
        "periodicidad": "unico",
        "monto_base": 350.00,
        "tipo_afectacion_igv": "20",
        "requiere_colegiado": True,
        "orden": 20,
    },
    {
        "codigo": "DER-AUD",
        "nombre": "Derecho de Auditor Independiente",
        "nombre_corto": "Auditor Indep.",
        "categoria": "derechos",
        "periodicidad": "anual",
        "monto_base": 200.00,
        "tipo_afectacion_igv": "20",
        "requiere_colegiado": True,
        "orden": 21,
    },
    {
        "codigo": "DER-SOC",
        "nombre": "Derecho de Sociedad Auditora",
        "nombre_corto": "Soc. Auditora",
        "categoria": "derechos",
        "periodicidad": "anual",
        "monto_base": 500.00,
        "tipo_afectacion_igv": "20",
        "requiere_colegiado": True,
        "orden": 22,
    },

    # ── CAPACITACIÓN ──
    {
        "codigo": "CAP-CERT",
        "nombre": "Certificado de Capacitación",
        "nombre_corto": "Cert. Capacitación",
        "categoria": "capacitacion",
        "periodicidad": "unico",
        "monto_base": 50.00,
        "permite_monto_libre": True,
        "tipo_afectacion_igv": "20",
        "requiere_colegiado": True,
        "orden": 30,
    },
    {
        "codigo": "CAP-ESP",
        "nombre": "Programa de Especialización",
        "nombre_corto": "Especialización",
        "categoria": "capacitacion",
        "periodicidad": "unico",
        "monto_base": 0,
        "permite_monto_libre": True,
        "tipo_afectacion_igv": "20",
        "orden": 31,
    },

    # ── ALQUILERES ──
    {
        "codigo": "ALQ-AUD",
        "nombre": "Alquiler de Auditorio",
        "nombre_corto": "Alq. Auditorio",
        "categoria": "alquileres",
        "periodicidad": "por_uso",
        "monto_base": 500.00,
        "permite_monto_libre": True,
        "tipo_afectacion_igv": "10",
        "afecto_igv": True,
        "requiere_colegiado": False,
        "aplica_a_publico": True,
        "orden": 40,
    },
    {
        "codigo": "ALQ-SAL",
        "nombre": "Alquiler de Salonazo",
        "nombre_corto": "Alq. Salonazo",
        "categoria": "alquileres",
        "periodicidad": "por_uso",
        "monto_base": 300.00,
        "permite_monto_libre": True,
        "tipo_afectacion_igv": "10",
        "afecto_igv": True,
        "requiere_colegiado": False,
        "aplica_a_publico": True,
        "orden": 41,
    },
    {
        "codigo": "ALQ-CAN",
        "nombre": "Alquiler de Cancha Sintética",
        "nombre_corto": "Alq. Cancha",
        "categoria": "alquileres",
        "periodicidad": "por_uso",
        "monto_base": 100.00,
        "permite_monto_libre": True,
        "tipo_afectacion_igv": "10",
        "afecto_igv": True,
        "requiere_colegiado": False,
        "aplica_a_publico": True,
        "orden": 42,
    },

    # ── RECREACIÓN ──
    {
        "codigo": "REC-ING",
        "nombre": "Ingreso al Centro Recreacional",
        "nombre_corto": "Ingreso C.R.",
        "categoria": "recreacion",
        "periodicidad": "por_uso",
        "monto_base": 10.00,
        "tipo_afectacion_igv": "20",
        "requiere_colegiado": False,
        "aplica_a_publico": True,
        "orden": 50,
    },

    # ── MERCADERÍA ──
    {
        "codigo": "MERC-PIN",
        "nombre": "Pin Institucional",
        "nombre_corto": "Pin",
        "categoria": "mercaderia",
        "periodicidad": "por_uso",
        "monto_base": 15.00,
        "tipo_afectacion_igv": "10",
        "afecto_igv": True,
        "maneja_stock": True,
        "requiere_colegiado": False,
        "aplica_a_publico": True,
        "orden": 60,
    },
    {
        "codigo": "MERC-MED",
        "nombre": "Medalla",
        "nombre_corto": "Medalla",
        "categoria": "mercaderia",
        "periodicidad": "por_uso",
        "monto_base": 50.00,
        "tipo_afectacion_igv": "10",
        "afecto_igv": True,
        "maneja_stock": True,
        "requiere_colegiado": False,
        "aplica_a_publico": True,
        "orden": 61,
    },
    {
        "codigo": "MERC-GOR",
        "nombre": "Gorro Institucional",
        "nombre_corto": "Gorro",
        "categoria": "mercaderia",
        "periodicidad": "por_uso",
        "monto_base": 25.00,
        "tipo_afectacion_igv": "10",
        "afecto_igv": True,
        "maneja_stock": True,
        "requiere_colegiado": False,
        "aplica_a_publico": True,
        "orden": 62,
    },
    {
        "codigo": "MERC-POL",
        "nombre": "Polo Institucional",
        "nombre_corto": "Polo",
        "categoria": "mercaderia",
        "periodicidad": "por_uso",
        "monto_base": 35.00,
        "permite_monto_libre": True,
        "tipo_afectacion_igv": "10",
        "afecto_igv": True,
        "maneja_stock": True,
        "requiere_colegiado": False,
        "aplica_a_publico": True,
        "orden": 63,
    },
    {
        "codigo": "MERC-LAP",
        "nombre": "Lapicero Institucional",
        "nombre_corto": "Lapicero",
        "categoria": "mercaderia",
        "periodicidad": "por_uso",
        "monto_base": 5.00,
        "tipo_afectacion_igv": "10",
        "afecto_igv": True,
        "maneja_stock": True,
        "requiere_colegiado": False,
        "aplica_a_publico": True,
        "orden": 64,
    },
    {
        "codigo": "MERC-FOL",
        "nombre": "Folder Colgante Verde",
        "nombre_corto": "Folder",
        "categoria": "mercaderia",
        "periodicidad": "por_uso",
        "monto_base": 10.00,
        "tipo_afectacion_igv": "10",
        "afecto_igv": True,
        "maneja_stock": True,
        "requiere_colegiado": False,
        "aplica_a_publico": True,
        "orden": 65,
    },
    {
        "codigo": "MERC-TAS",
        "nombre": "Tasa Institucional",
        "nombre_corto": "Tasa",
        "categoria": "mercaderia",
        "periodicidad": "por_uso",
        "monto_base": 20.00,
        "tipo_afectacion_igv": "10",
        "afecto_igv": True,
        "maneja_stock": True,
        "requiere_colegiado": False,
        "aplica_a_publico": True,
        "orden": 66,
    },

    # ── MULTAS ──
    {
        "codigo": "MULT-INA",
        "nombre": "Multa por Inasistencia a Reunión",
        "nombre_corto": "Multa Inasist.",
        "categoria": "multas",
        "periodicidad": "variable",
        "monto_base": 50.00,
        "permite_monto_libre": True,
        "tipo_afectacion_igv": "20",
        "genera_deuda": True,
        "requiere_colegiado": True,
        "orden": 70,
    },
    {
        "codigo": "MULT-FAL",
        "nombre": "Multa por Falta",
        "nombre_corto": "Multa",
        "categoria": "multas",
        "periodicidad": "variable",
        "monto_base": 0,
        "permite_monto_libre": True,
        "tipo_afectacion_igv": "20",
        "genera_deuda": True,
        "requiere_colegiado": True,
        "orden": 71,
    },
    {
        "codigo": "MULT-ENC",
        "nombre": "Multa por No Responder Encuesta",
        "nombre_corto": "Multa Encuesta",
        "categoria": "multas",
        "periodicidad": "variable",
        "monto_base": 30.00,
        "permite_monto_libre": True,
        "tipo_afectacion_igv": "20",
        "genera_deuda": True,
        "requiere_colegiado": True,
        "orden": 72,
    },

    # ── EVENTOS ──
    {
        "codigo": "EVT-CAMP",
        "nombre": "Inscripción Campeonato",
        "nombre_corto": "Campeonato",
        "categoria": "eventos",
        "periodicidad": "unico",
        "monto_base": 0,
        "permite_monto_libre": True,
        "tipo_afectacion_igv": "20",
        "requiere_colegiado": False,
        "aplica_a_publico": True,
        "orden": 80,
    },
    {
        "codigo": "EVT-BIN",
        "nombre": "Bingazo del Contador",
        "nombre_corto": "Bingazo",
        "categoria": "eventos",
        "periodicidad": "unico",
        "monto_base": 0,
        "permite_monto_libre": True,
        "tipo_afectacion_igv": "20",
        "requiere_colegiado": False,
        "aplica_a_publico": True,
        "orden": 81,
    },
    {
        "codigo": "EVT-NAV",
        "nombre": "Naviniño",
        "nombre_corto": "Naviniño",
        "categoria": "eventos",
        "periodicidad": "unico",
        "monto_base": 0,
        "permite_monto_libre": True,
        "tipo_afectacion_igv": "20",
        "orden": 82,
    },
    {
        "codigo": "EVT-DEP",
        "nombre": "Reclamo por Área de Deportes",
        "nombre_corto": "Recl. Deportes",
        "categoria": "eventos",
        "periodicidad": "unico",
        "monto_base": 0,
        "permite_monto_libre": True,
        "tipo_afectacion_igv": "20",
        "orden": 83,
    },

    # ── OTROS ──
    {
        "codigo": "OTR-VAR",
        "nombre": "Ingreso Varios",
        "nombre_corto": "Varios",
        "categoria": "otros",
        "periodicidad": "variable",
        "monto_base": 0,
        "permite_monto_libre": True,
        "tipo_afectacion_igv": "20",
        "requiere_colegiado": False,
        "aplica_a_publico": True,
        "orden": 90,
    },
]


def seed_conceptos_ccpl(db, organization_id: int):
    """
    Carga el catálogo inicial de conceptos del CCPL.
    Usar una sola vez o como migración de datos.

    Uso:
        from app.models.concepto_cobro import seed_conceptos_ccpl
        seed_conceptos_ccpl(db, org_id=1)
    """
    from sqlalchemy.orm import Session

    existentes = db.query(ConceptoCobro).filter(
        ConceptoCobro.organization_id == organization_id
    ).count()

    if existentes > 0:
        print(f"Ya existen {existentes} conceptos para org {organization_id}. Saltando seed.")
        return existentes

    count = 0
    for item in CATALOGO_CCPL:
        concepto = ConceptoCobro(
            organization_id=organization_id,
            codigo=item["codigo"],
            nombre=item["nombre"],
            nombre_corto=item.get("nombre_corto"),
            categoria=item.get("categoria", "otros"),
            periodicidad=item.get("periodicidad", "unico"),
            monto_base=item.get("monto_base", 0),
            permite_monto_libre=item.get("permite_monto_libre", False),
            tipo_afectacion_igv=item.get("tipo_afectacion_igv", "20"),
            afecto_igv=item.get("afecto_igv", False),
            genera_deuda=item.get("genera_deuda", False),
            es_cuota_mensual=item.get("es_cuota_mensual", False),
            dia_vencimiento=item.get("dia_vencimiento", 0),
            meses_aplicables=item.get("meses_aplicables"),
            requiere_colegiado=item.get("requiere_colegiado", True),
            aplica_a_publico=item.get("aplica_a_publico", False),
            maneja_stock=item.get("maneja_stock", False),
            genera_comprobante=True,
            activo=True,
            orden=item.get("orden", 0),
        )
        db.add(concepto)
        count += 1

    db.commit()
    print(f"Creados {count} conceptos de cobro para org {organization_id}")
    return count