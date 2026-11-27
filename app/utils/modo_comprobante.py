"""
app/utils/modo_comprobante.py — ÚNICO lugar donde se decide si un comprobante se EMITE de verdad
(Facturalo → SUNAT) o se SIMULA (numeración DEMO-000001 en su propia tabla, PDF «DEMOSTRACIÓN — SIN VALOR
TRIBUTARIO», cero llamadas a Facturalo/SUNAT).

Lo usa el pago de cuotas de plan desde Secretaría (tanda 19). No cambia Caja ni el resto de la facturación.

Regla (default SEGURO: ante cualquier duda, se SIMULA):
  1. ENVIRONMENT = sandbox o demo          → SIMULA siempre (aunque MODO_DEMO diga otra cosa).
  2. MODO_DEMO no definida                 → SIMULA.
  3. MODO_DEMO = true / 1 / sí / yes / on  → SIMULA.
  4. MODO_DEMO = false / 0 / no / off      → EMITE de verdad, pero SOLO si ENVIRONMENT = production.
                                             Con otro ENVIRONMENT (desarrollo, local, vacío) → SIMULA.
  5. Cualquier otro valor (ambiguo)        → SIMULA.
  EXCEPCIÓN (tanda 19c): con ENVIRONMENT = production y MODO_DEMO ausente o ambigua NO se simula ni se emite:
  queda BLOQUEADO y el pago con comprobante se rechaza con un mensaje claro (no se crea nada).

En producción hay que tener ENVIRONMENT=production y MODO_DEMO=false para emitir comprobantes reales.
Se lee en cada llamada (no al importar): cambiar la variable y reiniciar basta.
"""
import os

# Simulado: numeración claramente ficticia (DEMO-000001), en su propia tabla (comprobantes_simulados).
# NUNCA una serie con forma real (B…/F…): las series de prueba reales ante SUNAT (p. ej. 999) no se tocan.
PREFIJO_DEMO = "DEMO"
ROTULO_DEMO = "DEMOSTRACIÓN — SIN VALOR TRIBUTARIO"
_SI = {"true", "1", "si", "sí", "yes", "on"}
_NO = {"false", "0", "no", "off"}


MENSAJE_BLOQUEO = ("No se registró el pago: este servidor es de PRODUCCIÓN y no tiene definida la variable MODO_DEMO "
                   "(o tiene un valor no válido), así que no se sabe si debe emitir el comprobante real. "
                   "Avise al administrador para que ponga MODO_DEMO=false y reinicie.")


def modo_comprobante() -> dict:
    """{'real': bool, 'bloqueado': bool, 'motivo': str}.
    'real' solo es True en producción con MODO_DEMO=false explícito.
    'bloqueado' (tanda 19c) es True en producción con MODO_DEMO ausente o ambigua: ni se emite ni se simula,
    el pago con comprobante se RECHAZA (un comprobante simulado nunca debe llegar a un colegiado real)."""
    entorno = os.getenv("ENVIRONMENT", "").strip().lower()
    crudo = os.getenv("MODO_DEMO")
    v = (crudo or "").strip().lower()
    if entorno in ("sandbox", "demo"):
        return {"real": False, "bloqueado": False, "motivo": "ENVIRONMENT=%s: los comprobantes siempre se simulan" % entorno}
    if entorno == "production" and (crudo is None or v not in (_SI | _NO)):
        return {"real": False, "bloqueado": True, "motivo": MENSAJE_BLOQUEO}
    if crudo is None:
        return {"real": False, "bloqueado": False, "motivo": "MODO_DEMO no está definida: se simula por seguridad"}
    if v in _SI:
        return {"real": False, "bloqueado": False, "motivo": "MODO_DEMO=%s: se simula" % v}
    if v in _NO:
        if entorno != "production":
            return {"real": False, "bloqueado": False,
                    "motivo": "MODO_DEMO=%s pero ENVIRONMENT=%s: solo producción emite; se simula" % (v, entorno or "(vacío)")}
        return {"real": True, "bloqueado": False, "motivo": "Producción con MODO_DEMO=%s: se emite el comprobante real" % v}
    return {"real": False, "bloqueado": False, "motivo": "MODO_DEMO tiene un valor ambiguo: se simula por seguridad"}


def comprobante_real() -> bool:
    return modo_comprobante()["real"]
