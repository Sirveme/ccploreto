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
   Utilidades globales
──────────────────────────────────────────────────────────── */
const fmt = n =>
  (parseFloat(n) || 0).toLocaleString('es-PE', { minimumFractionDigits: 2, maximumFractionDigits: 2 });

// Redondeo al sol — sin céntimos para el colegiado
const fmtS = n => Math.round(parseFloat(n) || 0).toLocaleString('es-PE');

const hora = () =>
  new Date().toLocaleTimeString('es-PE', { hour: '2-digit', minute: '2-digit' });

const $ = id => document.getElementById(id);


/* ────────────────────────────────────────────────────────────
   esCondonable(deu) — Acuerdo 007-2026
   Misma lógica que loadDeuda(). Función global para reusar
   en cualquier módulo sin duplicar.
──────────────────────────────────────────────────────────── */
function esCondonable(deu) {
  const tipo     = (deu.debt_type || '').toLowerCase();
  const concepto = (deu.concept   || '').toLowerCase();
  const periodo  = (deu.periodo   || '');

  if (tipo === 'multa') {
    // Multas de elecciones/votaciones: NUNCA condonables
    return !concepto.includes('elecci') &&
           !concepto.includes('votaci') &&
           !concepto.includes('elección');
  }
  if (tipo === 'cuota_ordinaria') {
    const m = periodo.match(/(\d{4})/);
    return !!(m && parseInt(m[1]) <= 2019);
  }
  return false;
}


