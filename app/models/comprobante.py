"""
Modelo: Comprobantes Electrónicos
app/models/comprobante.py

Almacena boletas/facturas emitidas vía facturalo.pro
"""

from sqlalchemy import Column, Integer, String, Float, Text, Boolean, DateTime, ForeignKey, JSON
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func
from app.database import Base


class Comprobante(Base):
    """
    Comprobante Electrónico (Boleta/Factura)
    Emitido a través de facturalo.pro
    """
    __tablename__ = "comprobantes"
    
    id = Column(Integer, primary_key=True)
    organization_id = Column(Integer, ForeignKey("organizations.id"), nullable=False)
    
    # Relación con pago
    payment_id = Column(Integer, ForeignKey("payments.id"), nullable=False, unique=True)
    
    # Tipo de comprobante
    tipo = Column(String(2), nullable=False)  # '01' = Factura, '03' = Boleta
    serie = Column(String(4), nullable=False)  # B001, F001
    numero = Column(Integer, nullable=False)
    
    # Datos del comprobante
    fecha_emision = Column(DateTime(timezone=True), server_default=func.now())
    fecha_vencimiento = Column(DateTime(timezone=True), nullable=True)
    moneda = Column(String(3), default="PEN")  # PEN, USD
    
    # Importes
    subtotal = Column(Float, nullable=False)
    igv = Column(Float, default=0)  # 0 para exonerados
    total = Column(Float, nullable=False)
    
    # Cliente (del colegiado o pagador tercero)
    cliente_tipo_doc = Column(String(1), nullable=False)  # '1' = DNI, '6' = RUC
    cliente_num_doc = Column(String(15), nullable=False)
    cliente_nombre = Column(String(255), nullable=False)
    cliente_direccion = Column(String(255), nullable=True)
    cliente_email = Column(String(100), nullable=True)
    
    # Items del comprobante (JSON)
    items = Column(JSON, default=list)
    # Ejemplo: [{"descripcion": "Cuota Feb 2025", "cantidad": 1, "precio": 80.00}]
    
    # Respuesta de SUNAT
    sunat_response_code = Column(String(10), nullable=True)  # '0' = Aceptado
    sunat_response_description = Column(Text, nullable=True)
    sunat_hash = Column(String(100), nullable=True)  # Hash del CDR
    
    # Archivos generados
    xml_url = Column(String(500), nullable=True)
    pdf_url = Column(String(500), nullable=True)
    cdr_url = Column(String(500), nullable=True)  # Constancia de Recepción
    
    # Estado
    status = Column(String(20), default="pending")  
    # pending, sent, accepted, rejected, voided
    
    # Integración con facturalo.pro
    facturalo_id = Column(String(50), nullable=True)  # ID en facturalo.pro
    facturalo_response = Column(JSON, nullable=True)  # Respuesta completa
    
    # Notas
    observaciones = Column(Text, nullable=True)
    
    # Auditoría
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())
    created_by = Column(Integer, ForeignKey("members.id"), nullable=True)
    
    # Relaciones
    payment = relationship("Payment", backref="comprobante")
    organization = relationship("Organization")


class ConfiguracionFacturacion(Base):
    """
    Configuración de facturación electrónica por organización
    """
    __tablename__ = "configuracion_facturacion"
    
    id = Column(Integer, primary_key=True)
    organization_id = Column(Integer, ForeignKey("organizations.id"), unique=True)
    
    # Datos del emisor
    ruc = Column(String(11), nullable=False)
    razon_social = Column(String(255), nullable=False)
    nombre_comercial = Column(String(255), nullable=True)
    direccion = Column(String(255), nullable=True)
    ubigeo = Column(String(6), nullable=True)  # Código UBIGEO
    
    # Series
    serie_boleta = Column(String(4), default="B001")
    serie_factura = Column(String(4), default="F001")
    
    # Correlativos actuales
    ultimo_numero_boleta = Column(Integer, default=0)
    ultimo_numero_factura = Column(Integer, default=0)
    
    # Conexión con facturalo.pro
    facturalo_url = Column(String(255), default="https://facturalo.pro/api/v1")
    facturalo_token = Column(String(255), nullable=True)  # API Token
    facturalo_empresa_id = Column(String(50), nullable=True)  # ID de empresa en facturalo
    
    # Configuración
    emitir_automatico = Column(Boolean, default=True)  # Emitir al aprobar pago
    tipo_afectacion_igv = Column(String(2), default="20")  # '10' = Gravado, '20' = Exonerado
    porcentaje_igv = Column(Float, default=0)  # 0 para exonerados, 18 para gravados
    
    # Activo
    activo = Column(Boolean, default=True)
    
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())
    
    # Relación
    organization = relationship("Organization")


