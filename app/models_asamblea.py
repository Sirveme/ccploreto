"""
app/models_asamblea.py
======================
Módulo mínimo de asistencia a asamblea (captura en mesa + lista pública).
Alcance estricto: solo asistencia. NO multas, NO justificaciones.
"""
from sqlalchemy import (
    Column, BigInteger, String, Text, DateTime, Date, ForeignKey, func
)
from sqlalchemy.dialects.postgresql import JSONB

from app.database import Base


class Asamblea(Base):
    __tablename__ = "asambleas"
    id = Column(BigInteger, primary_key=True)
    organization_id = Column(BigInteger, nullable=False)
    fecha = Column(Date, nullable=False)
    titulo = Column(String(200), nullable=False)
    agenda = Column(JSONB)                       # lista de puntos
    estado = Column(String(12), nullable=False, default="abierta")   # abierta | cerrada
    created_at = Column(DateTime, server_default=func.now())


class AsambleaAsistencia(Base):
    __tablename__ = "asamblea_asistencia"
    id = Column(BigInteger, primary_key=True)
    organization_id = Column(BigInteger, nullable=False)
    asamblea_id = Column(BigInteger, ForeignKey("asambleas.id", ondelete="CASCADE"), nullable=False)
    colegiado_id = Column(BigInteger, ForeignKey("colegiados.id"), nullable=False)
    hora_registro = Column(DateTime, server_default=func.now())
    registrado_por = Column(BigInteger)          # member.id de la operadora
    foto_url = Column(Text)                       # opcional, uso interno (nunca público)
