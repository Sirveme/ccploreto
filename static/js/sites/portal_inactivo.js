/* ══════════════════════════════════════════════════════════════
   portal_inactivo.js  — ColegiosPro · CCPL
   Módulos: Portal | Asistente | Modales | PWA
   Backend:
     GET  /api/portal/mi-perfil
     GET  /api/portal/mi-deuda
     POST /api/portal/asistente          { pregunta, ctx }
     POST /api/portal/asistente/audio    { audio, ctx }
     POST /api/portal/reportar-pago      { FormData }
     POST /api/portal/solicitar-fraccionamiento { ... }
══════════════════════════════════════════════════════════════ */

'use strict';

/* ────────────────────────────────────────────────────────────
   Utilidades
──────────────────────────────────────────────────────────── */
const fmt = n =>
  (parseFloat(n) || 0).toLocaleString('es-PE', { minimumFractionDigits: 2, maximumFractionDigits: 2 });

const hora = () =>
  new Date().toLocaleTimeString('es-PE', { hour: '2-digit', minute: '2-digit' });

const $ = id => document.getElementById(id);


/* ════════════════════════════════════════════════════════════
   PORTAL — carga de perfil y deuda
════════════════════════════════════════════════════════════ */
const Portal = {

  ctx: {
    nombre: '', primera: '', matricula: '',
    dni: '', condicion: '',
    deuda_total: 0, deuda_fraccionable: 0,
    deuda_condonable: 0, cuota_inicial_min: 0,
    deudas: [],
  },

  async init() {
    try {
      // Perfil
      const rp = await fetch('/api/portal/mi-perfil');
      if (rp.status === 401 || rp.status === 422) { location.href = '/'; return; }
      const perfil = await rp.json();

      const cond = (perfil.condicion || '').toLowerCase();
      if (cond === 'habil' || cond === 'vitalicio') { location.href = '/dashboard'; return; }

      // Extraer datos
      const nombre  = perfil.nombres || perfil.nombre_completo || perfil.nombre_corto || '—';
      const partes  = nombre.trim().split(/\s+/);
      const ini     = ((partes[0]?.[0] || '') + (partes[1]?.[0] || '')).toUpperCase() || '?';
      const primera = partes[0] || 'Colegiado';

      this.ctx.nombre    = nombre;
      this.ctx.primera   = primera;
      this.ctx.matricula = perfil.matricula || '';
      this.ctx.dni       = perfil.dni || '';
      this.ctx.condicion = cond;

      // DOM — panel desktop
      $('panel-av').textContent     = ini;
      $('panel-nombre').textContent = nombre;
      $('panel-mat').textContent    = 'Matrícula ' + (perfil.matricula || '—');
      $('topbar-org').textContent   = perfil.organizacion || 'Colegio de Contadores Públicos de Loreto';

      if (cond === 'retirado') {
        const b = $('panel-status');
        b.classList.replace('status-inhabil', 'status-retirado');
        $('panel-status-txt').textContent = 'RETIRADO';
      }

      // DOM — topbar mobile
      $('mob-av').textContent     = ini;
      $('mob-nombre').textContent = primera;
      $('pwa-nombre').textContent = primera;

      // Pre-llenar modales con DNI/matrícula
      const dniMat = (perfil.dni || '') + ' / ' + (perfil.matricula || '');
      if ($('rp-dni-mat')) $('rp-dni-mat').value = dniMat;

      // Cargar deuda
      await this.loadDeuda();

      // Saludo inicial del asistente
      Asistente.welcomeMsg();

    } catch(e) {
      console.error('[Portal.init]', e);
    }
  },

  async loadDeuda() {
    try {
      const rd = await fetch('/api/portal/mi-deuda');
      const d  = await rd.json();

      const total      = parseFloat(d.total      || 0);
      const condona    = parseFloat(d.condonable  || 0);
      const fraccio    = parseFloat(d.fraccionable || total);
      const cuotaMin   = Math.max(100, Math.ceil(fraccio * 0.20 / 10) * 10);
      const cant       = parseInt(d.cantidad || 0);

      this.ctx.deuda_total       = total;
      this.ctx.deuda_condonable  = condona;
      this.ctx.deuda_fraccionable= fraccio;
      this.ctx.cuota_inicial_min = cuotaMin;
      this.ctx.deudas            = d.deudas || [];
      // ── Aliases que espera el backend ──────────────
      this.ctx.deuda_real        = fraccio;   // ← AÑADIR
      this.ctx.condonable        = condona;   // ← AÑADIR

      // Panel desktop
      $('panel-deuda-total').textContent = fmt(total);
      $('panel-deuda-cnt').textContent   =
        cant + ' concepto' + (cant !== 1 ? 's' : '') + ' pendiente' + (cant !== 1 ? 's' : '');
      $('mob-deuda').textContent         = 'Deuda S/ ' + fmt(total);

      // Pills condonable / fraccionable
      const pillsEl = $('panel-pills');
      if (pillsEl) {
        pillsEl.innerHTML = '';
        if (fraccio >= 500) {
          pillsEl.insertAdjacentHTML('beforeend',
            `<span class="deuda-pill pill-fraccion">
               <span class="mi sm" style="color:var(--blue-soft)">calendar_month</span>
               Fraccionable S/ ${fmt(fraccio)}
             </span>`);
        }
        if (condona > 0) {
          pillsEl.insertAdjacentHTML('beforeend',
            `<span class="deuda-pill pill-condona">
               <span class="mi sm" style="color:var(--violet)">auto_awesome</span>
               Condonable S/ ${fmt(condona)}
             </span>`);
        }
      }

      // Chips contextuales del chat
      this._renderChips(total, cuotaMin, condona, fraccio);

      // Datos para modal pago en línea
      const plRef = $('pl-deuda-ref');
      if (plRef) plRef.textContent = 'S/ ' + fmt(total);

      Modales.fraccion._setDeuda(fraccio, cuotaMin);

    } catch(e) {
      console.error('[Portal.loadDeuda]', e);
    }
  },

  _renderChips(total, cuotaMin, condona, fraccio) {
    const el = $('ctx-chips');
    if (!el) return;
    el.innerHTML = '';

    const chips = [];
    if (total > 0)
      chips.push({ cls: 'chip-deuda',    icon: 'account_balance_wallet', label: `Debo S/ ${fmt(total)}`,      q: `¿Cuánto debo en total y en qué conceptos?` });
    if (fraccio >= 500)
      chips.push({ cls: 'chip-inicial',  icon: 'calendar_month',          label: `Inicial mín. S/ ${fmt(cuotaMin)}`, q: '¿Cómo funciona el fraccionamiento y cuánto sería mi cuota mensual?' });
    if (condona > 0)
      chips.push({ cls: 'chip-condona',  icon: 'auto_awesome',            label: `Me condonan S/ ${fmt(condona)}`,  q: '¿Qué deudas me condonan y cómo aplico a la condonación?' });
    chips.push({ cls: 'chip-benef',    icon: 'handshake',                label: 'Beneficios al reactivarme',       q: '¿Qué beneficios y descuentos recupero al reactivarme?' });
    chips.push({ cls: 'chip-reactiva', icon: 'bolt',                     label: 'Reactivarme hoy',                 q: '¿Cuál es la forma más rápida de reactivarme hoy?' });
    chips.push({ cls: 'chip-legal',    icon: 'gavel',                    label: 'Base legal',                      q: '¿Cuál es la base legal que explica mi condición?' });

    chips.forEach(c => {
      const btn = document.createElement('button');
      btn.className = `ctx-chip ${c.cls}`;
      btn.innerHTML = `<span class="mi sm">${c.icon}</span>${c.label}`;
      btn.onclick   = () => Asistente.ask(c.q);
      el.appendChild(btn);
    });
  },
};


