/*
 * bingazo_panel.js — zClaude-95
 * Panel "🎯 Bingazo" para la ficha del colegiado en /caja + panel de activación.
 *
 * Uso (desde caja.js):
 *   1) Pestaña en ficha:
 *        BingazoPanel.montarFicha(colegiadoId, document.getElementById('tab-bingazo'));
 *   2) Botón de activación (admin/finanzas):
 *        BingazoPanel.mostrarActivacion();   // abre modal de configuración
 *
 * Endpoints consumidos (todos JSON):
 *   GET  /api/caja/bingazo/estado/{colegiadoId}
 *   POST /api/caja/bingazo/activar
 *   POST /api/caja/bingazo/asignacion/{id}/entregar
 *   POST /api/caja/bingazo/asignacion/{id}/pedir-adicionales
 *   POST /api/caja/bingazo/asignacion/{id}/devolver-adicionales
 *   POST /api/caja/bingazo/evento/{eventoId}/voluntario
 *
 * No usa alert/confirm/prompt nativos (regla global).
 */
(function (global) {
  "use strict";

  const API = "/api/caja/bingazo";

  // ── Utilidades ──────────────────────────────────────────────────
  const soles = (n) => "S/ " + (Number(n) || 0).toFixed(2);
  const esc = (s) =>
    String(s == null ? "" : s).replace(/[&<>"']/g, (c) =>
      ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c])
    );

  async function api(method, url, body) {
    const opts = { method, headers: { "Content-Type": "application/json" } };
    if (body !== undefined) opts.body = JSON.stringify(body);
    const r = await fetch(url, opts);
    let data = {};
    try { data = await r.json(); } catch (_) {}
    if (!r.ok) data.success = false;
    return data;
  }

  // Toast no nativo
  function toast(msg, tipo) {
    let host = document.getElementById("bingazo-toast-host");
    if (!host) {
      host = document.createElement("div");
      host.id = "bingazo-toast-host";
      host.style.cssText =
        "position:fixed;top:16px;right:16px;z-index:99999;display:flex;flex-direction:column;gap:8px;";
      document.body.appendChild(host);
    }
    const el = document.createElement("div");
    const bg = tipo === "error" ? "#dc2626" : tipo === "warn" ? "#d97706" : "#16a34a";
    el.style.cssText =
      `background:${bg};color:#fff;padding:10px 14px;border-radius:8px;` +
      "font:14px/1.4 system-ui;box-shadow:0 4px 12px rgba(0,0,0,.2);max-width:340px;";
    el.textContent = msg;
    host.appendChild(el);
    setTimeout(() => el.remove(), 4200);
  }

  // Modal genérico no nativo. Devuelve Promise<obj|null>.
  function modal({ titulo, campos = [], okLabel = "Confirmar" }) {
    return new Promise((resolve) => {
      const ov = document.createElement("div");
      ov.style.cssText =
        "position:fixed;inset:0;background:rgba(0,0,0,.45);z-index:99998;" +
        "display:flex;align-items:center;justify-content:center;";
      const box = document.createElement("div");
      box.style.cssText =
        "background:#fff;border-radius:12px;padding:20px;min-width:320px;max-width:420px;" +
        "font:14px system-ui;box-shadow:0 10px 40px rgba(0,0,0,.3);";
      box.innerHTML =
        `<h3 style="margin:0 0 14px;font-size:17px;">${esc(titulo)}</h3>` +
        campos
          .map(
            (c) =>
              `<label style="display:block;margin-bottom:10px;">` +
              `<span style="display:block;color:#374151;margin-bottom:4px;">${esc(c.label)}</span>` +
              `<input data-k="${esc(c.key)}" type="${c.type || "text"}" ` +
              `value="${esc(c.value != null ? c.value : "")}" ` +
              `${c.min != null ? `min="${c.min}"` : ""} ${c.max != null ? `max="${c.max}"` : ""} ` +
              `${c.step != null ? `step="${c.step}"` : ""} ` +
              `style="width:100%;padding:8px;border:1px solid #d1d5db;border-radius:6px;box-sizing:border-box;"/>` +
              `</label>`
          )
          .join("") +
        `<div style="display:flex;gap:8px;justify-content:flex-end;margin-top:16px;">` +
        `<button data-act="cancel" style="padding:8px 14px;border:1px solid #d1d5db;background:#fff;border-radius:6px;cursor:pointer;">Cancelar</button>` +
        `<button data-act="ok" style="padding:8px 14px;border:0;background:#16a34a;color:#fff;border-radius:6px;cursor:pointer;">${esc(okLabel)}</button>` +
        `</div>`;
      ov.appendChild(box);
      document.body.appendChild(ov);

      const cerrar = (val) => { ov.remove(); resolve(val); };
      box.querySelector('[data-act="cancel"]').onclick = () => cerrar(null);
      ov.onclick = (e) => { if (e.target === ov) cerrar(null); };
      box.querySelector('[data-act="ok"]').onclick = () => {
        const out = {};
        box.querySelectorAll("input[data-k]").forEach((i) => (out[i.dataset.k] = i.value));
        cerrar(out);
      };
    });
  }

  // ── Render de la ficha ──────────────────────────────────────────
  function renderFicha(estado, colegiadoId, container) {
    if (!estado || estado.success === false) {
      container.innerHTML =
        `<div style="padding:16px;color:#6b7280;">` +
        `${esc((estado && estado.error) || "Sin Bingazo activado este año.")}</div>`;
      return;
    }

    const ev = estado.evento;
    const asig = estado.asignacion;
    const dO = estado.deuda_obligatorios;
    const dA = estado.deuda_adicionales;

    // Vitalicio sin asignación: ofrecer asignación voluntaria
    if (!estado.tiene_asignacion && estado.es_vitalicio) {
      container.innerHTML =
        `<div style="border:1px solid #e5e7eb;border-radius:10px;overflow:hidden;font:14px system-ui;">` +
        `<div style="background:#7c3aed;color:#fff;padding:12px 14px;font-weight:600;">🎯 BINGAZO ${ev.año} · Vitalicio</div>` +
        `<div style="padding:14px;">` +
        `<p style="margin:0 0 10px;color:#374151;">Los vitalicios están exceptuados. Puede solicitar cartones de forma voluntaria.</p>` +
        `<button id="bz-voluntario" style="padding:8px 14px;border:0;background:#7c3aed;color:#fff;border-radius:6px;cursor:pointer;">Asignar cartones (voluntario)</button>` +
        `</div></div>`;
      container.querySelector("#bz-voluntario").onclick = async () => {
        const r = await modal({
          titulo: `Cartones voluntarios — Bingazo ${ev.año}`,
          campos: [
            { key: "cartones", label: "Cantidad de cartones", type: "number", min: 1, value: 1 },
            { key: "rango", label: "Rango (opcional)", type: "text" },
          ],
        });
        if (!r) return;
        const res = await api("POST", `${API}/evento/${ev.id}/voluntario`, {
          colegiado_id: colegiadoId,
          cartones: parseInt(r.cartones, 10) || 0,
          rango: r.rango || "",
        });
        if (res.success) { toast("Cartones asignados al vitalicio."); montarFicha(colegiadoId, container, ev.año); }
        else toast(res.error || "No se pudo asignar.", "error");
      };
      return;
    }

    const vendidos = asig ? asig.cartones_adicionales_vendidos : 0;

    container.innerHTML =
      `<div style="border:1px solid #e5e7eb;border-radius:10px;overflow:hidden;font:14px system-ui;">` +
      `<div style="background:#0e7490;color:#fff;padding:12px 14px;">` +
      `<div style="font-weight:600;font-size:15px;">🎯 BINGAZO ${ev.año}</div>` +
      `<div style="font-size:12px;opacity:.9;">Vence: ${esc(ev.fecha_limite)} · Precio: ${soles(ev.precio_unitario)} · Mínimo: ${ev.min_cartones} cartones · Comisión adic.: ${ev.comision_pct}%</div>` +
      `</div>` +

      // Obligatorios
      `<div style="padding:14px;border-bottom:1px solid #f3f4f6;">` +
      `<div style="display:flex;justify-content:space-between;font-weight:600;">` +
      `<span>Obligatorios (${ev.min_cartones})</span><span>${dO ? soles(dO.monto) : "—"}</span></div>` +
      `<div style="margin:10px 0;display:flex;align-items:center;gap:8px;flex-wrap:wrap;">` +
      `<label style="display:flex;align-items:center;gap:6px;"><input type="checkbox" id="bz-entreg" ${asig && asig.cartones_obligatorios_entregados ? "checked" : ""}/> Entregados</label>` +
      `<input id="bz-rango-oblig" type="text" placeholder="Rango ej: 00120-00134" value="${esc(asig ? asig.cartones_obligatorios_rango : "")}" style="flex:1;min-width:140px;padding:6px;border:1px solid #d1d5db;border-radius:6px;"/>` +
      `<button id="bz-confirm-oblig" style="padding:6px 12px;border:0;background:#0e7490;color:#fff;border-radius:6px;cursor:pointer;">✓ Confirmar</button>` +
      `</div>` +
      `<div style="font-size:12px;color:#6b7280;">Estado deuda: ${dO ? esc(dO.status) : "—"} · Saldo: ${dO ? soles(dO.balance) : "—"}</div>` +
      `</div>` +

      // Adicionales
      `<div style="padding:14px;">` +
      `<div style="font-weight:600;margin-bottom:6px;">Adicionales</div>` +
      `<div style="font-size:13px;color:#374151;margin-bottom:10px;">Pedidos: ${asig ? asig.cartones_adicionales_pedidos : 0} · Devueltos: ${asig ? asig.cartones_adicionales_devueltos : 0} · Vendidos: ${vendidos}${dA ? " · Deuda: " + soles(dA.balance) : ""}</div>` +
      `<div style="display:flex;gap:8px;flex-wrap:wrap;">` +
      `<button id="bz-pedir" style="padding:8px 12px;border:0;background:#16a34a;color:#fff;border-radius:6px;cursor:pointer;">+ Pedir adicionales</button>` +
      `<button id="bz-devolver" style="padding:8px 12px;border:1px solid #d1d5db;background:#fff;border-radius:6px;cursor:pointer;">↩ Devolver adicionales</button>` +
      `</div></div>` +
      `</div>`;

    // Bindings
    container.querySelector("#bz-confirm-oblig").onclick = async () => {
      if (!asig) return;
      const res = await api("POST", `${API}/asignacion/${asig.id}/entregar`, {
        rango: container.querySelector("#bz-rango-oblig").value || "",
        entregados: container.querySelector("#bz-entreg").checked,
      });
      if (res.success) { toast("Obligatorios actualizados."); montarFicha(colegiadoId, container, ev.año); }
      else toast(res.error || "Error al actualizar.", "error");
    };

    container.querySelector("#bz-pedir").onclick = async () => {
      if (!asig) return;
      const r = await modal({
        titulo: "Pedir cartones adicionales",
        campos: [
          { key: "cantidad", label: "Cantidad", type: "number", min: 1, value: 1 },
          { key: "rango", label: "Rango (opcional)", type: "text" },
        ],
      });
      if (!r) return;
      const res = await api("POST", `${API}/asignacion/${asig.id}/pedir-adicionales`, {
        cantidad: parseInt(r.cantidad, 10) || 0,
        rango: r.rango || "",
      });
      if (res.success) { toast(`Adicionales: ${res.total_pedidos} (${soles(res.monto_adicionales)}).`); montarFicha(colegiadoId, container, ev.año); }
      else toast(res.error || "No se pudo pedir.", "error");
    };

    container.querySelector("#bz-devolver").onclick = async () => {
      if (!asig) return;
      const maxDev = (asig.cartones_adicionales_pedidos || 0) - (asig.cartones_adicionales_devueltos || 0);
      if (maxDev <= 0) { toast("No hay adicionales para devolver.", "warn"); return; }
      const r = await modal({
        titulo: "Devolver cartones adicionales",
        campos: [{ key: "cantidad", label: `Cantidad (máx ${maxDev})`, type: "number", min: 1, max: maxDev, value: 1 }],
      });
      if (!r) return;
      const res = await api("POST", `${API}/asignacion/${asig.id}/devolver-adicionales`, {
        cantidad: parseInt(r.cantidad, 10) || 0,
      });
      if (res.success) { toast(`Devueltos: ${res.devueltos_total}. Nueva deuda: ${soles(res.nuevo_monto)}.`); montarFicha(colegiadoId, container, ev.año); }
      else toast(res.error || "No se pudo devolver.", "error");
    };
  }

  // ── API pública ─────────────────────────────────────────────────
  async function montarFicha(colegiadoId, container, año) {
    if (!container) return;
    container.innerHTML = `<div style="padding:16px;color:#6b7280;">Cargando Bingazo…</div>`;
    const url = `${API}/estado/${colegiadoId}` + (año ? `?año=${año}` : "");
    const estado = await api("GET", url);
    renderFicha(estado, colegiadoId, container);
  }

  async function mostrarActivacion() {
    const añoActual = new Date().getFullYear();
    const r = await modal({
      titulo: `Activar Bingazo ${añoActual}`,
      okLabel: "Activar",
      campos: [
        { key: "año", label: "Año", type: "number", value: añoActual, min: 2024 },
        { key: "precio_unitario", label: "Precio unitario (S/)", type: "number", step: "0.01", value: 12 },
        { key: "min_cartones", label: "Mínimo de cartones", type: "number", min: 1, value: 15 },
        { key: "comision_pct", label: "Comisión adicionales (%)", type: "number", step: "0.01", value: 12 },
        { key: "fecha_limite", label: "Fecha límite (exigibilidad)", type: "date", value: `${añoActual}-11-30` },
      ],
    });
    if (!r) return;
    if (!r.fecha_limite) { toast("Indica la fecha límite.", "warn"); return; }
    const res = await api("POST", `${API}/activar`, {
      año: parseInt(r.año, 10),
      precio_unitario: parseFloat(r.precio_unitario) || 0,
      min_cartones: parseInt(r.min_cartones, 10) || 15,
      comision_pct: parseFloat(r.comision_pct) || 0,
      fecha_limite: r.fecha_limite,
    });
    if (res.success) {
      toast(`✅ Bingazo ${r.año} activado: ${res.deudas_generadas} deudas por ${soles(res.monto_total)}.`);
    } else if (res.codigo === "YA_ACTIVADO") {
      toast(`El Bingazo ${r.año} ya estaba activado.`, "warn");
    } else {
      toast(res.error || "No se pudo activar.", "error");
    }
    return res;
  }

  global.BingazoPanel = { montarFicha, mostrarActivacion, toast };
})(window);