# ============================================================
# SQL para crear las tablas
# ============================================================
"""
-- Tabla de comprobantes electrónicos
CREATE TABLE comprobantes (
    id SERIAL PRIMARY KEY,
    organization_id INTEGER REFERENCES organizations(id) NOT NULL,
    payment_id INTEGER REFERENCES payments(id) NOT NULL UNIQUE,
    
    tipo VARCHAR(2) NOT NULL,
    serie VARCHAR(4) NOT NULL,
    numero INTEGER NOT NULL,
    
    fecha_emision TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    fecha_vencimiento TIMESTAMP WITH TIME ZONE,
    moneda VARCHAR(3) DEFAULT 'PEN',
    
    subtotal FLOAT NOT NULL,
    igv FLOAT DEFAULT 0,
    total FLOAT NOT NULL,
    
    cliente_tipo_doc VARCHAR(1) NOT NULL,
    cliente_num_doc VARCHAR(15) NOT NULL,
    cliente_nombre VARCHAR(255) NOT NULL,
    cliente_direccion VARCHAR(255),
    cliente_email VARCHAR(100),
    
    items JSONB DEFAULT '[]',
    
    sunat_response_code VARCHAR(10),
    sunat_response_description TEXT,
    sunat_hash VARCHAR(100),
    
    xml_url VARCHAR(500),
    pdf_url VARCHAR(500),
    cdr_url VARCHAR(500),
    
    status VARCHAR(20) DEFAULT 'pending',
    
    facturalo_id VARCHAR(50),
    facturalo_response JSONB,
    
    observaciones TEXT,
    
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE,
    created_by INTEGER REFERENCES members(id)
);

CREATE INDEX idx_comprobantes_org ON comprobantes(organization_id);
CREATE INDEX idx_comprobantes_payment ON comprobantes(payment_id);
CREATE INDEX idx_comprobantes_serie_num ON comprobantes(serie, numero);
CREATE INDEX idx_comprobantes_status ON comprobantes(status);

-- Tabla de configuración de facturación
CREATE TABLE configuracion_facturacion (
    id SERIAL PRIMARY KEY,
    organization_id INTEGER REFERENCES organizations(id) UNIQUE,
    
    ruc VARCHAR(11) NOT NULL,
    razon_social VARCHAR(255) NOT NULL,
    nombre_comercial VARCHAR(255),
    direccion VARCHAR(255),
    ubigeo VARCHAR(6),
    
    serie_boleta VARCHAR(4) DEFAULT 'B001',
    serie_factura VARCHAR(4) DEFAULT 'F001',
    
    ultimo_numero_boleta INTEGER DEFAULT 0,
    ultimo_numero_factura INTEGER DEFAULT 0,
    
    facturalo_url VARCHAR(255) DEFAULT 'https://facturalo.pro/api/v1',
    facturalo_token VARCHAR(255),
    facturalo_empresa_id VARCHAR(50),
    
    emitir_automatico BOOLEAN DEFAULT TRUE,
    tipo_afectacion_igv VARCHAR(2) DEFAULT '20',
    porcentaje_igv FLOAT DEFAULT 0,
    
    activo BOOLEAN DEFAULT TRUE,
    
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE
);
"""