/* ════════════════════════════════════════════════════════════
   PORTAL — carga de perfil y deuda
════════════════════════════════════════════════════════════ */
const Portal = {

  ctx: {
    nombre: '', primera: '', matricula: '',
    dni: '', condicion: '',
    // campos internos
    deuda_total:        0,
    deuda_fraccionable: 0,
    deuda_condonable:   0,
    cuota_inicial_min:  0,
    deudas:             [],
    // aliases para el backend (asistente.py)
    deuda_real:         0,
    condonable:         0,
    cuotas_pend:        0,
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
      if ($('panel-av'))     $('panel-av').textContent     = ini;
      if ($('panel-nombre')) $('panel-nombre').textContent = nombre;
      if ($('panel-mat'))    $('panel-mat').textContent    = 'Matrícula ' + (perfil.matricula || '—');
      if ($('topbar-org'))   $('topbar-org').textContent   = perfil.organizacion || 'Colegio de Contadores Públicos de Loreto';

      if (cond === 'retirado') {
        const b = $('panel-status');
        if (b) {
          b.classList.replace('status-inhabil', 'status-retirado');
          if ($('panel-status-txt')) $('panel-status-txt').textContent = 'RETIRADO';
        }
      }

      // DOM — topbar mobile
      if ($('mob-av'))     $('mob-av').textContent     = ini;
      if ($('mob-nombre')) $('mob-nombre').textContent = primera;
      if ($('pwa-nombre')) $('pwa-nombre').textContent = primera;

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

        const total    = parseFloat(d.total || 0);
        const cant     = parseInt(d.cantidad || 0);
        const deudas   = d.deudas || [];
        const cuotasPend = parseInt(d.cuotas_pendientes || 0);

        // ── Calcular condonable desde las deudas (Acuerdo 007-2026) ──
        // No depender de d.condonable que puede no venir del API
        let condona = 0;
        deudas.forEach(deu => {
        const tipo     = (deu.debt_type || deu.categoria || '').toLowerCase();
        const concepto = (deu.concept   || deu.concepto  || '').toLowerCase();
        const periodo  = (deu.periodo   || '');
        const balance  = parseFloat(deu.balance || 0);

        if (tipo === 'multa') {
            const esEleccion = concepto.includes('elecci') ||
                            concepto.includes('votaci') ||
                            concepto.includes('elección');
            if (!esEleccion) condona += balance;

        } else if (tipo === 'cuota_ordinaria') {
            const m = periodo.match(/(\d{4})/);
            if (m && parseInt(m[1]) <= 2019) condona += balance;
        }
        });
        // Si el API sí lo devuelve y la lista está vacía, usar el del API como fallback
        if (condona === 0 && d.condonable) condona = parseFloat(d.condonable);

        // ── Deuda real = total - condonable ──
        const fraccio  = Math.max(0, total - condona);

        // ── Cuota inicial mínima: ceil al 10 más cercano ──
        const cuotaMin = fraccio >= 500
        ? Math.max(100, Math.ceil((fraccio * 0.20) ) )
        : 0;

        // Guardar en ctx — con aliases para el backend
        this.ctx.deuda_total        = total;
        this.ctx.deuda_condonable   = condona;
        this.ctx.deuda_fraccionable = fraccio;
        this.ctx.cuota_inicial_min  = cuotaMin;
        this.ctx.deudas             = deudas;
        this.ctx.cuotas_pend        = cuotasPend;
        this.ctx.deuda_real         = fraccio;   // alias backend
        this.ctx.condonable         = condona;   // alias backend

        console.log('[Portal.ctx] total:', total,
                    '| condona:', condona,
                    '| fraccio:', fraccio,
                    '| cuotaMin:', cuotaMin);

        // Panel desktop
        if ($('panel-deuda-total')) $('panel-deuda-total').textContent = fmt(total);
        if ($('panel-deuda-cnt'))   $('panel-deuda-cnt').textContent   =
        cant + ' concepto' + (cant !== 1 ? 's' : '') + ' pendiente' + (cant !== 1 ? 's' : '');
        if ($('mob-deuda')) $('mob-deuda').textContent = 'Deuda S/ ' + fmt(total);

        // Pills
        const pillsEl = $('panel-pills');
        if (pillsEl) {
        pillsEl.innerHTML = '';
        if (fraccio >= 500)
            pillsEl.insertAdjacentHTML('beforeend',
            `<span class="deuda-pill pill-fraccion">
                <span class="mi sm" style="color:var(--blue-soft)">calendar_month</span>
                Fraccionable S/ ${fmt(fraccio)}
            </span>`);
        if (condona > 0)
            pillsEl.insertAdjacentHTML('beforeend',
            `<span class="deuda-pill pill-condona">
                <span class="mi sm" style="color:var(--violet)">auto_awesome</span>
                Condonable S/ ${fmt(condona)}
            </span>`);
        }

        this._renderChips(total, cuotaMin, condona, fraccio);

        const plRef = $('pl-deuda-ref');
        if (plRef) plRef.textContent = 'S/ ' + fmt(total);

        Modales.fraccion._setDeuda(fraccio, cuotaMin);

        const btnFracc = $('btn-fracc');
        if (btnFracc) btnFracc.style.display = fraccio >= 500 ? 'flex' : 'none';

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
      chips.push({
        cls: 'chip-deuda', icon: 'account_balance_wallet',
        label: `Debo S/ ${fmtS(total)}`,
        q: '¿Cuánto debo en total y en qué conceptos?',
      });
    if (fraccio >= 500)
      chips.push({
        cls: 'chip-inicial', icon: 'calendar_month',
        label: `Inicial mín. S/ ${fmtS(cuotaMin)}`,
        q: '¿Cómo funciona el fraccionamiento y cuánto sería mi cuota mensual?',
      });
    if (condona > 0)
      chips.push({
        cls: 'chip-condona', icon: 'auto_awesome',
        label: `Me condonan S/ ${fmtS(condona)}`,
        q: '¿Qué deudas me condonan y cómo aplico a la condonación?',
      });
    chips.push({
      cls: 'chip-benef', icon: 'handshake',
      label: 'Beneficios al reactivarme',
      q: '¿Qué beneficios y descuentos recupero al reactivarme?',
    });
    chips.push({
      cls: 'chip-reactiva', icon: 'bolt',
      label: 'Reactivarme hoy',
      q: '¿Cuál es la forma más rápida de reactivarme hoy?',
    });
    chips.push({
      cls: 'chip-legal', icon: 'gavel',
      label: 'Base legal',
      q: '¿Cuál es la base legal que explica mi condición y el fraccionamiento?',
    });

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
   ASISTENTE — chat de texto + grabación de voz + síntesis
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

  /* ── Saludo inicial ────────────────────────────────────── */
  welcomeMsg() {
    const { primera, deuda_total, deuda_condonable, deuda_fraccionable, cuota_inicial_min } = Portal.ctx;
    let txt = `¡Hola, ${primera}! 👋 Soy el asistente del Colegio de Contadores.`;
    if (deuda_total > 0) {
      txt += ` Tienes una deuda de <strong>S/ ${fmtS(deuda_total)}</strong>.`;
      if (deuda_condonable > 0)
        txt += ` De eso, <strong>S/ ${fmtS(deuda_condonable)}</strong> se <strong>condona automáticamente</strong> al fraccionar (Acuerdo 007-2026).`;
      if (deuda_fraccionable >= 500)
        txt += ` Tu deuda real a fraccionar es <strong>S/ ${fmtS(deuda_fraccionable)}</strong> con una cuota inicial desde <strong>S/ ${fmtS(cuota_inicial_min)}</strong>.`;
    }
    txt += '<br><br>Usa los accesos rápidos o escríbeme tu pregunta. ¿En qué te ayudo?';
    this._addMsg(txt, 'bot');
  },

  /* ── Chat texto ────────────────────────────────────────── */
  enviar() {
    const input = $('chat-input');
    const texto = input.value.trim();
    if (!texto) return;
    input.value = '';
    this._sendText(texto);
  },

  ask(texto) {
    const chips = $('ctx-chips');
    if (chips) chips.style.display = 'none';
    this._sendText(texto);
  },

  async _sendText(texto) {
    this._addMsg(texto, 'user');
    const typing = this._addTyping();
    const btnSend = $('btn-send');
    if (btnSend) btnSend.disabled = true;

    try {
      const fd = new FormData();
      fd.append('pregunta', texto);
      fd.append('ctx', JSON.stringify(Portal.ctx));

      const r = await fetch('/api/portal/asistente', { method: 'POST', body: fd });
      const d = await r.json();
      typing.remove();
      const resp = d.respuesta || 'No pude responder en este momento.';
      this._addMsg(resp, 'bot');
      this._hablar(resp);

    } catch(e) {
      typing.remove();
      this._addMsg('Error de conexión. Intenta en unos segundos.', 'bot');
    } finally {
      if (btnSend) btnSend.disabled = false;
    }
  },

  /* ── Síntesis de voz ───────────────────────────────────── */
  _hablar(texto) {
    if (!texto || !window.speechSynthesis) return;
    window.speechSynthesis.cancel();

    const limpiar = (t) => t
      // Porcentajes legibles
      .replace(/(\d+)\s*%/g, '$1 por ciento')
      // 24/7 → texto completo
      .replace(/24\/7/g, 'veinticuatro horas al día, siete días a la semana')
      // Fracciones simples — evitar "sobre" en montos
      .replace(/\b(\d+)\/(\d+)\b/g, (_, a, b) => a + ' sobre ' + b)
      // CCPL → "el Colegio de Contadores"
      .replace(/\bCCPL\b/g, 'el Colegio de Contadores')
      .replace(/\bCCPLo\b/gi, 'el Colegio de Contadores de Loreto')
      // Artículos estatutarios — sin puntos ni grados
      .replace(/Art\.\s*(\d+)\s*°?/gi, 'Artículo $1')
      .replace(/Art°?\.\s*/gi, 'Artículo ')
      .replace(/°/g, '')
      // Montos: S/ 2,272.00 → "2272 soles"
      .replace(/S\/\s*([\d,]+)(?:\.\d+)?/g, (_, n) => n.replace(/,/g, '') + ' soles')
      .replace(/\bS\//g, '')
      // Teléfonos 9 dígitos: 979 169 813 → "9-7-9, 1-6-9, 8-1-3"
      .replace(/\b(\d{3})\s*(\d{3})\s*(\d{3})\b/g, (_, a, b, c) =>
        [...a].join('-') + ', ' + [...b].join('-') + ', ' + [...c].join('-'))
      // HTML tags
      .replace(/<[^>]+>/g, ' ')
      .replace(/\s+/g, ' ').trim();

    const hablar = (voces) => {
      const utt  = new SpeechSynthesisUtterance(limpiar(texto));
      utt.lang   = 'es-PE';
      utt.rate   = 1.0;
      utt.pitch  = 1.0;
      const voz  = voces.find(v => v.lang.startsWith('es') && v.name.toLowerCase().includes('female'))
                || voces.find(v => v.lang.startsWith('es'))
                || null;
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

  /* ── Voz ───────────────────────────────────────────────── */
  async toggleVoz() {
    if (this.grabando) { this.detenerGrabacion(); return; }
    await this._iniciarGrabacion();
  },

  async _iniciarGrabacion() {
    if (!this.usarWhisper) { this._webSpeechFallback(); return; }

    try {
      const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
      this.chunks  = [];

      // Elegir MIME soportado
      const mime = ['audio/webm;codecs=opus', 'audio/webm', 'audio/ogg', '']
        .find(m => !m || MediaRecorder.isTypeSupported(m));
      this.mr = new MediaRecorder(stream, mime ? { mimeType: mime } : undefined);
      this.mr.ondataavailable = e => { if (e.data.size > 0) this.chunks.push(e.data); };
      this.mr.onstop          = ()  => this._procesarAudio(stream, mime || 'audio/webm');
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
      const btnMic  = $('btn-mic');
      const micIcon = $('mic-icon');
      if (btnMic)  btnMic.classList.add('rec');
      if (micIcon) micIcon.textContent = 'stop_circle';

      // Auto-stop a los 15 segundos
      this._autoStopTimer = setTimeout(() => {
        if (this.grabando) this.detenerGrabacion();
      }, 15000);

    } catch(e) {
      console.error('[Voz]', e);
      this._addMsg('No se pudo acceder al micrófono. Por favor permite el acceso en tu navegador.', 'bot');
    }
  },

  detenerGrabacion() {
    if (!this.mr || !this.grabando) return;
    this.grabando = false;
    if (this._autoStopTimer) { clearTimeout(this._autoStopTimer); this._autoStopTimer = null; }
    if (this.rafId)          { cancelAnimationFrame(this.rafId); this.rafId = null; }
    this.mr.stop();

    if ($('voz-lbl'))  $('voz-lbl').textContent  = 'Procesando...';
    if ($('voz-hint')) $('voz-hint').textContent = 'Enviando al asistente IA';
    $('voz-ov')?.classList.add('proc');
    document.querySelector('.btn-voz-stop')?.style?.setProperty('display', 'none');
    if ($('orb-icon')) $('orb-icon').textContent = 'hourglass_empty';

    const btnMic  = $('btn-mic');
    const micIcon = $('mic-icon');
    if (btnMic)  btnMic.classList.remove('rec');
    if (micIcon) micIcon.textContent = 'mic';
  },

  async _procesarAudio(stream, mimeUsado) {
    stream.getTracks().forEach(t => t.stop());
    if (this.audioCtx) { try { await this.audioCtx.close(); } catch(_) {} this.audioCtx = null; }
    this.analyser = null;

    const blob = new Blob(this.chunks, { type: mimeUsado || 'audio/webm' });
    console.log('[Audio] blob size:', blob.size, 'mime:', blob.type);

    if (blob.size < 500) {
      this._hideOverlay();
      this._addMsg('No escuché nada. ¿Puedes intentar de nuevo?', 'bot');
      return;
    }

    try {
      // Determinar extensión según MIME
      const extMap = {
        'audio/webm': 'webm', 'audio/webm;codecs=opus': 'webm',
        'audio/ogg':  'ogg',  'audio/mp4': 'mp4',
        'audio/mpeg': 'mp3',  'audio/wav': 'wav',
      };
      const ext      = extMap[blob.type] || extMap[mimeUsado] || 'webm';
      const filename = `voz.${ext}`;

      const fd = new FormData();
      fd.append('audio', blob, filename);
      fd.append('ctx',   JSON.stringify(Portal.ctx));

      console.log('[Audio] enviando:', filename, blob.size, 'bytes');

      const r = await fetch('/api/portal/asistente/audio', { method: 'POST', body: fd });

      if (!r.ok) {
        const err = await r.json().catch(() => ({}));
        console.error('[Audio] error HTTP', r.status, err);
        this._hideOverlay();
        // Mostrar respuesta de error si el backend la provee
        const msg = err.respuesta || err.error || 'No pude procesar el audio. Intenta de nuevo o escribe tu pregunta.';
        this._addMsg(msg, 'bot');
        return;
      }

      const d = await r.json();
      this._hideOverlay();

      const chips = $('ctx-chips');
      if (chips) chips.style.display = 'none';

      if (d.transcripcion) this._addMsg(`🎙 "${d.transcripcion}"`, 'user');
      const resp = d.respuesta || 'No pude procesar tu consulta.';
      this._addMsg(resp, 'bot');
      this._hablar(resp);

    } catch(e) {
      console.error('[Audio]', e);
      this._hideOverlay();
      this._addMsg('Error de conexión procesando el audio. Intenta de nuevo.', 'bot');
    }
  },

  _webSpeechFallback() {
    const SR = window.SpeechRecognition || window.webkitSpeechRecognition;
    if (!SR) {
      this._addMsg('Tu navegador no soporta reconocimiento de voz. Por favor escribe tu pregunta.', 'bot');
      return;
    }
    const sr    = new SR();
    sr.lang     = 'es-PE';
    sr.onresult = e => {
      const t = e.results[0]?.[0]?.transcript.trim();
      if (t) {
        const inp = $('chat-input');
        if (inp) inp.value = t;
        this.enviar();
      }
    };
    sr.onerror = () => {};
    sr.start();
  },

  /* ── Orb canvas ────────────────────────────────────────── */
  _drawOrb() {
    const canvas = $('orb-canvas');
    if (!canvas) return;
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
          const hue    = 130 + val * 30;
          ctx2d.save();
          ctx2d.strokeStyle = `hsla(${hue},75%,60%,${0.35 + val * .65})`;
          ctx2d.lineWidth   = 2;
          ctx2d.lineCap     = 'round';
          ctx2d.beginPath();
          ctx2d.moveTo(CX + Math.cos(angle) * innerR,            CY + Math.sin(angle) * innerR);
          ctx2d.lineTo(CX + Math.cos(angle) * (innerR + barLen), CY + Math.sin(angle) * (innerR + barLen));
          ctx2d.stroke();
          ctx2d.restore();
        }
      }

      // Core glow institucional
      const gr = ctx2d.createRadialGradient(CX, CY, 0, CX, CY, 42);
      gr.addColorStop(0, 'rgba(27,77,53,0.35)');
      gr.addColorStop(1, 'rgba(27,77,53,0)');
      ctx2d.beginPath();
      ctx2d.arc(CX, CY, 42, 0, Math.PI * 2);
      ctx2d.fillStyle = gr;
      ctx2d.fill();
    };

    frame();
  },

  /* ── Overlay helpers ───────────────────────────────────── */
  _showOverlay(processing) {
    const el = $('voz-ov');
    if (!el) return;
    el.classList.toggle('proc', !!processing);
    el.classList.add('on');
    if ($('voz-lbl'))        $('voz-lbl').textContent        = 'Escuchando...';
    if ($('voz-hint'))       $('voz-hint').textContent       = 'Habla tu pregunta claramente';
    if ($('voz-transcript')) {
      $('voz-transcript').textContent = '';
      $('voz-transcript').classList.remove('show');
    }
    if ($('orb-icon')) $('orb-icon').textContent = 'mic';
    const stopBtn = document.querySelector('.btn-voz-stop');
    if (stopBtn) stopBtn.style.display = 'flex';
  },

  _hideOverlay() {
    const el = $('voz-ov');
    if (!el) return;
    el.classList.remove('on', 'proc');
    const canvas = $('orb-canvas');
    if (canvas) canvas.getContext('2d').clearRect(0, 0, canvas.width, canvas.height);
  },

  /* ── Mensajes DOM ──────────────────────────────────────── */
  _addMsg(html, tipo) {
    const cont = $('msgs-wrap');
    if (!cont) return;
    const div  = document.createElement('div');
    div.className = `msg msg-${tipo}`;
    div.innerHTML = html + `<span class="msg-time">${hora()}</span>`;
    cont.appendChild(div);
    cont.scrollTop = cont.scrollHeight;
    return div;
  },

  _addTyping() {
    const cont = $('msgs-wrap');
    if (!cont) return { remove: () => {} };
    const div  = document.createElement('div');
    div.className = 'typing-dot';
    div.innerHTML = '<span></span><span></span><span></span>';
    cont.appendChild(div);
    cont.scrollTop = cont.scrollHeight;
    return div;
  },
};


/* ════════════════════════════════════════════════════════════
   MODALES
════════════════════════════════════════════════════════════ */
const Modales = {

  /* ─── Fraccionamiento ─────────────────────────────────── */
  fraccion: {
    deuda: 0, cuotaMin: 0, seleccion: null,

    _setDeuda(deuda, cuotaMin) {
      this.deuda    = deuda;
      this.cuotaMin = cuotaMin;
    },

    abrir() {
      if (this.deuda < 500) {
        Asistente._addMsg(
          'Tu deuda fraccionable es menor a S/ 500. El fraccionamiento aplica desde ese monto mínimo. ¿Quieres más información?',
          'bot'
        );
        return;
      }
      this._renderBody(this.cuotaMin);
      $('modal-fraccion')?.classList.add('open');
    },

    cerrar() { $('modal-fraccion')?.classList.remove('open'); },

    _renderBody(cuotaInicial) {
      const body = $('fraccion-body');
      if (!body) return;
      const condena = Portal.ctx.deuda_condonable;

      body.innerHTML = `
        <div class="fraccio-condiciones">
          <div class="fraccio-cond-title">Condiciones del plan</div>
          <div class="fraccio-cond-item"><span class="mi sm c-amber">info</span> Deuda mínima para fraccionar: S/ 500</div>
          <div class="fraccio-cond-item"><span class="mi sm c-blue">percent</span> Cuota inicial mínima: 20% de la deuda a fraccionar</div>
          <div class="fraccio-cond-item"><span class="mi sm c-dim">payments</span> Cuota mensual mínima: S/ 100</div>
          <div class="fraccio-cond-item"><span class="mi sm c-dim">calendar_month</span> Máximo 12 cuotas mensuales</div>
          ${condena > 0 ? `<div class="fraccio-cond-item"><span class="mi sm c-violet">auto_awesome</span> <strong style="color:var(--violet)">Condonable S/ ${fmt(condena)}</strong> — se elimina al activar (Acuerdo 007-2026)</div>` : ''}
          <div class="fraccio-cond-item"><span class="mi sm c-emerald">bolt</span> Habilidad temporal al pagar cada cuota puntualmente</div>
        </div>

        <div class="fraccio-field">
          <label class="fraccio-lbl">Cuota inicial (mínimo: S/ ${fmt(this.cuotaMin)})</label>
          <input type="number" class="fraccio-input" id="fraccio-inicial"
                 value="${this.cuotaMin}" min="${this.cuotaMin}" max="${this.deuda}"
                 step="10"
                 oninput="Modales.fraccion._recalcular()">
          <div class="fraccio-input-hint">Puedes ingresar más del mínimo para reducir las cuotas mensuales</div>
        </div>

        <label class="fraccio-lbl" style="display:block;margin-bottom:10px">Elige tu plan mensual</label>
        <div class="fraccio-options" id="fraccio-options"></div>
      `;

      this._recalcular();
    },

    _recalcular() {
      const input = $('fraccio-inicial');
      if (!input) return;
      // Cuota inicial: usar ceil para consistencia con backend
      const inicial  = Math.max(this.cuotaMin, parseFloat(input.value) || 0);
      const restante = Math.max(0, this.deuda - inicial);
      const optEl    = $('fraccio-options');
      if (!optEl) return;

      optEl.innerHTML = '';
      this.seleccion  = null;
      const btnSol = $('btn-solicitar-fraccion');
      if (btnSol) btnSol.style.display = 'none';

      for (let n = 2; n <= 12; n++) {
        // Cuota mensual redondeada al 10 superior
        const cuotaMes = Math.ceil(restante / n );
        if (cuotaMes < 100) break;
        const div = document.createElement('div');
        div.className    = 'fraccio-option';
        div.dataset.n    = n;
        div.dataset.mes  = cuotaMes;
        div.innerHTML    = `
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
      const btnSol = $('btn-solicitar-fraccion');
      if (btnSol) btnSol.style.display = 'flex';
    },

    pagarConTarjeta() {
      if (!this.seleccion) return;
      const { n, cuotaMes, inicial } = this.seleccion;

      // Generar código y notificar en el asistente
      const mat    = Portal.ctx.matricula || Portal.ctx.dni || '?';
      const matCod = mat.replace(/[^0-9]/g, '').slice(-4);
      const mes    = String(new Date().getMonth() + 1).padStart(2, '0');
      const codigo = `${matCod}-F${n}M-${mes}`;
      sessionStorage.setItem('fracc_codigo', codigo);
      sessionStorage.setItem('fracc_plan', JSON.stringify({ n, cuotaMes, inicial }));

      Asistente._addMsg(
          `📋 Tu código de plan es <strong>${codigo}</strong> ` +
          `(${n} meses · S/ ${Math.round(cuotaMes)}/mes). ` +
          `Guárdalo por si necesitas comunicarte con el colegio.`,
          'bot'
      );

      this.cerrar();
      Modales.pagoLinea.abrir(inicial);
  },

    irAReportar() {
        if (!this.seleccion) return;
        const { n, cuotaMes, inicial } = this.seleccion;

        const mat    = Portal.ctx.matricula || Portal.ctx.dni || '?';
        const matCod = mat.replace(/[^0-9]/g, '').slice(-4);
        const mes    = String(new Date().getMonth() + 1).padStart(2, '0');
        const codigo = `${matCod}-F${n}M-${mes}`;

        sessionStorage.setItem('fracc_codigo', codigo);
        sessionStorage.setItem('fracc_plan',   JSON.stringify({ n, cuotaMes, inicial }));

        Asistente._addMsg(
            `📋 Tu código de fraccionamiento es <strong>${codigo}</strong> ` +
            `(${n} meses de S/ ${Math.round(cuotaMes)}/mes). ` +
            `Guárdalo — también sirve en caja.`,
            'bot'
        );

        this.cerrar();
        // Usar abrirConFraccion para pre-llenar todo correctamente
        Modales.reportarPago.abrirConFraccion(inicial, n, cuotaMes, codigo);
    },

    async solicitar() {
      if (!this.seleccion) return;
      const { n, cuotaMes, inicial } = this.seleccion;
      try {
        const r = await fetch('/api/portal/solicitar-fraccionamiento', {
          method:  'POST',
          headers: { 'Content-Type': 'application/json' },
          body:    JSON.stringify({
            cuota_inicial:  inicial,
            n_cuotas:       n,
            cuota_mensual:  cuotaMes,
            deuda_total:    this.deuda,
          }),
        });
        const d = await r.json();
        this.cerrar();
        if (d.ok || r.ok) {
          Asistente._addMsg(
            `✅ Fraccionamiento solicitado: cuota inicial <strong>S/ ${fmt(inicial)}</strong>, ${n} cuotas de <strong>S/ ${fmt(cuotaMes)}/mes</strong>. El colegio revisará y activará tu habilidad temporal.`,
            'bot'
          );
        } else {
          Asistente._addMsg(
            'Hubo un problema al solicitar el fraccionamiento. Por favor contacta a la oficina del colegio.',
            'bot'
          );
        }
      } catch(e) {
        this.cerrar();
        Asistente._addMsg('Error de conexión. Por favor intenta más tarde.', 'bot');
      }
    },
  },


  /* ─── Catálogo ────────────────────────────────────────── */
catalogo: {
  items:       [],
  seleccion:   [],   // [{id, nombre, monto, es_mercaderia}]
  filtroActual: null,

  async abrir() {
    $('modal-catalogo')?.classList.add('open');
    if (this.items.length === 0) await this._cargar();
    this._renderFiltros();
    this._renderItems(this.filtroActual);
  },

  cerrar() {
    $('modal-catalogo')?.classList.remove('open');
    this.seleccion = [];
    this._actualizarFooter();
  },

  async _cargar() {
    try {
        const r = await fetch('/api/portal/catalogo');
        if (!r.ok) { console.error('[Catalogo] HTTP', r.status); return; }
        const d = await r.json();
        this.items = d.catalogo || [];
        console.log('[Catalogo] items:', this.items.length);

        // Llenar optgroups del select rp-concepto
        const servicios = this.items.filter(i => i.categoria !== 'mercaderia');
        const productos  = this.items.filter(i => i.categoria === 'mercaderia');
        const optServ = $('opt-servicios');
        const optProd = $('opt-productos');
        if (optServ) {
            optServ.innerHTML = servicios.map(i =>
                `<option value="serv_${i.id}">${i.nombre} — S/ ${Math.round(i.monto_base)}</option>`
            ).join('');
        }
        if (optProd) {
            optProd.innerHTML = productos.map(i =>
                `<option value="prod_${i.id}">${i.nombre} — S/ ${Math.round(i.monto_base)}</option>`
            ).join('');
        }
    } catch(e) {
        console.error('[Catalogo]', e);
    }
},

  _renderFiltros() {
    const el = $('cat-filtros');
    if (!el) return;
    const cats = [...new Set(this.items.map(i => i.categoria))];
    const labels = {
      mercaderia: '🛍 Productos', constancias: '📜 Constancias',
      capacitacion: '🎓 Capacitación', derechos: '📋 Derechos',
      otros: '📦 Otros',
    };
    el.innerHTML = `
      <button class="cat-pill ${!this.filtroActual ? 'active' : ''}"
              onclick="Modales.catalogo._renderItems(null)">
        Todos (${this.items.length})
      </button>
      ${cats.map(c => `
        <button class="cat-pill ${this.filtroActual === c ? 'active' : ''}"
                onclick="Modales.catalogo._renderItems('${c}')">
          ${labels[c] || c} (${this.items.filter(i => i.categoria === c).length})
        </button>`).join('')}`;
  },

  _renderItems(filtro) {
    this.filtroActual = filtro;
    // Actualizar pills activos
    document.querySelectorAll('.cat-pill').forEach(p => {
      p.classList.toggle('active',
        (!filtro && p.textContent.startsWith('Todos')) ||
        p.getAttribute('onclick')?.includes(`'${filtro}'`));
    });

    const lista  = $('cat-lista');
    const items  = filtro ? this.items.filter(i => i.categoria === filtro) : this.items;

    if (!items.length) {
      lista.innerHTML = `<div style="text-align:center;color:#64748b;padding:24px">
        Sin items disponibles</div>`;
      return;
    }

    lista.innerHTML = items.map(item => {
      const sel     = this.seleccion.find(s => s.id === item.id);
      const monto   = item.monto_colegiado || item.monto_base;
      const sinStock = item.maneja_stock && item.stock_actual === 0;
      return `
        <div class="cat-item ${sel ? 'cat-sel' : ''} ${sinStock ? 'cat-agotado' : ''}"
             onclick="${sinStock ? '' : `Modales.catalogo._toggle(${item.id})`}">
          <div style="flex:1">
            <div style="font-size:13px;font-weight:600;color:#e2eaf7;margin-bottom:2px">
              ${item.nombre}
              ${item.es_mercaderia ? '<span class="cat-badge-prod">Producto físico</span>' : ''}
            </div>
            ${item.descripcion ? `<div style="font-size:11px;color:#64748b">${item.descripcion}</div>` : ''}
            ${sinStock ? `<div style="font-size:10px;color:#ef4444;margin-top:2px">Sin stock</div>` : ''}
          </div>
          <div style="display:flex;flex-direction:column;align-items:flex-end;gap:6px;flex-shrink:0">
            <div style="font-size:14px;font-weight:700;color:${sel ? '#22c55e' : '#f1f5f9'}">
              S/ ${Math.round(monto)}
            </div>
            <div style="width:20px;height:20px;border-radius:50%;
                        background:${sel ? '#22c55e' : 'rgba(255,255,255,.08)'};
                        border:2px solid ${sel ? '#22c55e' : 'rgba(255,255,255,.2)'};
                        display:flex;align-items:center;justify-content:center">
              ${sel ? '<span class="mi" style="font-size:12px;color:#fff">check</span>' : ''}
            </div>
          </div>
        </div>`;
    }).join('');
  },

  _toggle(id) {
    const item = this.items.find(i => i.id === id);
    if (!item) return;
    const idx  = this.seleccion.findIndex(s => s.id === id);
    if (idx >= 0) {
      this.seleccion.splice(idx, 1);
    } else {
      this.seleccion.push({
        id,
        nombre:        item.nombre,
        monto:         item.monto_colegiado || item.monto_base,
        es_mercaderia: item.es_mercaderia,
      });
    }
    this._renderItems(this.filtroActual);
    this._actualizarFooter();
  },

  _actualizarFooter() {
    const total  = this.seleccion.reduce((s, i) => s + i.monto, 0);
    const footer = $('cat-footer');
    if ($('cat-total')) $('cat-total').textContent = 'S/ ' + Math.round(total);
    if (footer) footer.style.display = this.seleccion.length > 0 ? 'flex' : 'none';
  },

  _hayMercaderia() {
    return this.seleccion.some(i => i.es_mercaderia);
  },

  pagarTarjeta() {
    if (!this.seleccion.length) return;
    const total    = Math.round(this.seleccion.reduce((s, i) => s + i.monto, 0));
    const concepto = this.seleccion.map(i => i.nombre).join(', ');
    this.cerrar();
    if ($('pl-monto'))   $('pl-monto').value = total;
    // Guardar nota de mercadería para mostrar aviso post-pago
    if (this._hayMercaderia()) {
      sessionStorage.setItem('hay_mercaderia', '1');
      sessionStorage.setItem('items_mercaderia', JSON.stringify(
        this.seleccion.filter(i => i.es_mercaderia).map(i => i.nombre)
      ));
    }
    Modales.pagoLinea.recalcular();
    Modales.pagoLinea.abrir();
  },

  reportar() {
    if (!this.seleccion.length) return;
    const total    = Math.round(this.seleccion.reduce((s, i) => s + i.monto, 0));
    const nombres  = this.seleccion.map(i => i.nombre).join(', ');
    const hayMerc  = this._hayMercaderia();
    this.cerrar();
    if ($('rp-monto'))    $('rp-monto').value    = total;
    if ($('rp-concepto')) $('rp-concepto').value  = hayMerc ? 'mercaderia' : 'otro';
    // Mostrar aviso de retiro si hay productos físicos
    const aviso = $('rp-aviso-producto');
    if (aviso) aviso.style.display = hayMerc ? 'block' : 'none';
    Modales.reportarPago.abrir();
  },
},

  /* ─── Reportar Pago ───────────────────────────────────── */
  /* ════════════════════════════════════════════════════════════
   Modales.reportarPago — REEMPLAZAR el bloque existente completo
   en portal_inactivo.js

   Nuevas funciones vs versión anterior:
   · handleFile()     → sube voucher y llama OCR automáticamente
   · _ocr()          → POST /api/portal/analizar-voucher
   · onTipoComprobante() → muestra/oculta sección Factura
   · onRucInput()    → consulta RUC con debounce 600ms
   · _consultarRuc() → GET /api/portal/ruc/{ruc}
   · Todo lo demás igual (tabs deudas, matching, enviar)
════════════════════════════════════════════════════════════ */

  reportarPago: {
    metodo:           null,
    archivo:          null,        // File object del voucher
    _idsSeleccionados: new Set(),
    _filtroActual:    null,
    _tipoComp:        null,        // 'boleta' | 'factura' | null
    _rucTimer:        null,        // debounce timer para consulta RUC
    _rucTipo:         null,        // 'natural' | 'empresa'

    _GRUPOS: {
      cuota_ordinaria:      { icon: 'receipt_long',   label: 'Cuotas Ordinarias',      color: 'c-amber'  },
      cuota_extraordinaria: { icon: 'star',           label: 'Cuotas Extraordinarias', color: 'c-blue'   },
      multa:                { icon: 'gavel',          label: 'Multas',                 color: 'c-red'    },
      fraccionamiento:      { icon: 'calendar_month', label: 'Fraccionamiento',         color: 'c-violet' },
      otros:                { icon: 'more_horiz',     label: 'Otros',                  color: 'c-dim'    },
    },

    /* ── Abrir ──────────────────────────────────────────── */
    abrir() {
      this._reset();
      this._renderContenido();
      $('modal-reporte')?.classList.add('open');
    },

    abrirConFraccion(inicial, n, cuotaMes, codigo) {
      this._reset();
      this._filtroActual = 'fraccionamiento';
      this._renderContenido();
      if ($('rp-monto'))           $('rp-monto').value           = Math.round(inicial);
      if ($('rp-fracc-cod-input')) $('rp-fracc-cod-input').value = codigo;
      if ($('rp-fracc-resumen'))
        $('rp-fracc-resumen').innerHTML =
          `<span style="color:var(--violet)">${n} cuotas · S/ ${Math.round(cuotaMes)}/mes</span>`;
      if ($('rp-fracc-codigo')) $('rp-fracc-codigo').style.display = 'block';
      this.recalcularTotal();
      $('modal-reporte')?.classList.add('open');
    },

    cerrar() { $('modal-reporte')?.classList.remove('open'); },

    _reset() {
      this.metodo           = null;
      this.archivo          = null;
      this._idsSeleccionados = new Set();
      this._filtroActual    = null;
      this._tipoComp        = null;
      this._rucTipo         = null;
      if (this._rucTimer) { clearTimeout(this._rucTimer); this._rucTimer = null; }

      // Limpiar campos estáticos
      ['rp-monto','rp-nro-op','rp-ruc','rp-razon-social','rp-direccion'].forEach(id => {
        const el = $(id); if (el) { el.value = ''; el.readOnly = false; }
      });
      document.querySelectorAll('input[name="rp-tipo-comp"]')
        .forEach(r => { r.checked = false; });
      const chk = $('rp-constancia-check'); if (chk) chk.checked = false;

      // Ocultar secciones condicionales
      ['rp-factura-datos','rp-fracc-codigo','rp-banco-row','ocr-estado'].forEach(id => {
        const el = $(id); if (el) el.style.display = 'none';
      });

      // Reset voucher UI
      if ($('voucher-label')) $('voucher-label').textContent = 'Toca para adjuntar o arrastra aquí';
      if ($('voucher-icon'))  $('voucher-icon').textContent  = 'photo_camera';
      if ($('voucher-drop'))  $('voucher-drop').style.borderColor = '';

      // Reset métodos
      document.querySelectorAll('.metodo-btn').forEach(b => b.classList.remove('active'));

      // Reset comprobante opts
      ['opt-boleta','opt-factura'].forEach(id => {
        const el = $(id); if (el) el.classList.remove('rp-comp-selected');
      });
    },

    /* ── Voucher + OCR ──────────────────────────────────── */
    handleFile(file) {
      if (!file) return;
      this.archivo = file;
      if ($('voucher-label')) $('voucher-label').textContent = '✅ ' + file.name;
      if ($('voucher-icon'))  $('voucher-icon').textContent  = 'check_circle';
      if ($('voucher-drop'))  $('voucher-drop').style.borderColor = 'var(--verde-soft)';
      this._ocr(file);
    },

    handleDrop(e) {
      e.preventDefault();
      $('voucher-drop')?.classList.remove('drag');
      const file = e.dataTransfer?.files?.[0];
      if (file) this.handleFile(file);
    },

    async _ocr(file) {
      const estado = $('ocr-estado');
      const ico    = $('ocr-ico');
      const txt    = $('ocr-txt');
      if (!estado) return;

      estado.style.display = 'flex';
      if (ico) ico.textContent = 'hourglass_empty';
      if (txt) txt.textContent = 'Analizando voucher con IA...';

      try {
        const fd = new FormData();
        fd.append('voucher', file);

        const r = await fetch('/api/portal/analizar-voucher', { method: 'POST', body: fd });
        const d = await r.json();

        if (d.ok) {
          // Pre-llenar campos con datos del OCR
          if (d.amount && $('rp-monto') && !$('rp-monto').value) {
            $('rp-monto').value = d.amount;
            this.recalcularTotal();
          }
          if (d.operation_code && $('rp-nro-op') && !$('rp-nro-op').value) {
            $('rp-nro-op').value = d.operation_code;
          }
          // Banco detectado — mostrar badge y auto-seleccionar método
          if (d.bank) {
            const bancoRow = $('rp-banco-row');
            const bancoTxt = $('rp-banco-txt');
            if (bancoRow) bancoRow.style.display = 'block';
            if (bancoTxt) bancoTxt.textContent    = d.bank;
            this._autoMetodo(d.bank);
          }
          if (ico) ico.textContent = 'check_circle';
          if (txt) txt.textContent = 'Datos extraídos — revisa y corrige si hace falta';
          ico.style.color = 'var(--emerald-soft)';
        } else {
          if (ico) ico.textContent = 'info';
          if (txt) txt.textContent = d.msg || 'Ingresa los datos manualmente';
        }
      } catch(e) {
        if (ico) ico.textContent = 'info';
        if (txt) txt.textContent = 'OCR no disponible — ingresa los datos manualmente';
      }
    },

    _autoMetodo(banco) {
      // Auto-seleccionar método según banco detectado
      const b = (banco || '').toLowerCase();
      let btn = null;
      if (b.includes('yape'))                                             btn = document.querySelector('.metodo-btn.metodo-yape');
      else if (b.includes('plin'))                                        btn = document.querySelector('.metodo-btn.metodo-plin');
      else if (b.includes('bbva')||b.includes('bcp')||b.includes('inter')) btn = document.querySelector('.metodo-btn.metodo-transf');
      if (btn) {
        const metodo = b.includes('yape') ? 'yape' : b.includes('plin') ? 'plin' : 'transferencia';
        this.setMetodo(metodo, btn);
      }
    },

    /* ── Comprobante ────────────────────────────────────── */
    onTipoComprobante(tipo) {
      this._tipoComp = tipo;
      const datos = $('rp-factura-datos');

      // Resaltar opción seleccionada
      ['opt-boleta','opt-factura'].forEach(id => {
        const el = $(id);
        if (el) el.classList.toggle('rp-comp-selected',
          (tipo === 'boleta' && id === 'opt-boleta') ||
          (tipo === 'factura' && id === 'opt-factura')
        );
      });

      if (tipo === 'factura') {
        if (datos) datos.style.display = 'block';
      } else {
        if (datos) datos.style.display = 'none';
        // Limpiar campos factura
        ['rp-ruc','rp-razon-social','rp-direccion'].forEach(id => {
          const el = $(id); if (el) { el.value = ''; el.readOnly = false; }
        });
        if ($('rp-ruc-estado')) $('rp-ruc-estado').textContent = '';
      }
    },

    /* ── Consulta RUC con debounce ──────────────────────── */
    onRucInput(ruc) {
      const estado = $('rp-ruc-estado');
      if (estado) estado.textContent = '';

      if (this._rucTimer) clearTimeout(this._rucTimer);

      if (ruc.length !== 11 || !/^\d+$/.test(ruc)) return;

      this._rucTimer = setTimeout(() => this._consultarRuc(ruc), 600);
    },

    async _consultarRuc(ruc) {
      const spin     = $('rp-ruc-spin');
      const estado   = $('rp-ruc-estado');
      const rsInput  = $('rp-razon-social');
      const dirInput = $('rp-direccion');
      const dirHint  = $('rp-dir-hint');

      if (spin)  spin.style.display  = 'inline-flex';
      if (estado) estado.textContent = 'Consultando...';

      try {
        const r = await fetch(`/api/portal/ruc/${ruc}`);
        const d = await r.json();

        this._rucTipo = d.tipo_ruc || (ruc.startsWith('10') ? 'natural' : 'empresa');

        if (spin) spin.style.display = 'none';

        if (d.ok && d.nombre) {
          // Razón social → read-only con dato de API
          if (rsInput) { rsInput.value = d.nombre; rsInput.readOnly = true; }

          // Dirección
          const esNatural = this._rucTipo === 'natural';
          if (dirInput) {
            dirInput.value    = d.direccion || '';
            // RUC 10: siempre editable. RUC 20: read-only si API devolvió dirección
            dirInput.readOnly = !esNatural && !!d.direccion;
          }
          if (dirHint) {
            dirHint.textContent = esNatural
              ? '(RUC Natural — ingresa tu dirección)'
              : (d.direccion ? '' : 'API no devolvió dirección — ingresa manualmente');
          }
          if (estado) {
            estado.textContent = `✅ ${d.estado || 'ACTIVO'} — ${d.condicion || ''}`;
            estado.style.color = 'var(--emerald-soft)';
          }
        } else {
          // API falló — todo editable
          if (rsInput)  { rsInput.value  = ''; rsInput.readOnly  = false; }
          if (dirInput) { dirInput.value = ''; dirInput.readOnly = false; }
          if (dirHint)  dirHint.textContent = 'Ingresa los datos manualmente';
          if (estado) {
            estado.textContent = d.msg || 'No encontrado — ingresa los datos manualmente';
            estado.style.color = 'var(--amber-soft)';
          }
        }
      } catch(e) {
        if (spin)   spin.style.display  = 'none';
        if (estado) estado.textContent  = 'Error de conexión — ingresa los datos manualmente';
        if ($('rp-razon-social')) { $('rp-razon-social').readOnly = false; }
        if ($('rp-direccion'))    { $('rp-direccion').readOnly    = false; }
      }
    },

    /* ── Tabs de deudas ─────────────────────────────────── */
    _renderContenido() {
      const zona = $('rp-deudas-zona');
      if (!zona) return;
      const deudas = Portal.ctx.deudas || [];
      if (!deudas.length) {
        zona.innerHTML = '<div class="rp-empty">Sin deudas registradas.</div>';
        return;
      }

      const grupos = {};
      deudas.forEach(d => {
        const tipo = (d.debt_type || 'otros').toLowerCase();
        const grp  = this._GRUPOS[tipo] ? tipo : 'otros';
        if (!grupos[grp]) grupos[grp] = [];
        grupos[grp].push(d);
      });

      const tabsHtml = Object.keys(grupos).map(grp => {
        const g = this._GRUPOS[grp];
        const activo = this._filtroActual === grp ? 'active' : '';
        return `<button class="rp-tab ${activo}"
                        onclick="Modales.reportarPago._setFiltro('${grp}')">
                  <span class="mi sm ${g.color}">${g.icon}</span>
                  ${g.label}
                  <span class="rp-tab-cnt">${grupos[grp].length}</span>
                </button>`;
      }).join('');

      const desc2026 = this._descuentoMesActual();
      const tiene2026 = deudas.some(d =>
        (d.debt_type||'').toLowerCase() === 'cuota_ordinaria' &&
        (d.periodo||'').includes('2026')
      );
      const aviso2026 = !tiene2026 ? (
        '<div class="rp-aviso-2026"><span class="mi sm c-amber">schedule</span>' +
        'Las cuotas ordinarias 2026 se habilitarán cuando el colegio las genere.' +
        (desc2026 > 0 ? ' Hay descuento del <strong>' + desc2026 + '%</strong> si pagas anticipado este mes.' : '') +
        '</div>'
      ) : '';

      zona.innerHTML = `
        <div class="rp-tabs" id="rp-tabs">${tabsHtml}</div>
        ${aviso2026}
        <div class="rp-check-all-row">
          <label class="dl-check-all" for="rp-check-all">
            <input type="checkbox" id="rp-check-all"
                   onchange="Modales.reportarPago._toggleAll(this.checked)">
            Seleccionar todas las deudas visibles
          </label>
          <span class="dl-header-cnt" id="rp-sel-cnt">0 seleccionadas</span>
        </div>
        <div class="dl-lista" id="rp-lista"></div>
      `;
      this._renderLista(this._filtroActual, grupos);
    },

    _descuentoMesActual() {
      const m = new Date().getMonth() + 1;
      return m === 1 ? 30 : m === 2 ? 20 : m === 3 ? 10 : 0;
    },

    _setFiltro(filtro) {
      this._filtroActual = filtro;
      document.querySelectorAll('.rp-tab').forEach(t => {
        t.classList.toggle('active', t.textContent.includes(this._GRUPOS[filtro]?.label || ''));
      });
      const deudas = Portal.ctx.deudas || [];
      const grupos = {};
      deudas.forEach(d => {
        const tipo = (d.debt_type || 'otros').toLowerCase();
        const grp  = this._GRUPOS[tipo] ? tipo : 'otros';
        if (!grupos[grp]) grupos[grp] = [];
        grupos[grp].push(d);
      });
      const lista = $('rp-lista');
      if (lista) {
        lista.classList.remove('rp-lista-flash');
        void lista.offsetWidth;
        lista.classList.add('rp-lista-flash');
      }
      this._renderLista(filtro, grupos);
    },

    _renderLista(filtro, grupos) {
      const lista   = $('rp-lista');
      if (!lista) return;
      const deudas  = Portal.ctx.deudas || [];
      const visibles = filtro ? (grupos[filtro] || []) : deudas;
      if (!visibles.length) {
        lista.innerHTML = '<div class="rp-empty">Sin deudas en esta categoría.</div>';
        return;
      }
      lista.innerHTML = visibles.map(deu => {
        const condona = esCondonable(deu);
        const monto   = parseFloat(deu.balance || deu.amount || 0);
        const sel     = this._idsSeleccionados.has(deu.id);
        return `
          <label class="dl-item ${sel ? 'dl-sel' : ''}" for="rp-chk-${deu.id}">
            <input type="checkbox" class="dl-chk" id="rp-chk-${deu.id}"
                   ${sel ? 'checked' : ''} value="${deu.id}" data-monto="${monto}"
                   onchange="Modales.reportarPago._toggleDeuda(${deu.id}, ${monto}, this.checked)">
            <div class="dl-info">
              <div class="dl-concept">${deu.concept || '—'}</div>
              <div class="dl-meta">${deu.period_label || deu.periodo || ''}</div>
            </div>
            <div class="dl-right">
              ${condona ? '<span class="dl-badge-condona"><span class="mi sm" style="font-size:9px">auto_awesome</span>Condonable</span>' : ''}
              <span class="dl-monto">S/ ${Math.round(monto)}</span>
            </div>
          </label>`;
      }).join('');
    },

    _toggleDeuda(id, monto, checked) {
      if (checked) this._idsSeleccionados.add(id);
      else { this._idsSeleccionados.delete(id); const ca = $('rp-check-all'); if (ca) ca.checked = false; }
      this._actualizarContador();
      this.recalcularTotal();
    },

    _toggleAll(checked) {
      document.querySelectorAll('#rp-lista .dl-chk').forEach(chk => {
        chk.checked = checked;
        const id = parseInt(chk.value);
        if (checked) this._idsSeleccionados.add(id);
        else         this._idsSeleccionados.delete(id);
      });
      this._actualizarContador();
      this.recalcularTotal();
    },

    _actualizarContador() {
      const el = $('rp-sel-cnt');
      if (el) el.textContent = this._idsSeleccionados.size + ' seleccionadas';
    },

    /* ── Recalcular total ───────────────────────────────── */
    recalcularTotal() {
      let montoBase = 0;
      if (this._idsSeleccionados.size > 0) {
        (Portal.ctx.deudas || []).forEach(d => {
          if (this._idsSeleccionados.has(d.id))
            montoBase += parseFloat(d.balance || d.amount || 0);
        });
        montoBase = Math.round(montoBase);
        if ($('rp-monto')) $('rp-monto').value = montoBase;
      } else {
        montoBase = parseFloat($('rp-monto')?.value || 0);
      }
      const addConst = $('rp-constancia-check')?.checked ? 10 : 0;
      if ($('rp-total')) $('rp-total').textContent = 'S/ ' + (Math.round(montoBase) + addConst);
    },

    setMetodo(m, btn) {
      this.metodo = m;
      document.querySelectorAll('.metodo-btn').forEach(b => b.classList.remove('active'));
      btn.classList.add('active');
    },

    /* ── Validar y enviar ───────────────────────────────── */
    async enviar() {
      const monto  = parseFloat($('rp-monto')?.value || 0);
      const nroOp  = ($('rp-nro-op')?.value || '').trim();

      if (!this.archivo) {
        alert('El voucher es obligatorio.');
        return;
      }
      if (!monto || monto <= 0) {
        alert('El monto debe ser mayor a cero.');
        $('rp-monto')?.focus();
        return;
      }
      if (!nroOp) {
        alert('El N° de operación es obligatorio.');
        $('rp-nro-op')?.focus();
        return;
      }
      if (!this.metodo) {
        alert('Selecciona el método de pago.');
        return;
      }
      if (!this._tipoComp) {
        alert('Indica si deseas Boleta o Factura.');
        return;
      }
      if (this._tipoComp === 'factura') {
        const ruc = ($('rp-ruc')?.value || '').trim();
        const rs  = ($('rp-razon-social')?.value || '').trim();
        if (!ruc || ruc.length !== 11) {
          alert('Ingresa un RUC válido de 11 dígitos.');
          $('rp-ruc')?.focus();
          return;
        }
        if (!rs) {
          alert('Ingresa la Razón Social.');
          $('rp-razon-social')?.focus();
          return;
        }
      }

      // Armar FormData
      const fd = new FormData();
      fd.append('monto',                monto);
      fd.append('nro_operacion',        nroOp);
      fd.append('metodo',               this.metodo);
      fd.append('deuda_ids',            [...this._idsSeleccionados].join(','));
      fd.append('fracc_codigo',         $('rp-fracc-cod-input')?.value || '');
      fd.append('tipo_comprobante',     this._tipoComp);
      fd.append('solicitar_constancia', $('rp-constancia-check')?.checked ? '1' : '0');
      fd.append('voucher',              this.archivo);

      if (this._tipoComp === 'factura') {
        fd.append('factura_ruc',         $('rp-ruc')?.value           || '');
        fd.append('factura_razon_social', $('rp-razon-social')?.value || '');
        fd.append('factura_direccion',   $('rp-direccion')?.value     || '');
      }

      try {
        const r = await fetch('/api/portal/reportar-pago', { method: 'POST', body: fd });
        const d = await r.json();
        this.cerrar();
        Asistente._addMsg(
          d.mensaje || '✅ Pago reportado. La caja validará tu voucher en hasta 24h.',
          'bot'
        );
      } catch(e) {
        this.cerrar();
        Asistente._addMsg('Error al enviar el reporte. Por favor intenta de nuevo.', 'bot');
      }
    },
  },

  /* ─── Pago en Línea ───────────────────────────────────── */
  pagoLinea: {

    _montoFijo:        null,    // != null → modo fraccionamiento (cuota inicial fija)
    _idsSeleccionados: new Set(),

    /* abrir(montoFijo)
       - montoFijo !== null : viene de fraccionamiento → monto fijo, sin lista
       - montoFijo === null : viene de PAGAR AHORA → lista con checkboxes        */
    abrir(montoFijo = null) {
      this._montoFijo        = montoFijo;
      this._idsSeleccionados = new Set();

      if (montoFijo !== null) {
        this._renderModoFijo(montoFijo);
      } else {
        this._renderModoLista();
      }

      // Constancia sin marcar por defecto
      const chk = $('pl-incluir-constancia');
      if (chk) chk.checked = false;

      this.recalcular();
      $('modal-pago-linea')?.classList.add('open');
    },

    cerrar() { $('modal-pago-linea')?.classList.remove('open'); },

    /* ── Modo fijo (cuota inicial de fraccionamiento) ─────── */
    _renderModoFijo(montoFijo) {
      const cuerpo = $('pl-cuerpo');
      if (!cuerpo) return;

      // Recuperar código y plan generados en fraccion.pagarConTarjeta()
      const codigo = sessionStorage.getItem('fracc_codigo') || '';
      const plan   = (() => {
        try { return JSON.parse(sessionStorage.getItem('fracc_plan') || 'null'); } catch(_) { return null; }
      })();

      const codigoHtml = codigo ? `
        <div class="pl-fracc-codigo">
          <div class="pl-fracc-codigo-head">
            <span class="mi sm c-violet">confirmation_number</span>
            Código de fraccionamiento
          </div>
          <div class="pl-fracc-codigo-val">${codigo}</div>
          <div class="pl-fracc-codigo-sub">
            ${plan ? plan.n + ' cuotas de S/ ' + Math.round(plan.cuotaMes) + '/mes · ' : ''}Guárdalo — también vale en caja
          </div>
        </div>` : '';

      cuerpo.innerHTML = codigoHtml + `
        <div class="pl-monto-fijo-card">
          <span class="mi sm c-blue">calendar_month</span>
          <div class="pl-monto-fijo-info">
            <div class="pl-monto-fijo-lbl">Cuota inicial de fraccionamiento</div>
            <div class="pl-monto-fijo-sub">Al pagar, quedas HÁBIL ese mismo día</div>
          </div>
          <div class="pl-monto-fijo-amt">S/ ${Math.round(montoFijo)}</div>
        </div>
        <input type="hidden" id="pl-monto" value="${Math.round(montoFijo)}">
      `;
    },

    /* ── Modo lista (PAGAR AHORA) ─────────────────────────── */
    _renderModoLista() {
      const cuerpo = $('pl-cuerpo');
      if (!cuerpo) return;
      const deudas = Portal.ctx.deudas || [];

      if (!deudas.length) {
        cuerpo.innerHTML = '<div style="text-align:center;color:var(--text-dim);padding:24px">Sin deudas registradas.</div>';
        return;
      }

      const rows = deudas.map(deu => {
        const condona = esCondonable(deu);
        const monto   = parseFloat(deu.balance || deu.amount || 0);
        return `
          <label class="dl-item" for="dl-chk-${deu.id}">
            <input type="checkbox" class="dl-chk" id="dl-chk-${deu.id}"
                   value="${deu.id}" data-monto="${monto}" data-condona="${condona}"
                   onchange="Modales.pagoLinea._toggleDeuda(${deu.id}, ${monto}, ${condona}, this.checked)">
            <div class="dl-info">
              <div class="dl-concept">${deu.concept || deu.concepto || '—'}</div>
              <div class="dl-meta">${deu.period_label || deu.periodo || ''}</div>
            </div>
            <div class="dl-right">
              ${condona ? `<span class="dl-badge-condona">
                             <span class="mi sm" style="font-size:10px">auto_awesome</span>
                             Condonable</span>` : ''}
              <span class="dl-monto">S/ ${Math.round(monto)}</span>
            </div>
          </label>`;
      }).join('');

      cuerpo.innerHTML = `
        <div class="dl-header">
          <label class="dl-check-all" for="pl-check-all">
            <input type="checkbox" id="pl-check-all"
                   onchange="Modales.pagoLinea._toggleAll(this.checked)">
            Seleccionar todas las deudas
          </label>
          <span class="dl-header-cnt">${deudas.length} conceptos</span>
        </div>
        <div class="dl-lista" id="pl-lista">${rows}</div>
        <div id="pl-aviso-condona" class="pl-aviso-condona" style="display:none"></div>
      `;
    },

    _toggleDeuda(id, monto, condona, checked) {
      if (checked) {
        this._idsSeleccionados.add(id);
      } else {
        this._idsSeleccionados.delete(id);
        // Desmarcar "todas"
        const chkAll = $('pl-check-all');
        if (chkAll) chkAll.checked = false;
      }
      this.recalcular();
    },

    _toggleAll(checked) {
      const deudas = Portal.ctx.deudas || [];
      document.querySelectorAll('.dl-chk').forEach(chk => { chk.checked = checked; });
      if (checked) {
        deudas.forEach(d => this._idsSeleccionados.add(d.id));
      } else {
        this._idsSeleccionados.clear();
      }
      this.recalcular();
    },

    recalcular() {
      let montoBase    = 0;
      let condonaEnSel = 0;

      if (this._montoFijo !== null) {
        // Modo fijo
        montoBase = this._montoFijo;
      } else {
        // Modo lista — sumar seleccionadas
        const deudas = Portal.ctx.deudas || [];
        deudas.forEach(d => {
          if (this._idsSeleccionados.has(d.id)) {
            const bal = parseFloat(d.balance || d.amount || 0);
            montoBase += bal;
            if (esCondonable(d)) condonaEnSel += bal;
          }
        });
      }

      // Aviso condonable en selección
      const avisoEl = $('pl-aviso-condona');
      if (avisoEl) {
        if (condonaEnSel > 0) {
          avisoEl.style.display = 'flex';
          avisoEl.innerHTML = `
            <span class="mi sm c-violet" style="flex-shrink:0">info</span>
            De tu selección, <strong style="color:var(--violet)">S/ ${Math.round(condonaEnSel)}</strong>
            se condonan automáticamente si fraccionas (Acuerdo 007-2026).
            <span class="pl-link-fracc"
                  onclick="Modales.pagoLinea.cerrar();Modales.fraccion.abrir()">
              Ver fraccionamiento
            </span>`;
        } else {
          avisoEl.style.display = 'none';
        }
      }

      const addConst = $('pl-incluir-constancia')?.checked ? 10 : 0;
      const total    = Math.round(montoBase) + addConst;
      if ($('pl-total')) $('pl-total').textContent = 'S/ ' + total.toFixed(2);

      // Habilitar/deshabilitar botón pagar
      const btnPagar = $('pl-btn-pagar');
      if (btnPagar) btnPagar.disabled = (montoBase <= 0);
    },

    async pagar() {
      let monto    = 0;
      let deudaIds = '';

      if (this._montoFijo !== null) {
        // Modo fijo — cuota inicial del fraccionamiento
        monto    = this._montoFijo;
        deudaIds = '';
      } else {
        // Modo lista — IDs seleccionados
        if (this._idsSeleccionados.size === 0) {
          alert('Selecciona al menos una deuda para pagar.');
          return;
        }
        const deudas = Portal.ctx.deudas || [];
        deudas.forEach(d => {
          if (this._idsSeleccionados.has(d.id)) {
            monto += parseFloat(d.balance || d.amount || 0);
          }
        });
        monto    = Math.round(monto);
        deudaIds = [...this._idsSeleccionados].join(',');
      }

      if (!monto || monto <= 0) {
        alert('El monto a pagar debe ser mayor a cero.');
        return;
      }

      const addConst = $('pl-incluir-constancia')?.checked ? 10 : 0;

      try {
        const r = await fetch('/pagos/openpay/iniciar', {
          method:  'POST',
          headers: { 'HX-Request': 'true', 'Content-Type': 'application/x-www-form-urlencoded' },
          body:    new URLSearchParams({
            monto_directo:      monto,
            incluir_constancia: addConst > 0 ? '1' : '0',
            deuda_ids:          deudaIds,
          }),
        });
        const hxRedir = r.headers.get('HX-Redirect');
        if (hxRedir)      { location.href = hxRedir; return; }
        if (r.redirected)  { location.href = r.url;   return; }
        const d = await r.json().catch(() => ({}));
        if (d.redirect_url) { location.href = d.redirect_url; }
        else Asistente._addMsg('Error al conectar con el procesador de pagos.', 'bot');
      } catch(e) {
        this.cerrar();
        Asistente._addMsg('Error de conexión al procesar el pago.', 'bot');
      }
    },
  },

  /* ─── Elegir tipo de pago ─────────────────────────────── */
    elegirPago: {
        abrir()  { $('modal-elegir-pago')?.classList.add('open'); },
        cerrar() { $('modal-elegir-pago')?.classList.remove('open'); },

        conTarjeta() {
            this.cerrar();
            Modales.pagoLinea.abrir();  // sin parámetro → usa montoMax
        },

        reportarPago() {
            this.cerrar();
            Modales.reportarPago.abrir();
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
    window.addEventListener('beforeinstallprompt', e => {
      e.preventDefault();
      this.deferredPrompt = e;
    });

    if (this.esIOS) {
      const iosHint = $('ios-hint');
      if (iosHint) iosHint.style.display = 'block';
    }

    document.addEventListener('mouseleave', e => {
      if (e.clientY < 5 && !this.popupMostrado) {
        setTimeout(() => this.mostrarPopup(), 300);
      }
    });

    document.addEventListener('visibilitychange', () => {
      if (document.hidden && !this.popupMostrado && this._tiempoEnPagina() > 30) {
        this.mostrarPopup();
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
    $('pwa-overlay')?.classList.add('open');
  },

  cerrarPopup() { $('pwa-overlay')?.classList.remove('open'); },

  async instalar() {
    if (this.deferredPrompt) {
      this.deferredPrompt.prompt();
      const { outcome } = await this.deferredPrompt.userChoice;
      if (outcome === 'accepted') this.deferredPrompt = null;
    } else {
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
        Asistente._addMsg('✅ ¡App instalada! Ya puedes recibir alertas y acceder más rápido.', 'bot');
      }
    } else if (this.esIOS) {
      // instrucciones ya visibles en el popup
    } else {
      this.cerrarPopup();
      Asistente._addMsg(
        'La app ya está instalada o tu navegador no soporta instalación directa. Prueba desde Chrome en Android.',
        'bot'
      );
    }
  },
};


/* ════════════════════════════════════════════════════════════
   Interceptor global de sesión expirada
════════════════════════════════════════════════════════════ */
const _fetchOrig = window.fetch.bind(window);
window.fetch = async function(...args) {
  const resp = await _fetchOrig(...args);
  if ((resp.status === 401 || resp.status === 422)) {
    const url = (typeof args[0] === 'string' ? args[0] : args[0]?.url) || '';
    if (!url.includes('/auth/')) {
      $('modal-sesion-exp')?.classList.add('open');
    }
  }
  return resp;
};


/* ════════════════════════════════════════════════════════════
   Eventos globales
════════════════════════════════════════════════════════════ */
document.querySelectorAll('.modal-overlay').forEach(ov => {
  ov.addEventListener('click', e => {
    if (e.target === ov) ov.classList.remove('open');
  });
});

document.addEventListener('change', e => {
  if (e.target.id === 'pl-incluir-constancia') Modales.pagoLinea.recalcular();
});

// Pre-cargar voces de síntesis al cargar la página
window.speechSynthesis?.getVoices();
window.speechSynthesis?.addEventListener('voiceschanged', () => window.speechSynthesis.getVoices());


/* ════════════════════════════════════════════════════════════
   BOOT
════════════════════════════════════════════════════════════ */
document.addEventListener('DOMContentLoaded', () => {
  Portal.init();
  Asistente.activarWhisper();
  PWA.init();
});