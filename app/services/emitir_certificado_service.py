"""
Servicio: Emisión automática de certificados
=============================================
Función reutilizable desde pagos o admin.
NO hace commit - el llamador controla la transacción.
"""

from sqlalchemy.orm import Session
from sqlalchemy import text
from datetime import datetime, date, timedelta
from dateutil.relativedelta import relativedelta
import secrets

def generar_codigo_seguridad() -> str:
    caracteres = 'ABCDEFGHJKMNPQRSTUVWXYZ23456789'
    grupos = []
    for _ in range(3):
        grupo = ''.join(secrets.choice(caracteres) for _ in range(4))
        grupos.append(grupo)
    return '-'.join(grupos)


def calcular_vigencia(fecha_pago: date, en_fraccionamiento: bool = False) -> date:
    meses = 1 if en_fraccionamiento else 3
    fecha_fin = fecha_pago + relativedelta(months=meses)
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
    Emite certificado automáticamente después de pago aprobado.
    NO hace commit - el llamador controla la transacción.
    """
    
    # 1. Datos del colegiado
    colegiado = db.execute(
        text("""
            SELECT id, apellidos_nombres, codigo_matricula, condicion
            FROM colegiados WHERE id = :cid
        """),
        {"cid": colegiado_id}
    ).fetchone()
    
    if not colegiado:
        print(f"⚠️ Certificado: colegiado {colegiado_id} no encontrado")
        return {"emitido": False, "error": "Colegiado no encontrado"}
    
    # 2. Solo emitir si está hábil
    if colegiado.condicion not in ('habil', 'vitalicio'):
        print(f"⚠️ Certificado: colegiado {colegiado_id} no hábil ({colegiado.condicion})")
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
    
    # 6. Calcular vigencia
    fecha_pago = pago.created_at.date() if hasattr(pago.created_at, 'date') else pago.created_at
    fecha_vigencia = calcular_vigencia(fecha_pago)
    fecha_emision = datetime.now()
    
    # 7. Insertar certificado
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
                FALSE, :payment_id,
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
            "payment_id": payment_id,
            "emitido_por": str(emitido_por) if emitido_por else "sistema",
            "ip": ip_origen
        }
    )
    
    print(f"✅ Certificado emitido: {codigo_correlativo} → {colegiado.apellidos_nombres}")
    
    return {
        "emitido": True,
        "codigo": codigo_correlativo,
        "codigo_seguridad": codigo_seguridad,
        "vigencia_hasta": fecha_vigencia.isoformat(),
        "nombre": colegiado.apellidos_nombres
    }