/* ════════════════════════════════════════════════════════════
   ASISTENTE — chat de texto + grabación de voz
════════════════════════════════════════════════════════════ */
const Asistente = {

  usarWhisper: false,
  grabando:    false,
  mr:          null,
  audioCtx:    null,
  analyser:    null,
  rafId:       null,
  chunks:      [],

  activarWhisper() { this.usarWhisper = true; },

  /* ── Saludo inicial ──────────────────────────────────── */
  welcomeMsg() {
    const { primera, deuda_total, deuda_condonable } = Portal.ctx;
    let txt = `¡Hola, ${primera}! 👋 Soy el asistente del CCPL.`;
    if (deuda_total > 0) {
      txt += ` Veo que tienes una deuda de <strong>S/ ${fmt(deuda_total)}</strong>.`;
      if (deuda_condonable > 0)
        txt += ` De eso, <strong>S/ ${fmt(deuda_condonable)}</strong> pueden <strong>condonarse</strong> automáticamente al activar un fraccionamiento.`;
    }
    txt += '<br><br>¿En qué te puedo ayudar?';
    this._addMsg(txt, 'bot');
  },

  /* ── Chat texto ──────────────────────────────────────── */
  enviar() {
    const input = $('chat-input');
    const texto = input.value.trim();
    if (!texto) return;
    input.value = '';
    this._sendText(texto);
  },

  ask(texto) {
    // Ocultar chips tras primera pregunta
    const chips = $('ctx-chips');
    if (chips) chips.style.display = 'none';
    this._sendText(texto);
  },

  async _sendText(texto) {
    this._addMsg(texto, 'user');
    const typing = this._addTyping();
    $('btn-send').disabled = true;

    try {
      const fd = new FormData();
      fd.append('pregunta', texto);
      fd.append('ctx', JSON.stringify(Portal.ctx));

      const r = await fetch('/api/portal/asistente', { method: 'POST', body: fd });
      const d = await r.json();
      typing.remove();
      this._addMsg(d.respuesta || 'No pude responder en este momento.', 'bot');
      this._hablar(d.respuesta);

    } catch(e) {
      typing.remove();
      this._addMsg('Error de conexión. Intenta en unos segundos.', 'bot');
    } finally {
      $('btn-send').disabled = false;
    }
  },

  /* ── Voz ─────────────────────────────────────────────── */
  async toggleVoz() {
    if (this.grabando) { this.detenerGrabacion(); return; }
    await this._iniciarGrabacion();
  },

  async _iniciarGrabacion() {
    if (!this.usarWhisper) { this._webSpeechFallback(); return; }

    try {
      const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
      this.chunks  = [];

      const mime  = ['audio/webm;codecs=opus','audio/webm',''].find(m => !m || MediaRecorder.isTypeSupported(m));
      this.mr     = new MediaRecorder(stream, mime ? { mimeType: mime } : undefined);
      this.mr.ondataavailable = e => { if (e.data.size > 0) this.chunks.push(e.data); };
      this.mr.onstop          = ()  => this._procesarAudio(stream);
      this.mr.start(100);
      this.grabando = true;

      // AudioContext para el orbe
      try {
        this.audioCtx = new (window.AudioContext || window.webkitAudioContext)();
        const src     = this.audioCtx.createMediaStreamSource(stream);
        this.analyser = this.audioCtx.createAnalyser();
        this.analyser.fftSize = 128;
        src.connect(this.analyser);
      } catch(_) { this.analyser = null; }

      this._showOverlay(false);
      this._drawOrb();

      // UI botón
      $('btn-mic').classList.add('rec');
      $('mic-icon').textContent = 'stop_circle';

    } catch(e) {
      console.error('[Voz]', e);
      alert('No se pudo acceder al micrófono. Por favor permite el acceso en tu navegador.');
    }
  },

  detenerGrabacion() {
    if (!this.mr || !this.grabando) return;
    this.grabando = false;
    if (this.rafId) { cancelAnimationFrame(this.rafId); this.rafId = null; }
    this.mr.stop();
    $('voz-lbl').textContent  = 'Procesando...';
    $('voz-hint').textContent = 'Enviando al asistente IA';
    $('voz-ov').classList.add('proc');
    const stopBtn = document.querySelector('.btn-voz-stop');
    if (stopBtn) stopBtn.style.display = 'none';
    $('orb-icon').textContent = 'hourglass_empty';
    $('btn-mic').classList.remove('rec');
    $('mic-icon').textContent = 'mic';
  },

  async _procesarAudio(stream) {
    stream.getTracks().forEach(t => t.stop());
    if (this.audioCtx) { try { await this.audioCtx.close(); } catch(_) {} this.audioCtx = null; }
    this.analyser = null;

    const blob = new Blob(this.chunks, { type: 'audio/webm' });
    if (blob.size < 500) { this._hideOverlay(); return; }

    try {
      const fd = new FormData();
      fd.append('audio', blob, 'voz.webm');
      fd.append('ctx', JSON.stringify(Portal.ctx));

      const r = await fetch('/api/portal/asistente/audio', { method: 'POST', body: fd });
      const d = await r.json();

      this._hideOverlay();

      const chips = $('ctx-chips');
      if (chips) chips.style.display = 'none';

      if (d.transcripcion) this._addMsg(d.transcripcion, 'user');
      this._addMsg(d.respuesta || 'No pude procesar tu consulta.', 'bot');
      this._hablar(d.respuesta);

    } catch(e) {
      console.error('[Audio]', e);
      this._hideOverlay();
      this._addMsg('Error procesando el audio. Intenta de nuevo.', 'bot');
    }
  },

  _webSpeechFallback() {
    const SR = window.SpeechRecognition || window.webkitSpeechRecognition;
    if (!SR) { alert('Tu navegador no soporta reconocimiento de voz.'); return; }
    const sr = new SR();
    sr.lang     = 'es-PE';
    sr.onresult = e => {
      const t = e.results[0]?.[0]?.transcript.trim();
      if (t) { $('chat-input').value = t; this.enviar(); }
    };
    sr.onerror  = () => {};
    sr.start();
  },

  /* ── Orb canvas ──────────────────────────────────────── */
  _drawOrb() {
    const canvas = $('orb-canvas');
    const ctx2d  = canvas.getContext('2d');
    const W = canvas.width, H = canvas.height, CX = W/2, CY = H/2;

    const frame = () => {
      if (!this.grabando) return;
      this.rafId = requestAnimationFrame(frame);
      ctx2d.clearRect(0, 0, W, H);

      if (this.analyser) {
        const data = new Uint8Array(this.analyser.frequencyBinCount);
        this.analyser.getByteFrequencyData(data);
        const bars = 52, innerR = 42;
        for (let i = 0; i < bars; i++) {
          const angle  = (i / bars) * Math.PI * 2 - Math.PI / 2;
          const val    = (data[Math.floor(i * data.length / bars)] || 0) / 255;
          const barLen = val * 36 + 5;
          const hue    = 130 + val * 30;  // verde → amarillo
          ctx2d.save();
          ctx2d.strokeStyle = `hsla(${hue},75%,60%,${0.35 + val * .65})`;
          ctx2d.lineWidth   = 2; ctx2d.lineCap = 'round';
          ctx2d.beginPath();
          ctx2d.moveTo(CX + Math.cos(angle) * innerR,             CY + Math.sin(angle) * innerR);
          ctx2d.lineTo(CX + Math.cos(angle) * (innerR + barLen),  CY + Math.sin(angle) * (innerR + barLen));
          ctx2d.stroke(); ctx2d.restore();
        }
      }

      // Core glow institucional
      const gr = ctx2d.createRadialGradient(CX, CY, 0, CX, CY, 42);
      gr.addColorStop(0, 'rgba(27,77,53,0.35)');
      gr.addColorStop(1, 'rgba(27,77,53,0)');
      ctx2d.beginPath(); ctx2d.arc(CX, CY, 42, 0, Math.PI * 2);
      ctx2d.fillStyle = gr; ctx2d.fill();
    };

    frame();
  },

  /* ── Overlay helpers ─────────────────────────────────── */
  _showOverlay(processing) {
    const el = $('voz-ov');
    el.classList.toggle('proc', !!processing);
    el.classList.add('on');
    $('voz-lbl').textContent  = 'Escuchando...';
    $('voz-hint').textContent = 'Habla tu pregunta claramente';
    $('voz-transcript').textContent = '';
    $('voz-transcript').classList.remove('show');
    $('orb-icon').textContent = 'mic';
    const stopBtn = document.querySelector('.btn-voz-stop');
    if (stopBtn) stopBtn.style.display = 'flex';
  },

  _hideOverlay() {
    const el = $('voz-ov');
    el.classList.remove('on', 'proc');
    const canvas = $('orb-canvas');
    canvas.getContext('2d').clearRect(0, 0, canvas.width, canvas.height);
  },

  /* ── Mensajes DOM ────────────────────────────────────── */
  _addMsg(html, tipo) {
    const cont = $('msgs-wrap');
    const div  = document.createElement('div');
    div.className = `msg msg-${tipo}`;
    div.innerHTML = html + `<span class="msg-time">${hora()}</span>`;
    cont.appendChild(div);
    cont.scrollTop = cont.scrollHeight;
    return div;
  },

  _addTyping() {
    const cont = $('msgs-wrap');
    const div  = document.createElement('div');
    div.className = 'typing-dot';
    div.innerHTML = '<span></span><span></span><span></span>';
    cont.appendChild(div);
    cont.scrollTop = cont.scrollHeight;
    return div;
  },

  _hablar(texto) {
        if (!texto || !window.speechSynthesis) return;
        window.speechSynthesis.cancel();

        const hablar = (voces) => {
            let t = texto
                .replace(/24\/7/g, 'veinticuatro horas al día, siete días a la semana')
                .replace(/\bCCPL\b/g, 'el Colegio de Contadores')
                .replace(/Art\.\s*(\d+)\s*°?/gi, 'Artículo $1')
                .replace(/°/g, '')
                .replace(/S\/\s*([\d,]+)(?:\.\d+)?/g, (_, n) => n.replace(/,/g,'') + ' soles')
                .replace(/\bS\//g, '')
                .replace(/\b(\d{3})\s*(\d{3})\s*(\d{3})\b/g, (_, a,b,c) =>
                    [...a].join('-')+', '+[...b].join('-')+', '+[...c].join('-'));
            const utt  = new SpeechSynthesisUtterance(t);
            utt.lang   = 'es-PE';
            utt.rate   = 1.0;
            utt.pitch  = 1.0;
            const voz  = voces.find(v => v.lang.startsWith('es') && v.name.toLowerCase().includes('female'))
                    || voces.find(v => v.lang.startsWith('es')) || null;
            if (voz) utt.voice = voz;
            window.speechSynthesis.speak(utt);
        };

        const voces = window.speechSynthesis.getVoices();
        if (voces.length > 0) {
            hablar(voces);
        } else {
            window.speechSynthesis.addEventListener('voiceschanged',
                () => hablar(window.speechSynthesis.getVoices()), { once: true });
        }
    },
};




/* ════════════════════════════════════════════════════════════
   MODALES
════════════════════════════════════════════════════════════ */
const Modales = {

  /* ─── Fraccionamiento ────────────────────────────────── */
  fraccion: {
    deuda: 0, cuotaMin: 0, seleccion: null,

    _setDeuda(deuda, cuotaMin) {
      this.deuda    = deuda;
      this.cuotaMin = cuotaMin;
    },

    abrir() {
      if (this.deuda < 500) {
        Asistente._addMsg('Tu deuda es menor a S/ 500. El fraccionamiento aplica desde ese monto. ¿Quieres más información?', 'bot');
        return;
      }
      this._renderBody(this.cuotaMin);
      $('modal-fraccion').classList.add('open');
    },

    cerrar() { $('modal-fraccion').classList.remove('open'); },

    _renderBody(cuotaInicial) {
      const body = $('fraccion-body');
      const restante = Math.max(0, this.deuda - cuotaInicial);
      const condena  = Portal.ctx.deuda_condonable;

      body.innerHTML = `
        <div class="fraccio-condiciones">
          <div class="fraccio-cond-title">Condiciones del plan</div>
          <div class="fraccio-cond-item"><span class="mi sm c-amber">info</span> Deuda mínima para fraccionar: S/ 500</div>
          <div class="fraccio-cond-item"><span class="mi sm c-blue">percent</span> Cuota inicial mínima: 20% de la deuda total</div>
          <div class="fraccio-cond-item"><span class="mi sm c-dim">payments</span> Cuota mensual mínima: S/ 100</div>
          <div class="fraccio-cond-item"><span class="mi sm c-dim">calendar_month</span> Máximo 12 cuotas mensuales</div>
          ${condena > 0 ? `<div class="fraccio-cond-item"><span class="mi sm c-violet">auto_awesome</span> <strong style="color:var(--violet)">Condonable S/ ${fmt(condena)}</strong> — se elimina al activar el fraccionamiento (Acuerdo 007-2026)</div>` : ''}
          <div class="fraccio-cond-item"><span class="mi sm c-emerald">bolt</span> Habilidad temporal al pagar cada cuota puntualmente</div>
        </div>

        <div class="fraccio-field">
          <label class="fraccio-lbl">Cuota inicial (mínimo: S/ ${fmt(this.cuotaMin)})</label>
          <input type="number" class="fraccio-input" id="fraccio-inicial"
                 value="${this.cuotaMin}" min="${this.cuotaMin}" max="${this.deuda}"
                 oninput="Modales.fraccion._recalcular()">
          <div class="fraccio-input-hint">Puedes ingresar más del mínimo para reducir las cuotas mensuales</div>
        </div>

        <label class="fraccio-lbl" style="display:block;margin-bottom:10px">Elige tu plan mensual</label>
        <div class="fraccio-options" id="fraccio-options">
          <!-- Renderizado por _recalcular -->
        </div>
      `;

      this._recalcular();
    },

    _recalcular() {
      const input   = $('fraccio-inicial');
      if (!input) return;
      const inicial = Math.max(this.cuotaMin, parseFloat(input.value) || 0);
      const restante= Math.max(0, this.deuda - inicial);
      const optEl   = $('fraccio-options');
      if (!optEl) return;

      optEl.innerHTML = '';
      this.seleccion  = null;
      $('btn-solicitar-fraccion').style.display = 'none';

      for (let n = 2; n <= 12; n++) {
        const cuotaMes = Math.ceil(restante / n / 10) * 10;
        if (cuotaMes < 100) break;
        const div = document.createElement('div');
        div.className = 'fraccio-option';
        div.dataset.n = n;
        div.dataset.mes = cuotaMes;
        div.innerHTML = `
          <div>
            <div class="fraccio-n-cuotas">${n} cuotas mensuales</div>
            <div class="fraccio-detalle">de S/ ${fmt(cuotaMes)} cada una</div>
          </div>
          <div class="fraccio-monto-mes">S/ ${fmt(cuotaMes)}/mes</div>
        `;
        div.onclick = () => this._seleccionar(div, n, cuotaMes, inicial);
        optEl.appendChild(div);
      }
    },

    _seleccionar(el, n, cuotaMes, inicial) {
      document.querySelectorAll('.fraccio-option').forEach(o => o.classList.remove('selected'));
      el.classList.add('selected');
      this.seleccion = { n, cuotaMes, inicial };
      $('btn-solicitar-fraccion').style.display = 'flex';
    },

    async solicitar() {
      if (!this.seleccion) return;
      const { n, cuotaMes, inicial } = this.seleccion;
      try {
        const r = await fetch('/api/portal/solicitar-fraccionamiento', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({
            cuota_inicial: inicial,
            n_cuotas: n,
            cuota_mensual: cuotaMes,
            deuda_total: this.deuda,
          }),
        });
        const d = await r.json();
        this.cerrar();
        if (d.ok || r.ok) {
          Asistente._addMsg(`✅ Fraccionamiento solicitado: cuota inicial S/ ${fmt(inicial)}, ${n} cuotas de S/ ${fmt(cuotaMes)}/mes. El colegio revisará y activará tu habilidad temporal.`, 'bot');
        } else {
          Asistente._addMsg('Hubo un problema al solicitar el fraccionamiento. Por favor contacta a la oficina del colegio.', 'bot');
        }
      } catch(e) {
        this.cerrar();
        Asistente._addMsg('Error de conexión. Por favor intenta más tarde.', 'bot');
      }
    },
  },

  /* ─── Reportar Pago ──────────────────────────────────── */
  reportarPago: {
    metodo: null,
    archivo: null,

    abrir() { $('modal-reporte').classList.add('open'); },
    cerrar() { $('modal-reporte').classList.remove('open'); },

    setMetodo(m, btn) {
      this.metodo = m;
      document.querySelectorAll('.metodo-btn').forEach(b => b.classList.remove('active'));
      btn.classList.add('active');
    },

    handleFile(file) {
      if (!file) return;
      this.archivo = file;
      $('voucher-label').textContent = '✅ ' + file.name;
      $('voucher-drop').style.borderColor = 'var(--verde-soft)';
    },

    handleDrop(e) {
      e.preventDefault();
      $('voucher-drop').classList.remove('drag');
      const file = e.dataTransfer?.files?.[0];
      if (file) this.handleFile(file);
    },

    async enviar() {
      const monto = parseFloat($('rp-monto')?.value || 0);
      if (!monto || monto <= 0) {
        alert('Por favor ingresa el monto del pago.');
        return;
      }
      if (!this.metodo) {
        alert('Por favor selecciona el método de pago.');
        return;
      }

      const fd = new FormData();
      fd.append('concepto',   $('rp-concepto')?.value || 'deuda_total');
      fd.append('monto',      monto);
      fd.append('metodo',     this.metodo);
      fd.append('nro_operacion', $('rp-nro-op')?.value || '');
      fd.append('solicitar_constancia', $('rp-constancia-check')?.checked ? '1' : '0');
      if (this.archivo) fd.append('voucher', this.archivo);

      try {
        const r = await fetch('/api/portal/reportar-pago', { method: 'POST', body: fd });
        const d = await r.json();
        this.cerrar();
        Asistente._addMsg(
          d.mensaje || '✅ Pago reportado. El colegio lo validará en hasta 24h. Recibirás una notificación al aprobar.',
          'bot'
        );
      } catch(e) {
        this.cerrar();
        Asistente._addMsg('Error al enviar el reporte. Por favor intenta de nuevo.', 'bot');
      }
    },
  },

  /* ─── Pago en Línea ──────────────────────────────────── */
  pagoLinea: {

    abrir() {
      this.recalcular();
      $('modal-pago-linea').classList.add('open');
    },

    cerrar() { $('modal-pago-linea').classList.remove('open'); },

    recalcular() {
      const monto    = parseFloat($('pl-monto')?.value || 0);
      const addConst = $('pl-incluir-constancia')?.checked ? 10 : 0;
      const total    = monto + addConst;
      const el       = $('pl-total');
      if (el) el.textContent = 'S/ ' + fmt(total);
    },

    async pagar() {
      const monto = parseFloat($('pl-monto')?.value || 0);
      if (!monto || monto <= 0) {
        alert('Por favor ingresa el monto a pagar.');
        return;
      }
      const addConst = $('pl-incluir-constancia')?.checked ? 10 : 0;
      const total    = monto + addConst;

      try {
        // Llamar al endpoint OpenPay para obtener URL de pago
        const r = await fetch('/api/portal/pago-linea', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({
            monto,
            incluir_constancia: addConst > 0,
            total,
          }),
        });
        const d = await r.json();

        if (d.redirect_url) {
          location.href = d.redirect_url;
        } else if (d.error) {
          Asistente._addMsg('Error al iniciar el pago: ' + d.error, 'bot');
        } else {
          Asistente._addMsg('Error al conectar con el procesador de pagos. Intenta más tarde.', 'bot');
        }

      } catch(e) {
        this.cerrar();
        Asistente._addMsg('Error de conexión al procesar el pago.', 'bot');
      }
    },
  },
};


