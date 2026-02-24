# app/models/lote_operacion.py
from sqlalchemy import (
    Column, Integer, String, Boolean, Text, DateTime, Float,
    ForeignKey, Table, UniqueConstraint, Index, JSON
)
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func
from app.database import Base

class LoteOperacion(Base):
    """
    Agrupa un conjunto de operaciones de prueba/migración
    para poder revertirlas atómicamente.
    
    Estados:
      borrador   → en construcción, nada confirmado
      confirmado → operaciones aplicadas a la BD
      revertido  → rollback ejecutado, BD limpia
      produccion → sellado, NO revertible
    """
    __tablename__ = "lotes_operacion"

    id           = Column(Integer, primary_key=True, autoincrement=True)
    codigo       = Column(String(50), unique=True, nullable=False)
    # Ej: "IMPORT-2025-001", "PRUEBA-PAGOS-002", "VITALICIOS-2025-01"
    
    tipo         = Column(String(30), nullable=False)
    # migracion_cuotas | pago_prueba | fraccionamiento |
    # cambio_condicion | condonacion_multas | mixto
    
    descripcion  = Column(Text, nullable=True)
    estado       = Column(String(20), default='borrador')
    
    # Snapshot del estado ANTES (para rollback de campos no-tabla)
    snapshot_json = Column(JSON, nullable=True)
    # Almacena: [{"tabla":"colegiados","id":3416,"campo":"condicion",
    #             "valor_antes":"inhabil","valor_despues":"vitalicio"}, ...]
    
    created_by   = Column(Integer, ForeignKey("users.id"), nullable=True)
    created_at   = Column(DateTime(timezone=True), server_default=func.now())
    confirmado_at = Column(DateTime(timezone=True), nullable=True)
    revertido_at  = Column(DateTime(timezone=True), nullable=True)
    revertido_by  = Column(Integer, ForeignKey("users.id"), nullable=True)
    notas_rollback = Column(Text, nullable=True)