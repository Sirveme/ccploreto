"""
app/utils/cuotas_enteras.py — Planes NUEVOS sin céntimos (tanda 8, decisión de Duilio).

  - Inicial sugerida: ceil(deuda × %), en soles enteros (misma fórmula del 20% de siempre).
  - Cuotas mensuales: soles enteros redondeando HACIA ABAJO; la ÚLTIMA absorbe la diferencia.
      S/ 874 en 8 cuotas → 7 de S/ 109 y la última de S/ 111.
    Si el saldo trae céntimos (la deuda los tenía), solo la última los lleva.
  - Los planes existentes NO se recalculan: esto solo se usa al crear planes nuevos
    (fraccionar y refinanciar) y en simuladores/vistas previas.

Espejo en JavaScript (mismo cálculo) en caja.js, secretaria.html y portal_inactivo.js:
    regular = Math.floor(saldo / n);  ultima = round2(saldo - regular * (n - 1))
"""
import math


def inicial_sugerida(total, pct):
    """pct en fracción (0.20)."""
    return float(math.ceil(round(float(total) * float(pct), 6)))


def repartir(saldo, n):
    """Lista de n montos: n-1 iguales en soles enteros (hacia abajo) y la última con el resto."""
    n = int(n)
    if n <= 0:
        return []
    saldo = round(float(saldo), 2)
    regular = float(math.floor(round(saldo / n, 6)))
    ultima = round(saldo - regular * (n - 1), 2)
    return [regular] * (n - 1) + [ultima]


def cuota_regular(saldo, n):
    return repartir(saldo, n)[0] if n else 0.0


def texto_cuotas(montos):
    """'8 cuotas de S/ 109' o '7 cuotas de S/ 109 y la última de S/ 111'."""
    if not montos:
        return ""
    if len(montos) == 1 or montos[-1] == montos[0]:
        return "%d cuota%s de S/ %s" % (len(montos), "s" if len(montos) > 1 else "", _s(montos[0]))
    return "%d cuota%s de S/ %s y la última de S/ %s" % (
        len(montos) - 1, "s" if len(montos) > 2 else "", _s(montos[0]), _s(montos[-1]))


def _s(x):
    x = float(x)
    return ("{:,.0f}" if x == int(x) else "{:,.2f}").format(x)
