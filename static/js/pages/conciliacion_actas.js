/* Bandeja "Actas pendientes de firma" (roles firmantes de conciliación).
   Lectura: GET /api/conciliacion-deuda/actas?estado=...   Firma: POST .../actas/{id}/firmar
   Vanilla JS, sin alert/confirm/prompt nativos. */
(function () {
  "use strict";
  var API = "/api/conciliacion-deuda";
  var estado = "pendiente";
  var COND = { habil: "Hábil", inhabil: "Inhábil", vitalicio: "Vitalicio", suspendido: "Suspendido", fallecido: "Fallecido", retirado: "Retirado" };

  function esc(s) {
    return String(s == null ? "" : s).replace(/[&<>"']/g, function (c) {
      return { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c];
    });
  }
  function soles(n) { return "S/ " + Number(n || 0).toLocaleString("es-PE", { minimumFractionDigits: 2, maximumFractionDigits: 2 }); }
  function cond(c) { return COND[c] || c || "—"; }
  function toast(msg, tipo) {
    var t = document.getElementById("toast");
    t.textContent = msg; t.className = tipo || ""; t.style.display = "block";
    clearTimeout(t._t); t._t = setTimeout(function () { t.style.display = "none"; }, tipo === "err" ? 6000 : 3500);
  }

  function tarjeta(a) {
    var filas = (a.detalle || []).map(function (d) {
      var accion = d.accion === "anulada" ? "Se anula" : d.accion === "saldo_reducido" ? "Se reduce el saldo" : "Se crea";
      return "<tr><td>" + esc(d.concepto || "") + (d.periodo ? ' <span style="color:var(--text-sec)">' + esc(d.periodo) + "</span>" : "") +
        "</td><td>" + accion + "</td><td class='n'>" + soles(d.saldo_antes) + "</td><td class='n'>" + soles(d.saldo_despues) + "</td></tr>";
    }).join("");
    var firmas = (a.firmas || []).map(function (f) {
      return "<div class='firma'><span class='" + (f.decision === "aprobar" ? "si'>✓" : "no'>✕") + "</span> <b>" + esc(f.rol) + "</b> · " +
        esc(f.nombre) + " · " + esc(f.fecha || "") + (f.comentario ? " — " + esc(f.comentario) : "") + "</div>";
    }).join("");
    var condFinal = a.estado === "ejecutada" ? a.condicion_despues : a.condicion_prevista;
    var h = "<article class='acta' data-id='" + a.id + "'>" +
      "<div class='acta-top'><span class='num'>" + esc(a.numero) + "</span><span class='quien'>" + esc(a.colegiado || "") + "</span>" +
      "<span class='mat'>Mat. " + esc(a.matricula || "—") + " · " + esc(a.creada || "") + "</span>" +
      "<span class='chip " + esc(a.estado) + "'>" + esc(a.estado) + "</span></div>" +
      "<div class='montos'>" +
      "<div class='dato'><small>Deuda al proponer</small><b>" + soles(a.deuda_anterior) + "</b></div>" +
      "<div class='dato'><small>Deuda que queda</small><b>" + soles(a.monto_fijado) + "</b></div>" +
      "<div class='dato'><small>" + (a.sentido === "baja" ? "Baja" : "Sube") + "</small><b>" + soles(Math.abs(a.diferencia)) + "</b></div>" +
      "<div class='dato'><small>Condición</small><b>" + esc(cond(a.condicion_antes)) + " → " + esc(cond(condFinal)) + "</b></div>" +
      "<div class='dato'><small>Firmas</small><b>" + a.firmas_aprobadas + " de " + a.firmas_requeridas + "</b></div></div>" +
      "<div class='motivo'>" + esc(a.motivo) + "</div>" +
      "<details><summary>" + (a.estado === "ejecutada" ? "Deudas tocadas" : "Deudas que se tocarían") + " (" + (a.detalle || []).length + ")</summary>" +
      "<div class='tabla'><table><thead><tr><th>Deuda</th><th>Qué pasa</th><th class='n'>Saldo antes</th><th class='n'>Queda</th></tr></thead><tbody>" +
      (filas || "<tr><td colspan='4' style='color:var(--text-sec)'>Sin detalle.</td></tr>") + "</tbody></table></div></details>" +
      "<div class='firmas'>" + firmas + "</div>";
    if (a.motivo_cierre) h += "<div class='cierre'>" + esc(a.motivo_cierre) + "</div>";
    if (a.estado === "ejecutada") {
      h += "<div class='acciones'><a class='b pdf' href='" + API + "/actas/" + a.id + "/pdf' download>Descargar acta en PDF</a></div>";
    }
    if (a.estado === "pendiente") {
      if (a.puedo_firmar) {
        h += "<div class='acciones'><textarea rows='2' maxlength='500' placeholder='Comentario (obligatorio si rechazas)' aria-label='Comentario'></textarea>" +
          "<button class='b ok' data-decision='aprobar'>Firmar y aprobar</button>" +
          "<button class='b no' data-decision='rechazar'>Rechazar</button></div>" +
          "<div class='nota'>No se toca ningún pago ni comprobante. Si la deuda cambió desde que se propuso, el acta no se ejecuta.</div>";
      } else {
        h += "<div class='nota'>No puedes firmar esta acta: ya firmaste, o ya hay una firma de tu rol. Falta la firma de otra persona con otro rol (" +
          esc((a.roles_firmantes || []).join(", ")) + ").</div>";
      }
    }
    return h + "</article>";
  }

  function cargar() {
    var lista = document.getElementById("lista");
    fetch(API + "/actas?estado=" + encodeURIComponent(estado), { credentials: "same-origin" })
      .then(function (r) { return r.json().then(function (j) { return { ok: r.ok, j: j }; }); })
      .then(function (res) {
        if (!res.ok) { lista.innerHTML = "<div class='vacio'>" + esc(res.j.detail || "No se pudo cargar.") + "</div>"; return; }
        document.getElementById("regla").textContent =
          "Hoy se piden " + res.j.firmas_requeridas + " firma(s), de personas y roles distintos. Firman: " + (res.j.roles_firmantes || []).join(", ") + ".";
        var actas = res.j.actas || [];
        lista.innerHTML = actas.length ? actas.map(tarjeta).join("")
          : "<div class='vacio'>" + (estado === "pendiente" ? "No hay actas pendientes de firma." : "No hay actas en este estado.") + "</div>";
      })
      .catch(function () { lista.innerHTML = "<div class='vacio'>Error de red.</div>"; });
  }

  document.addEventListener("click", function (e) {
    var tab = e.target.closest(".tab");
    if (tab) {
      estado = tab.getAttribute("data-estado");
      Array.prototype.forEach.call(document.querySelectorAll(".tab"), function (t) { t.setAttribute("aria-selected", t === tab ? "true" : "false"); });
      cargar(); return;
    }
    var btn = e.target.closest("button[data-decision]");
    if (!btn) return;
    var art = btn.closest(".acta"), decision = btn.getAttribute("data-decision");
    var comentario = art.querySelector("textarea").value.trim();
    if (decision === "rechazar" && !comentario) { toast("Escribe por qué rechazas el acta.", "err"); art.querySelector("textarea").focus(); return; }
    // Segundo clic = confirmación (sin diálogos nativos)
    if (btn.getAttribute("data-confirmar") !== "1") {
      Array.prototype.forEach.call(art.querySelectorAll("button[data-decision]"), function (b) {
        b.removeAttribute("data-confirmar"); b.textContent = b.getAttribute("data-decision") === "aprobar" ? "Firmar y aprobar" : "Rechazar";
      });
      btn.setAttribute("data-confirmar", "1");
      btn.textContent = decision === "aprobar" ? "Confirmar firma" : "Confirmar rechazo";
      return;
    }
    Array.prototype.forEach.call(art.querySelectorAll("button"), function (b) { b.disabled = true; });
    fetch(API + "/actas/" + art.getAttribute("data-id") + "/firmar", {
      method: "POST", credentials: "same-origin", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ decision: decision, comentario: comentario || null })
    }).then(function (r) { return r.json().then(function (j) { return { ok: r.ok, j: j }; }); })
      .then(function (res) {
        if (!res.ok) { toast(res.j.detail || "No se pudo firmar.", "err"); Array.prototype.forEach.call(art.querySelectorAll("button"), function (b) { b.disabled = false; }); return; }
        toast(res.j.mensaje || "Listo.", res.j.estado === "desactualizada" ? "err" : "ok");
        cargar();
      })
      .catch(function () { toast("Error de red.", "err"); Array.prototype.forEach.call(art.querySelectorAll("button"), function (b) { b.disabled = false; }); });
  });

  cargar();
})();
