"""
Servicio: Emisión automática de constancias de habilidad
=========================================================
Función reutilizable desde pagos o admin.
NO hace commit - el llamador controla la transacción.

Seguridad (ISO 27001):
- Código de verificación público: CERT-2026-00123 (correlativo)
- Código de seguridad privado: A3K2-M7NP-X9QR (se imprime en la constancia)
- Verificación: público + privado deben coincidir
- Esto impide falsificación: aunque alguien adivine el correlativo,
  no puede generar el código de seguridad aleatorio.
"""

from sqlalchemy.orm import Session
from sqlalchemy import text
from datetime import datetime, date, timedelta
from dateutil.relativedelta import relativedelta
import secrets

def generar_codigo_seguridad() -> str:
    """Genera código alfanumérico de 12 caracteres (3 grupos de 4).
    Excluye caracteres ambiguos: 0/O, 1/I/L."""
    caracteres = 'ABCDEFGHJKMNPQRSTUVWXYZ23456789'
    grupos = []
    for _ in range(3):
        grupo = ''.join(secrets.choice(caracteres) for _ in range(4))
        grupos.append(grupo)
    return '-'.join(grupos)


def calcular_vigencia(fecha_pago: date, en_fraccionamiento: bool = False) -> date:
    """
    Calcula fecha de vigencia de la constancia.
    
    - Normal (sin fraccionamiento): 3 meses desde la fecha de pago,
      hasta el último día del mes resultante.
    - Con fraccionamiento: 1 mes desde la fecha de pago,
      hasta el último día del mes resultante.
    """
    meses = 1 if en_fraccionamiento else 3
    fecha_fin = fecha_pago + relativedelta(months=meses)
    # Último día del mes
    primer_dia_sig = fecha_fin.replace(day=1) + relativedelta(months=1)
    ultimo_dia = primer_dia_sig - timedelta(days=1)
    return ultimo_dia


def separar_apellidos_nombres(apellidos_nombres: str) -> tuple:
    """
    Separa 'APELLIDO1 APELLIDO2, NOMBRES' en (nombres, apellidos).
    Si no hay coma, intenta dividir por espacios (2 primeras = apellidos).
    """
    if not apellidos_nombres:
        return ("", "")
    
    if "," in apellidos_nombres:
        partes = apellidos_nombres.split(",", 1)
        apellidos = partes[0].strip()
        nombres = partes[1].strip() if len(partes) > 1 else ""
    else:
        palabras = apellidos_nombres.strip().split()
        if len(palabras) >= 3:
            apellidos = " ".join(palabras[:2])
            nombres = " ".join(palabras[2:])
        elif len(palabras) == 2:
            apellidos = palabras[0]
            nombres = palabras[1]
        else:
            apellidos = apellidos_nombres
            nombres = ""
    
    return (nombres, apellidos)


def emitir_certificado_automatico(
    db: Session,
    colegiado_id: int,
    payment_id: int,
    ip_origen: str = None,
    emitido_por: int = None
) -> dict:
    """
    Emite constancia de habilidad después de pago aprobado.
    NO hace commit - el llamador controla la transacción.
    
    Vigencia:
    - Sin fraccionamiento: 3 meses
    - Con fraccionamiento activo: 1 mes
    """
    
    # 1. Datos del colegiado (incluir campos de fraccionamiento)
    colegiado = db.execute(
        text("""
            SELECT id, apellidos_nombres, codigo_matricula, condicion,
                   COALESCE(tiene_fraccionamiento, false) as tiene_fraccionamiento,
                   habilidad_vence
            FROM colegiados WHERE id = :cid
        """),
        {"cid": colegiado_id}
    ).fetchone()
    
    if not colegiado:
        print(f"⚠️ Constancia: colegiado {colegiado_id} no encontrado")
        return {"emitido": False, "error": "Colegiado no encontrado"}
    
    # 2. Solo emitir si está hábil
    if colegiado.condicion not in ('habil', 'vitalicio'):
        print(f"⚠️ Constancia: colegiado {colegiado_id} no hábil ({colegiado.condicion})")
        return {"emitido": False, "error": f"No hábil: {colegiado.condicion}"}
    
    # 3. Datos del pago
    pago = db.execute(
        text("SELECT id, created_at FROM payments WHERE id = :pid"),
        {"pid": payment_id}
    ).fetchone()
    
    if not pago:
        return {"emitido": False, "error": "Pago no encontrado"}
    
    # 4. Separar apellidos y nombres
    nombres, apellidos = separar_apellidos_nombres(colegiado.apellidos_nombres)
    
    # 5. Generar códigos
    codigo_correlativo = db.execute(
        text("SELECT generar_codigo_certificado()")
    ).fetchone()[0]
    codigo_seguridad = generar_codigo_seguridad()
    
    # 6. Calcular vigencia según fraccionamiento
    fecha_pago = pago.created_at.date() if hasattr(pago.created_at, 'date') else pago.created_at
    en_fraccionamiento = bool(colegiado.tiene_fraccionamiento)
    
    if en_fraccionamiento and colegiado.habilidad_vence:
        # Si tiene habilidad temporal, la constancia vence cuando vence la habilidad
        fecha_vigencia = colegiado.habilidad_vence.date() if hasattr(
            colegiado.habilidad_vence, 'date'
        ) else colegiado.habilidad_vence
    else:
        # Normal: 3 meses. Fraccionamiento sin habilidad_vence: 1 mes.
        fecha_vigencia = calcular_vigencia(fecha_pago, en_fraccionamiento)
    
    fecha_emision = datetime.now()
    
    # 7. Insertar constancia
    db.execute(
        text("""
            INSERT INTO certificados_emitidos (
                codigo_verificacion, codigo_seguridad, colegiado_id,
                nombres, apellidos, matricula,
                fecha_emision, fecha_vigencia_hasta,
                en_fraccionamiento, payment_id,
                emitido_por, ip_emision, estado
            ) VALUES (
                :codigo, :seguridad, :colegiado_id,
                :nombres, :apellidos, :matricula,
                :fecha_emision, :fecha_vigencia,
                :en_fraccionamiento, :payment_id,
                :emitido_por, :ip, 'vigente'
            )
        """),
        {
            "codigo": codigo_correlativo,
            "seguridad": codigo_seguridad,
            "colegiado_id": colegiado_id,
            "nombres": nombres,
            "apellidos": apellidos,
            "matricula": colegiado.codigo_matricula,
            "fecha_emision": fecha_emision,
            "fecha_vigencia": fecha_vigencia,
            "en_fraccionamiento": en_fraccionamiento,
            "payment_id": payment_id,
            "emitido_por": str(emitido_por) if emitido_por else "sistema",
            "ip": ip_origen
        }
    )
    
    vigencia_meses = "1 mes" if en_fraccionamiento else "3 meses"
    print(
        f"✅ Constancia emitida: {codigo_correlativo} → {colegiado.apellidos_nombres} "
        f"(vigencia: {vigencia_meses}, hasta {fecha_vigencia})"
    )
    
    return {
        "emitido": True,
        "codigo": codigo_correlativo,
        "codigo_seguridad": codigo_seguridad,
        "vigencia_hasta": fecha_vigencia.isoformat(),
        "vigencia_meses": vigencia_meses,
        "en_fraccionamiento": en_fraccionamiento,
        "nombre": colegiado.apellidos_nombres,
        # URL de verificación pública (con ambos códigos)
        "url_verificacion": f"/verificar/{codigo_correlativo}?s={codigo_seguridad}",
    }