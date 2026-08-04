from sqlalchemy import (
    Boolean,
    Column,
    DateTime,
    ForeignKey,
    Integer,
    Numeric,
    String,
    Text,
    BigInteger,
    func
)

from sqlalchemy.orm import relationship

from app.database import Base


class CredentialTemplate(Base):

    __tablename__ = "credential_templates"

    id = Column(BigInteger, primary_key=True)

    organization_id = Column(
        BigInteger,
        ForeignKey("organizations.id", ondelete="CASCADE"),
        nullable=False
    )

    nombre = Column(String(150), nullable=False)

    descripcion = Column(Text)

    activa = Column(Boolean, default=True)

    ancho_mm = Column(Numeric(6,2), default=85.60)

    alto_mm = Column(Numeric(6,2), default=53.98)

    fondo_frente_url = Column(Text)

    fondo_reverso_url = Column(Text)

    color_primario = Column(String(20))

    color_secundario = Column(String(20))

    microtexto = Column(String(200))

    patron_seguridad = Column(String(50))

    qr_habilitado = Column(Boolean, default=True)

    mostrar_anio = Column(Boolean, default=True)

    created_at = Column(DateTime, server_default=func.now())

    updated_at = Column(DateTime)



class CredentialIssuance(Base):

    __tablename__ = "credential_issuances"

    id = Column(BigInteger, primary_key=True)

    organization_id = Column(
        BigInteger,
        ForeignKey("organizations.id", ondelete="CASCADE"),
        nullable=False
    )

    template_id = Column(
        BigInteger,
        ForeignKey("credential_templates.id", ondelete="CASCADE"),
        nullable=False
    )

    colegiado_id = Column(
        BigInteger,
        ForeignKey("colegiados.id", ondelete="CASCADE"),
        nullable=False
    )

    version = Column(Integer, default=1)

    tipo_emision = Column(String(30), default="ORIGINAL")

    codigo_verificacion = Column(String(120), unique=True)

    qr_url = Column(Text)

    usuario_id = Column(BigInteger)

    observaciones = Column(Text)

    emitido_en = Column(DateTime, server_default=func.now())

    impreso = Column(Boolean, default=False)

    impreso_en = Column(DateTime)

    template = relationship("CredentialTemplate")