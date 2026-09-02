/* Panel de Parámetros del Sistema (Administrador) — sección Fraccionamiento primero.
   Lectura: GET /api/admin/parametros[/{seccion}]. Escritura: POST /api/admin/parametros.
   Historial: GET /api/admin/parametros/{seccion}/{clave}/historial.
   Auth por cookie (same-origin); vanilla JS; sin alert/confirm/prompt nativos. */
(function () {
  "use strict";

  var API = "/api/admin/parametros";
  var seccionActual = null;
  var pendiente = null; // {seccion, clave, valor, etiqueta, esBool, advertirPerdida}

  function esc(s) {
    return String(s == null ? "" : s).replace(/[&<>"']/g, function (c) {
      return { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c];
    });
  }

  function toast(msg, ok) {
    var t = document.getElementById("pxToast");
    t.textContent = msg;
    t.style.background = ok === false ? "#dc2626" : "#10b981";
    t.style.display = "block";
    clearTimeout(t._t);
    t._t = setTimeout(function () { t.style.display = "none"; }, ok === false ? 5000 : 3200);
  }

  function fmtValor(p) {
    if (p.tipo === "booleano") return p.valor ? "Sí" : "No";
    return p.valor;
  }

  // ── Carga inicial: secciones → selector ──
  function cargarSecciones() {
    fetch(API, { credentials: "same-origin" })
      .then(function (r) { return r.json(); })
      .then(function (d) {
        var sel = document.getElementById("selSeccion");
        sel.innerHTML = "";
        (d.secciones || []).forEach(function (s) {
          var o = document.createElement("option");
          o.value = s.seccion; o.textContent = s.etiqueta || s.seccion;
          sel.appendChild(o);
        });
        if (sel.options.length) { seccionActual = sel.value; cargarSeccion(seccionActual); }
        sel.onchange = function () { seccionActual = sel.value; cargarSeccion(seccionActual); };
      })
      .catch(function () { toast("No se pudieron cargar las secciones", false); });
  }

  // ── Carga de una sección → tabla ──
  function cargarSeccion(seccion) {
    fetch(API + "/" + encodeURIComponent(seccion), { credentials: "same-origin" })
      .then(function (r) { return r.json(); })
      .then(function (d) {
        document.getElementById("secEtiqueta").textContent = d.etiqueta || "";
        renderTabla(d.parametros || []);
      })
      .catch(function () { toast("No se pudo cargar la sección", false); });
  }

  function renderTabla(params) {
    var editables = params.filter(function (p) { return p.editable; });
    var fijos = params.filter(function (p) { return !p.editable; });
    var html = "";

    editables.forEach(function (p) { html += filaEditable(p); });

    if (fijos.length) {
      html += '<tr class="px-grp"><td colspan="5">No editables (informativos)</td></tr>';
      fijos.forEach(function (p) { html += filaFija(p); });
    }
    document.getElementById("tbodyParametros").innerHTML = html ||
      '<tr><td colspan="5" style="color:#94a3b8">Sin parámetros en esta sección.</td></tr>';
  }

  function filaEditable(p) {
    var id = "in_" + p.clave;
    var input;
    if (p.tipo === "booleano") {
      input = '<select class="px-in" id="' + id + '" data-orig="' + (p.valor ? "true" : "false") + '"' +
        ' onchange="pxOnChange(\'' + p.clave + '\')">' +
        '<option value="true"' + (p.valor ? " selected" : "") + '>Sí</option>' +
        '<option value="false"' + (!p.valor ? " selected" : "") + '>No</option></select>';
    } else {
      input = '<input class="px-in" id="' + id + '" type="number" step="any" value="' + esc(p.valor) +
        '" data-orig="' + esc(p.valor) + '" oninput="pxOnChange(\'' + p.clave + '\')">';
    }
    return '<tr data-clave="' + esc(p.clave) + '" data-tipo="' + p.tipo + '" data-etq="' + esc(p.etiqueta) + '">' +
      '<td>' + esc(p.etiqueta) + '</td>' +
      '<td>' + input + '</td>' +
      '<td class="px-unit">' + esc(p.unidad || "") + '</td>' +
      '<td><button class="px-btn px-btn-save" id="save_' + esc(p.clave) + '" disabled ' +
      'onclick="pxGuardar(\'' + p.clave + '\')">Guardar</button></td>' +
      '<td><button class="px-btn px-btn-hist" onclick="pxHistorial(\'' + esc(p.clave) + '\',\'' + esc(p.etiqueta) + '\')">Historial</button></td>' +
      '</tr>';
  }

  function filaFija(p) {
    return '<tr>' +
      '<td>' + esc(p.etiqueta) + '<div class="px-desc">' + esc(p.descripcion || "") + '</div></td>' +
      '<td class="px-ro">' + esc(fmtValor(p)) + '</td>' +
      '<td class="px-unit">' + esc(p.unidad || "") + '</td>' +
      '<td class="px-lock"><i class="ph ph-lock-simple"></i> no editable</td>' +
      '<td><button class="px-btn px-btn-hist" onclick="pxHistorial(\'' + esc(p.clave) + '\',\'' + esc(p.etiqueta) + '\')">Historial</button></td>' +
      '</tr>';
  }

  // ── Detectar cambio → habilitar Guardar ──
  window.pxOnChange = function (clave) {
    var el = document.getElementById("in_" + clave);
    var btn = document.getElementById("save_" + clave);
    var cambiado = String(el.value) !== String(el.getAttribute("data-orig"));
    btn.disabled = !cambiado;
  };

  // ── Guardar → abrir modal motivo (con aviso perdida_automatica) ──
  window.pxGuardar = function (clave) {
    var tr = document.querySelector('tr[data-clave="' + clave + '"]');
    var tipo = tr.getAttribute("data-tipo");
    var etq = tr.getAttribute("data-etq");
    var el = document.getElementById("in_" + clave);
    var esBool = tipo === "booleano";
    var valor = esBool ? (el.value === "true") : parseFloat(el.value);

    if (!esBool && isNaN(valor)) { toast("Valor no numérico", false); return; }

    pendiente = { seccion: seccionActual, clave: clave, valor: valor, etiqueta: etq, esBool: esBool };

    document.getElementById("motivoResumen").innerHTML =
      "<b>" + esc(etq) + "</b>: nuevo valor <b>" + esc(esBool ? (valor ? "Sí" : "No") : valor) + "</b>";

    var warn = document.getElementById("motivoWarn");
    if (seccionActual === "fraccionamiento" && clave === "perdida_automatica" && valor === true) {
      warn.innerHTML = "⚠️ El <b>ejecutor de pérdida automática aún no existe</b>. Activarlo " +
        "<b>no tendrá efecto</b> hasta construirlo (hoy la pérdida es manual). Puedes guardar igual.";
      warn.style.display = "block";
    } else {
      warn.style.display = "none";
    }
    document.getElementById("motivoTexto").value = "";
    document.getElementById("modalMotivo").style.display = "block";
  };

  window.pxCerrarMotivo = function () {
    document.getElementById("modalMotivo").style.display = "none";
    pendiente = null;
  };

  window.pxConfirmarGuardado = function () {
    if (!pendiente) return;
    var motivo = document.getElementById("motivoTexto").value.trim();
    var btn = document.getElementById("btnConfirmarMotivo");
    btn.disabled = true;
    fetch(API, {
      method: "POST",
      credentials: "same-origin",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        seccion: pendiente.seccion, clave: pendiente.clave,
        valor: pendiente.valor, motivo: motivo
      })
    })
      .then(function (r) { return r.json().then(function (j) { return { ok: r.ok, j: j }; }); })
      .then(function (res) {
        btn.disabled = false;
        if (!res.ok) { toast(res.j.detail || "No se pudo guardar", false); return; }
        document.getElementById("modalMotivo").style.display = "none";
        toast("Guardado. Versión #" + res.j.nuevo_id + " creada.", true);
        if (res.j.advertencia) { setTimeout(function () { toast(res.j.advertencia, false); }, 300); }
        var pend = pendiente; pendiente = null;
        cargarSeccion(pend.seccion); // refresca valores + deshabilita Guardar
      })
      .catch(function () { btn.disabled = false; toast("Error de red al guardar", false); });
  };

  // ── Historial ──
  window.pxHistorial = function (clave, etiqueta) {
    document.getElementById("histTitulo").textContent = "Historial · " + etiqueta;
    document.getElementById("tbodyHistorial").innerHTML =
      '<tr><td colspan="5" style="color:#94a3b8">Cargando…</td></tr>';
    document.getElementById("modalHistorial").style.display = "block";
    fetch(API + "/" + encodeURIComponent(seccionActual) + "/" + encodeURIComponent(clave) + "/historial",
      { credentials: "same-origin" })
      .then(function (r) { return r.json(); })
      .then(function (d) {
        var rows = (d.versiones || []).map(function (v) {
          var vig = esc(v.vigencia_desde || "?") + " → " + (v.vigencia_hasta ? esc(v.vigencia_hasta) : "<b>vigente</b>");
          return "<tr><td>" + vig + "</td><td>" + esc(v.valor) + "</td><td>" + esc(v.origen) +
            "</td><td>" + esc(v.cambio == null ? "—" : v.cambio) + "</td><td>" + esc(v.motivo || "") + "</td></tr>";
        }).join("");
        document.getElementById("tbodyHistorial").innerHTML = rows ||
          '<tr><td colspan="5" style="color:#94a3b8">Sin versiones.</td></tr>';
      })
      .catch(function () {
        document.getElementById("tbodyHistorial").innerHTML =
          '<tr><td colspan="5" style="color:#dc2626">No se pudo cargar el historial.</td></tr>';
      });
  };

  window.pxCerrarHistorial = function () {
    document.getElementById("modalHistorial").style.display = "none";
  };

  document.addEventListener("DOMContentLoaded", cargarSecciones);
})();
