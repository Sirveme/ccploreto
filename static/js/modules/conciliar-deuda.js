/* Conciliar deuda — botón y modal de la ficha del colegiado (Secretaría).
   Solo aparece para los ROLES FIRMANTES (lo decide el servidor en /config).
   Flujo: monto fijado + motivo → vista previa → crear acta (cuenta como 1ª firma).
   Vanilla JS, sin alert/confirm/prompt nativos. Tema oscuro, sin blanco puro. */
(function () {
  "use strict";

  var API = "/api/conciliacion-deuda";
  var cfg = null;          // {firmas_requeridas, roles_firmantes, puedo_firmar}
  var col = null;          // colegiado de la ficha
  var previa = null;       // última vista previa válida

  function esc(s) {
    return String(s == null ? "" : s).replace(/[&<>"']/g, function (c) {
      return { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c];
    });
  }
  function soles(n) { return "S/ " + Number(n || 0).toLocaleString("es-PE", { minimumFractionDigits: 2, maximumFractionDigits: 2 }); }
  function $(id) { return document.getElementById(id); }
  var COND = { habil: "Hábil", inhabil: "Inhábil", vitalicio: "Vitalicio", suspendido: "Suspendido", fallecido: "Fallecido", retirado: "Retirado" };
  function cond(c) { return COND[c] || c || "—"; }

  function estilos() {
    if ($("cdx-css")) return;
    var s = document.createElement("style");
    s.id = "cdx-css";
    s.textContent =
      ".cdx-btn{display:none;font-size:11px;font-weight:600;color:#c7d2fe;background:rgba(99,102,241,.14);" +
      "border:1px solid rgba(99,102,241,.45);border-radius:6px;padding:4px 10px;margin-left:8px;cursor:pointer}" +
      ".cdx-btn:hover{background:rgba(99,102,241,.26)}" +
      ".cdx-fondo{display:none;position:fixed;inset:0;background:rgba(0,0,0,.66);z-index:10050;align-items:flex-start;justify-content:center;padding:28px 14px;overflow:auto}" +
      ".cdx-caja{background:#181a20;color:#e8e8ed;border:1px solid rgba(255,255,255,.1);border-radius:12px;max-width:640px;width:100%;padding:22px 24px;box-shadow:0 18px 50px rgba(0,0,0,.6)}" +
      ".cdx-caja h3{margin:0 0 2px;font-size:17px;color:#c7d2fe}" +
      ".cdx-sub{font-size:12px;color:#8b8d97;margin-bottom:14px}" +
      ".cdx-fila{display:flex;gap:12px;flex-wrap:wrap;margin-bottom:12px}" +
      ".cdx-dato{flex:1;min-width:150px;background:#1e2028;border:1px solid rgba(255,255,255,.06);border-radius:8px;padding:9px 12px}" +
      ".cdx-dato small{display:block;font-size:10.5px;color:#8b8d97;text-transform:uppercase;letter-spacing:.04em}" +
      ".cdx-dato b{font-size:16px;font-variant-numeric:tabular-nums}" +
      ".cdx-lbl{display:block;font-size:12px;color:#8b8d97;margin:10px 0 4px}" +
      ".cdx-in{width:100%;box-sizing:border-box;background:#0f1117;color:#e8e8ed;border:1px solid rgba(255,255,255,.14);border-radius:8px;padding:9px 11px;font-size:14px;font-family:inherit}" +
      ".cdx-in:focus{outline:none;border-color:#6366f1}" +
      ".cdx-prev{margin-top:14px;border:1px solid rgba(255,255,255,.08);border-radius:8px;overflow:hidden;display:none}" +
      ".cdx-prev table{width:100%;border-collapse:collapse;font-size:12.5px}" +
      ".cdx-prev th{background:#0f1117;color:#8b8d97;text-align:left;font-weight:600;font-size:10.5px;text-transform:uppercase;padding:7px 10px}" +
      ".cdx-prev td{padding:7px 10px;border-top:1px solid rgba(255,255,255,.05)}" +
      ".cdx-num{text-align:right;font-variant-numeric:tabular-nums;white-space:nowrap}" +
      ".cdx-res{padding:10px 12px;background:#1e2028;font-size:13px;line-height:1.6}" +
      ".cdx-aviso{margin-top:10px;padding:9px 12px;border-radius:8px;font-size:12.5px;display:none}" +
      ".cdx-aviso.err{display:block;background:rgba(239,68,68,.12);border:1px solid rgba(239,68,68,.4);color:#fca5a5}" +
      ".cdx-aviso.ok{display:block;background:rgba(52,211,153,.12);border:1px solid rgba(52,211,153,.4);color:#6ee7b7}" +
      ".cdx-aviso.warn{display:block;background:rgba(245,158,11,.12);border:1px solid rgba(245,158,11,.4);color:#fcd34d}" +
      ".cdx-pie{display:flex;justify-content:flex-end;gap:10px;margin-top:16px;flex-wrap:wrap}" +
      ".cdx-b{border:0;border-radius:8px;padding:9px 16px;font-size:13px;font-weight:600;cursor:pointer}" +
      ".cdx-b.sec{background:#1e2028;color:#c9cbd3;border:1px solid rgba(255,255,255,.1)}" +
      ".cdx-b.pri{background:#4f46e5;color:#eef2ff}" +
      ".cdx-b[disabled]{background:#2a2c35;color:#6b6d77;cursor:not-allowed}";
    document.head.appendChild(s);
  }

  function modal() {
    if ($("cdx-fondo")) return;
    var d = document.createElement("div");
    d.id = "cdx-fondo"; d.className = "cdx-fondo";
    d.innerHTML =
      '<div class="cdx-caja" role="dialog" aria-modal="true" aria-labelledby="cdx-titulo">' +
      '<h3 id="cdx-titulo">Conciliar deuda</h3>' +
      '<div class="cdx-sub" id="cdx-quien"></div>' +
      '<div class="cdx-fila">' +
      '<div class="cdx-dato"><small>Deuda actual</small><b id="cdx-actual">—</b></div>' +
      '<div class="cdx-dato"><small>Condición</small><b id="cdx-cond">—</b></div>' +
      '<div class="cdx-dato"><small>Firmas requeridas</small><b id="cdx-firmas">—</b></div>' +
      '</div>' +
      '<label class="cdx-lbl" for="cdx-monto">Deuda que debe quedar (S/)</label>' +
      '<input class="cdx-in" id="cdx-monto" type="number" min="0" step="0.01" inputmode="decimal">' +
      '<label class="cdx-lbl" for="cdx-motivo">Motivo (obligatorio: qué sustenta este monto)</label>' +
      '<textarea class="cdx-in" id="cdx-motivo" rows="3" maxlength="1000" placeholder="Ej.: Ficha física y vouchers revisados con el colegiado el ..."></textarea>' +
      '<div class="cdx-prev" id="cdx-prev"></div>' +
      '<div class="cdx-aviso" id="cdx-aviso"></div>' +
      '<div class="cdx-pie">' +
      '<button class="cdx-b sec" id="cdx-cerrar" type="button">Cerrar</button>' +
      '<button class="cdx-b sec" id="cdx-ver" type="button">Ver vista previa</button>' +
      '<button class="cdx-b pri" id="cdx-crear" type="button" disabled>Crear acta y firmar</button>' +
      '</div></div>';
    document.body.appendChild(d);
    $("cdx-cerrar").onclick = cerrar;
    $("cdx-ver").onclick = verPrevia;
    $("cdx-crear").onclick = crear;
    $("cdx-monto").oninput = invalidar;
    d.addEventListener("click", function (e) { if (e.target === d) cerrar(); });
    document.addEventListener("keydown", function (e) { if (e.key === "Escape" && d.style.display === "flex") cerrar(); });
  }

  function aviso(tipo, texto) {
    var a = $("cdx-aviso");
    a.className = "cdx-aviso" + (tipo ? " " + tipo : "");
    a.textContent = texto || "";
  }
  function invalidar() { previa = null; $("cdx-crear").disabled = true; $("cdx-prev").style.display = "none"; aviso("", ""); }
  function cerrar() { $("cdx-fondo").style.display = "none"; }

  function pedir(url, opciones) {
    return fetch(url, Object.assign({ credentials: "same-origin" }, opciones || {}))
      .then(function (r) {
        return r.json().catch(function () { return {}; }).then(function (j) { return { ok: r.ok, estado: r.status, j: j }; });
      });
  }

  function abrir(c) {
    if (!c || !c.id) return;
    col = c; previa = null;
    estilos(); modal();
    $("cdx-quien").textContent = (c.apellidos_nombres || "") + (c.codigo_matricula ? " · Mat. " + c.codigo_matricula : "");
    $("cdx-monto").value = ""; $("cdx-motivo").value = "";
    $("cdx-prev").style.display = "none"; $("cdx-crear").disabled = true; aviso("", "");
    $("cdx-actual").textContent = "…"; $("cdx-cond").textContent = cond(c.condicion);
    $("cdx-firmas").textContent = cfg ? cfg.firmas_requeridas : "—";
    $("cdx-ver").disabled = false;
    $("cdx-fondo").style.display = "flex";
    pedir(API + "/deuda/" + c.id).then(function (res) {
      if (!res.ok) { aviso("err", res.j.detail || "No se pudo leer la deuda."); return; }
      $("cdx-actual").textContent = soles(res.j.deuda_total);
      $("cdx-cond").textContent = cond(res.j.condicion);
      if (res.j.tiene_plan_activo) {
        aviso("warn", "Este colegiado tiene un plan de fraccionamiento activo. La conciliación con plan activo todavía no está disponible.");
        $("cdx-ver").disabled = true;
      } else { $("cdx-monto").focus(); }
    });
  }

  function verPrevia() {
    var monto = parseFloat($("cdx-monto").value);
    if (isNaN(monto) || monto < 0) { aviso("err", "Escribe el monto en que debe quedar la deuda (0 o más)."); return; }
    aviso("", "");
    pedir(API + "/preview?colegiado_id=" + col.id + "&monto_fijado=" + encodeURIComponent(monto)).then(function (res) {
      if (!res.ok) { invalidar(); aviso("err", res.j.detail || "No se pudo calcular la vista previa."); return; }
      previa = res.j;
      var filas = (previa.deudas || []).map(function (d) {
        var accion = d.accion === "anulada" ? "Se anula" : d.accion === "saldo_reducido" ? "Se reduce el saldo" : "Se crea";
        return "<tr><td>" + esc(d.concepto || "") + (d.periodo ? ' <span style="color:#8b8d97">' + esc(d.periodo) + "</span>" : "") + "</td>" +
          "<td>" + accion + "</td><td class='cdx-num'>" + soles(d.saldo_antes) + "</td><td class='cdx-num'>" + soles(d.saldo_despues) + "</td></tr>";
      }).join("");
      var cambio = previa.cambia_condicion
        ? "<b style='color:#fcd34d'>" + esc(cond(previa.condicion_antes)) + " → " + esc(cond(previa.condicion_despues)) + "</b>"
        : esc(cond(previa.condicion_despues)) + " (sin cambio)";
      $("cdx-prev").innerHTML =
        "<table><thead><tr><th>Deuda</th><th>Qué pasa</th><th class='cdx-num'>Saldo hoy</th><th class='cdx-num'>Queda</th></tr></thead><tbody>" +
        (filas || "<tr><td colspan='4' style='color:#8b8d97'>Sin deudas que tocar.</td></tr>") + "</tbody></table>" +
        "<div class='cdx-res'>Deuda total: <b>" + soles(previa.deuda_actual) + "</b> → <b>" + soles(previa.deuda_despues) + "</b> (" +
        (previa.sentido === "baja" ? "baja " : "sube ") + soles(Math.abs(previa.diferencia)) + ")<br>Condición: " + cambio +
        "<br><span style='color:#8b8d97'>No se toca ningún pago ni comprobante. " +
        (previa.firmas_requeridas > 1
          ? "El ajuste se aplica cuando firmen " + previa.firmas_requeridas + " personas de roles distintos; tu firma es la primera."
          : "Con una sola firma requerida, el ajuste se aplica al crear el acta.") + "</span></div>";
      $("cdx-prev").style.display = "block";
      $("cdx-crear").disabled = false;
    });
  }

  function crear() {
    if (!previa) return;
    var motivo = $("cdx-motivo").value.trim();
    if (motivo.length < 10) { aviso("err", "Escribe el motivo (mínimo 10 caracteres)."); $("cdx-motivo").focus(); return; }
    var btn = $("cdx-crear"); btn.disabled = true;
    pedir(API + "/actas", {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ colegiado_id: col.id, monto_fijado: previa.monto_fijado, motivo: motivo })
    }).then(function (res) {
      if (!res.ok) { btn.disabled = false; aviso("err", res.j.detail || "No se pudo crear el acta."); return; }
      aviso(res.j.estado === "desactualizada" ? "warn" : "ok", res.j.mensaje || "Acta creada.");
      $("cdx-ver").disabled = true;
      if (res.j.estado === "ejecutada") {
        // refrescar la ficha si la pantalla lo permite
        try { if (typeof window.cargarDeudas === "function") window.cargarDeudas(col.id); } catch (e) { /* sin ficha que refrescar */ }
        try { if (typeof window.actualizarBadgeColegiado === "function" && res.j.condicion_despues) window.actualizarBadgeColegiado(res.j.condicion_despues, col.habilidad_vence); } catch (e) { /* idem */ }
      }
    }).catch(function () { btn.disabled = false; aviso("err", "Error de red. Intenta de nuevo."); });
  }

  // Muestra el botón solo si el servidor dice que este usuario es firmante.
  function iniciar() {
    pedir(API + "/config").then(function (res) {
      if (!res.ok || !res.j.puedo_firmar) return;
      cfg = res.j;
      estilos();
      var b = $("btnConciliarDeuda");
      if (b) {
        b.classList.add("cdx-btn"); b.style.display = "inline-block";
        b.onclick = function () { abrir(window.ConciliarDeuda.colegiado()); };
      }
      var l = $("linkActasConciliacion");
      if (l) l.style.display = "inline-block";
    }).catch(function () { /* sin permiso o sin red: el botón queda oculto */ });
  }

  window.ConciliarDeuda = {
    abrir: abrir,
    // la pantalla anfitriona puede redefinir de dónde sale el colegiado
    colegiado: function () { try { return colegiadoActual; } catch (e) { return null; } } // eslint-disable-line no-undef
  };
  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", iniciar); else iniciar();
})();