/* ════════════════════════════════════════════════════════════
   PWA — install prompt + exit intent
════════════════════════════════════════════════════════════ */
const PWA = {

  deferredPrompt: null,
  popupMostrado:  false,
  esIOS: /iPad|iPhone|iPod/.test(navigator.userAgent) && !window.MSStream,

  init() {
    // Capturar beforeinstallprompt (Android/Chrome/Edge)
    window.addEventListener('beforeinstallprompt', e => {
      e.preventDefault();
      this.deferredPrompt = e;
      console.log('[PWA] beforeinstallprompt capturado');
    });

    // Detectar iOS
    if (this.esIOS) {
      const iosHint = $('ios-hint');
      if (iosHint) iosHint.style.display = 'block';
      // En iOS no hay deferredPrompt — btn muestra instrucciones
    }

    // Exit intent desktop
    document.addEventListener('mouseleave', e => {
      if (e.clientY < 5 && !this.popupMostrado) {
        setTimeout(() => this.mostrarPopup(), 300);
      }
    });

    // Exit intent mobile — cambio de visibilidad (tab switch, home button)
    document.addEventListener('visibilitychange', () => {
      if (document.hidden && !this.popupMostrado) {
        // No disparar en la primera visita para no ser invasivo
        // Solo si ya lleva más de 30s en la página
        if (this._tiempoEnPagina() > 30) this.mostrarPopup();
      }
    });

    this._inicioTiempo = Date.now();
  },

  _tiempoEnPagina() {
    return Math.round((Date.now() - (this._inicioTiempo || Date.now())) / 1000);
  },

  mostrarPopup() {
    if (this.popupMostrado) return;
    this.popupMostrado = true;
    $('pwa-overlay').classList.add('open');
  },

  cerrarPopup() {
    $('pwa-overlay').classList.remove('open');
  },

  async instalar() {
    // Desde bottom bar
    if (this.deferredPrompt) {
      this.deferredPrompt.prompt();
      const { outcome } = await this.deferredPrompt.userChoice;
      if (outcome === 'accepted') this.deferredPrompt = null;
    } else {
      // No hay prompt disponible — mostrar popup con instrucciones
      this.mostrarPopup();
    }
  },

  async instalarDesdePopup() {
    if (this.deferredPrompt) {
      this.deferredPrompt.prompt();
      const { outcome } = await this.deferredPrompt.userChoice;
      this.cerrarPopup();
      if (outcome === 'accepted') {
        this.deferredPrompt = null;
        Asistente._addMsg('✅ ¡App instalada! Ya puedes recibir alertas y acceder sin conexión.', 'bot');
      }
    } else if (this.esIOS) {
      // Instrucciones ya visibles en el popup para iOS — no hacer nada más
    } else {
      this.cerrarPopup();
      Asistente._addMsg('La app ya está instalada o tu navegador no soporta la instalación directa. Prueba desde Chrome en Android.', 'bot');
    }
  },
};


/* ════════════════════════════════════════════════════════════
   Cerrar modales al tocar el overlay
════════════════════════════════════════════════════════════ */
document.querySelectorAll('.modal-overlay').forEach(ov => {
  ov.addEventListener('click', e => {
    if (e.target === ov) ov.classList.remove('open');
  });
});

// Recalcular total pago en línea al cambiar checkbox
document.addEventListener('change', e => {
  if (e.target.id === 'pl-incluir-constancia') Modales.pagoLinea.recalcular();
});


/* ════════════════════════════════════════════════════════════
   BOOT
════════════════════════════════════════════════════════════ */
document.addEventListener('DOMContentLoaded', () => {
  Portal.init();
  Asistente.activarWhisper();
  PWA.init();
});