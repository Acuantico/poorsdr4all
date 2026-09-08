let token = "";
let ws = null;
let pc = null;
let currentState = {
  frequency_hz: 0,
  mode: "AM",
  band: "20m",
  bands: [],
  step_khz: 1,
  step_options_khz: [0.01, 0.1, 0.5, 1, 5, 10, 100],
  ptt: false,
  rx_volume: 1.0,
  tx_volume: 1.0,
  radio_on: true,
  audio_enabled: false,
  remote_audio_active: false,
  rx_audio_source: "radio",
  anr_enabled: false,
  anr_intensity: 3,
  anr_available: false,
};
let webrtcConnected = false;
let editingFreq = false;
let editingMode = false;
let editingBand = false;
let editingStep = false;
let editingVolume = false;
let editingAnr = false;
let lastFreqChangeAt = 0;
let lastModeChangeAt = 0;
let micStream = null;
let wsReconnectAttempts = 0;
let wsReconnectTimer = null;
let statusPollTimer = null;
let pttPending = false;
let wsConnected = false;
let pttDesiredState = false;
let pttLastToggleAt = 0;
let pttPointerHandledAt = 0;
let micTrackReady = false;
let lastPttStateChangeAt = 0;
let lastAppliedMonitorTxState = null;
let pttMicUnavailable = false;
let webrtcReconnecting = false;
let webrtcReconnectTimer = null;
let webrtcReconnectAttempts = 0;
const wsMaxReconnectDelay = 30000;
const wsReconnectBaseDelay = 1000;
const PTT_TOGGLE_DEBOUNCE_MS = 650;
const PTT_MIN_ACTIVE_MS = 0;

function applyRxMonitorState() {
  if (!audioEl) return;
  // Instant local switch: when TX is active, mute RX monitor immediately.
  const inTx = !!currentState.ptt;
  if (lastAppliedMonitorTxState === inTx) return;
  lastAppliedMonitorTxState = inTx;
  audioEl.muted = inTx;
  if (inTx) {
    audioEl.volume = 0.0;
  } else {
    audioEl.volume = 1.0;
  }
}

function applyImmediateTxIntent(targetState) {
  if (!audioEl) return;
  if (targetState) {
    audioEl.muted = true;
    audioEl.volume = 0.0;
  } else {
    // Real state will be re-applied by updateUI once backend confirms RX.
    audioEl.muted = false;
    audioEl.volume = 1.0;
  }
}

const statusEl = document.getElementById("status");
const loginSection = document.getElementById("login");
const controlsSection = document.getElementById("controls");
const pttBtn = document.getElementById("pttBtn");
const audioSessionBtn = document.getElementById("audioSessionBtn");
const freqInput = document.getElementById("freq");
const modeSelect = document.getElementById("mode");
const bandSelect = document.getElementById("bandSelect");
const stepSelect = document.getElementById("stepSelect");
const audioStatusEl = document.getElementById("audioStatus");
const pttHelpEl = document.getElementById("pttHelp");
const volRxEl = document.getElementById("volRx");
const volTxEl = document.getElementById("volTx");
const audioEl = document.getElementById("audioOut");
const anrToggleEl = document.getElementById("anrToggle");
const anrIntensityEl = document.getElementById("anrIntensity");
const freqUpBtn = document.getElementById("freqUpBtn");
const freqDownBtn = document.getElementById("freqDownBtn");

function formatFrequencyMeter(hz) {
  const digits = String(Math.max(0, Number(hz || 0))).padStart(7, "0");
  const mhz = digits.slice(0, -6) || "0";
  const khz = digits.slice(-6, -3);
  const hzTail = digits.slice(-3);
  return `${mhz}.${khz}.${hzTail}`;
}

function formatFrequencyLabel(hz) {
  return `${formatFrequencyMeter(hz)} Hz`;
}

function parseFrequencyHz(raw) {
  const text = String(raw || "").trim().replace(/\s+/g, "").replace(/,/g, ".");
  if (!text) return 0;
  const compact = text.replace(/\./g, "");
  if (/^\d{5,9}$/.test(compact)) {
    return Number(compact);
  }
  const num = Number(text);
  if (Number.isNaN(num)) return 0;
  if (text.includes(".")) {
    return Math.round(num * 1e6);
  }
  if (num < 1000) {
    return Math.round(num * 1e6);
  }
  if (num < 1_000_000) {
    return Math.round(num * 1000);
  }
  return Math.round(num);
}

async function api(path, method = "GET", body = null) {
  const headers = { "Content-Type": "application/json" };
  if (token) headers.Authorization = `Bearer ${token}`;
  const res = await fetch(path, {
    method,
    headers,
    body: body ? JSON.stringify(body) : null,
  });
  if (!res.ok) {
    throw new Error(await res.text());
  }
  return res.json();
}

function cleanupAudioResources() {
  if (micStream) {
    micStream.getTracks().forEach((track) => track.stop());
    micStream = null;
  }
  if (audioEl && audioEl.srcObject) {
    audioEl.srcObject.getTracks().forEach((track) => track.stop());
    audioEl.srcObject = null;
    audioEl.pause();
  }
}

function syncSelectOptions(select, values, formatter = (value) => value) {
  const wanted = values.map((value) => String(value));
  const current = Array.from(select.options).map((opt) => opt.value);
  if (JSON.stringify(current) === JSON.stringify(wanted)) {
    return;
  }
  select.innerHTML = "";
  values.forEach((value) => {
    const option = document.createElement("option");
    option.value = String(value);
    option.textContent = formatter(value);
    select.appendChild(option);
  });
}

function updateUI(state) {
  const prevPtt = !!currentState.ptt;
  currentState = { ...currentState, ...state };

  document.getElementById("freqLabel").textContent = formatFrequencyLabel(currentState.frequency_hz);

  const now = Date.now();
  if (!editingFreq && now - lastFreqChangeAt > 120) {
    const newFreq = formatFrequencyMeter(currentState.frequency_hz);
    if (freqInput.value !== newFreq) {
      freqInput.value = newFreq;
    }
  }
  if (!editingMode && now - lastModeChangeAt > 800 && modeSelect.value !== (currentState.mode || "AM")) {
    modeSelect.value = currentState.mode || "AM";
  }

  syncSelectOptions(stepSelect, currentState.step_options_khz || [0.01, 0.1, 0.5, 1, 5, 10, 100], (value) => `${value} kHz`);
  syncSelectOptions(bandSelect, currentState.bands || [], (value) => value);

  if (!editingStep) {
    stepSelect.value = String(currentState.step_khz ?? 1);
  }
  if (!editingBand) {
    bandSelect.value = String(currentState.band || "");
  }

  document.getElementById("modeLabel").textContent = currentState.mode || "--";
  document.getElementById("radioLabel").textContent = currentState.ptt ? "TX" : "RX";
  pttBtn.textContent = currentState.ptt ? "Pasar a RX" : "Pasar a TX";
  pttBtn.classList.toggle("ptt-tx", !!currentState.ptt);
  pttBtn.classList.toggle("ptt-rx", !currentState.ptt);
  if (currentState.ptt && pttMicUnavailable) {
    pttHelpEl.textContent = "Transmitiendo sin microfono (revisa permisos/HTTPS para enviar audio)";
  } else {
    pttHelpEl.textContent = currentState.ptt
      ? "La radio esta transmitiendo"
      : "La radio esta en recepcion";
  }

  if (!editingVolume) {
    volRxEl.value = Number(currentState.rx_volume ?? 1.0);
    volTxEl.value = Number(currentState.tx_volume ?? 1.0);
  }
  anrToggleEl.disabled = !currentState.anr_available;
  anrIntensityEl.disabled = !currentState.anr_available;
  if (!editingAnr) {
    anrToggleEl.checked = !!currentState.anr_enabled;
    anrIntensityEl.value = Number(currentState.anr_intensity ?? 3);
  }

  audioSessionBtn.textContent = webrtcConnected ? "Desconectar audio" : "Conectar audio";
  if (webrtcReconnecting) {
    // No pisar el aviso de scheduleWebrtcReconnect(): el push de estado
    // por WebSocket llega cada 30 ms y sobrescribiría este texto.
  } else if (webrtcConnected) {
    audioStatusEl.textContent = currentState.ptt
      ? "WebRTC conectado, enviando microfono a la radio"
      : "WebRTC conectado, reproduciendo RX";
    if (!micTrackReady) {
      audioStatusEl.textContent = "WebRTC conectado sin microfono (TX no disponible)";
    }
  } else if (currentState.remote_audio_active) {
    audioStatusEl.textContent = "Sesion remota activa";
  } else if (currentState.audio_enabled) {
    audioStatusEl.textContent = "Audio local activo";
  } else {
    audioStatusEl.textContent = "WebRTC desconectado";
  }

  if (!pttPending) {
    pttBtn.disabled = !currentState.radio_on;
  }
  if ("ptt" in state && !!currentState.ptt !== prevPtt) {
    lastPttStateChangeAt = Date.now();
  }
  applyRxMonitorState();
  statusEl.textContent = currentState.radio_on ? "Conectado" : "Sin radio";
}

async function refreshStatus() {
  if (!token) return;
  try {
    const state = await api("/api/status");
    updateUI(state);
  } catch (err) {
    console.error("Status refresh error:", err);
  }
}

async function login() {
  const username = document.getElementById("user").value.trim();
  const password = document.getElementById("pass").value;
  const otp = document.getElementById("otp").value.trim();
  try {
    const data = await api("/api/auth/login", "POST", { username, password, otp });
    token = data.token;
    loginSection.classList.add("hidden");
    controlsSection.classList.remove("hidden");
    document.getElementById("loginError").textContent = "";
    await refreshStatus();
    startWs();
    if (statusPollTimer) clearInterval(statusPollTimer);
    // Fallback poll only when WS is disconnected.
    statusPollTimer = setInterval(() => {
      if (!wsConnected) {
        refreshStatus();
      }
    }, 2000);
  } catch (_err) {
    document.getElementById("loginError").textContent = "Login incorrecto";
  }
}

function startWs() {
  wsConnected = false;
  if (ws) {
    ws.onclose = null;
    ws.close();
  }
  if (wsReconnectTimer) {
    clearTimeout(wsReconnectTimer);
    wsReconnectTimer = null;
  }
  const tokenParam = token ? `?token=${encodeURIComponent(token)}` : "";
  const wsUrl = `${location.origin.replace("http", "ws")}/api/ws${tokenParam}`;
  ws = new WebSocket(wsUrl);
  ws.onopen = () => {
    wsConnected = true;
    wsReconnectAttempts = 0;
    statusEl.textContent = "Conectado";
  };
  ws.onmessage = (evt) => {
    try {
      const msg = JSON.parse(evt.data);
      if (msg.type === "state") {
        updateUI(msg.data);
      } else if (msg.type !== "ping") {
        updateUI(msg);
      }
    } catch (err) {
      console.error("WebSocket parse error:", err);
    }
  };
  ws.onclose = () => {
    wsConnected = false;
    statusEl.textContent = "Desconectado";
    wsReconnectAttempts += 1;
    const delay = Math.min(
      wsReconnectBaseDelay * Math.pow(2, wsReconnectAttempts - 1),
      wsMaxReconnectDelay,
    );
    wsReconnectTimer = setTimeout(() => {
      if (token) startWs();
    }, delay);
  };
}

function scheduleWebrtcReconnect(graceMs = 3000) {
  if (webrtcReconnecting || !webrtcConnected) return;
  webrtcReconnecting = true;
  audioStatusEl.textContent = "Audio remoto desconectado, reconectando...";
  if (webrtcReconnectTimer) clearTimeout(webrtcReconnectTimer);
  // "disconnected" puede ser un corte breve de ICE que se recupera solo;
  // solo se fuerza una renegociación completa si sigue caído pasado el
  // plazo de gracia (o de inmediato si ya está "failed"/"closed").
  const immediate = pc ? pc.connectionState !== "disconnected" : true;
  webrtcReconnectTimer = setTimeout(
    async () => {
      webrtcReconnecting = false;
      if (pc && pc.connectionState === "connected") return; // se recuperó solo
      webrtcReconnectAttempts += 1;
      webrtcConnected = false; // fuerza que connectWebRTC() negocie de cero
      micTrackReady = false;
      if (pc) {
        pc.onconnectionstatechange = null;
        pc.ontrack = null;
        try {
          pc.close();
        } catch (err) {
          console.error("Error closing stale peer connection:", err);
        }
        pc = null;
      }
      try {
        await connectWebRTC();
      } catch (err) {
        console.error("WebRTC auto-reconnect failed:", err);
        audioStatusEl.textContent = "Audio remoto desconectado (reintento fallido)";
        // Reintenta con retroceso exponencial en vez de dejarlo muerto.
        const delay = Math.min(1000 * Math.pow(2, webrtcReconnectAttempts), 15000);
        webrtcConnected = true; // para que la siguiente llamada vuelva a programar
        webrtcReconnectTimer = setTimeout(() => scheduleWebrtcReconnect(0), delay);
      }
    },
    immediate ? 0 : graceMs,
  );
}

async function connectWebRTC() {
  if (webrtcConnected) {
    // Desconexión manual: cancelar cualquier reconexión automática pendiente
    // para no reabrir la sesión sola justo después de que el usuario la
    // haya cerrado a propósito.
    webrtcReconnecting = false;
    webrtcReconnectAttempts = 0;
    if (webrtcReconnectTimer) {
      clearTimeout(webrtcReconnectTimer);
      webrtcReconnectTimer = null;
    }
    if (currentState.ptt) {
      try {
        await api("/api/ptt", "POST", { state: false });
      } catch (err) {
        console.error("Error disabling PTT on disconnect:", err);
      }
    }
    if (pc) {
      pc.onconnectionstatechange = null;
      pc.ontrack = null;
      pc.close();
      pc = null;
    }
    webrtcConnected = false;
    micTrackReady = false;
    cleanupAudioResources();
    await refreshStatus();
    return;
  }

  pc = new RTCPeerConnection();
  // Si el DTLS/ICE se cae en mitad de una sesión, detecta la caída y
  // reconecta solo — sin esto, webrtcConnected se quedaría a true, la UI
  // seguiría diciendo "conectado" y el audio no volvería sin cerrar
  // sesión y reconectar a mano.
  pc.onconnectionstatechange = () => {
    if (!pc) return;
    const state = pc.connectionState;
    if (state === "failed" || state === "disconnected" || state === "closed") {
      scheduleWebrtcReconnect();
    } else if (state === "connected") {
      webrtcReconnectAttempts = 0;
    }
  };
  pc.ontrack = (event) => {
    const stream = event.streams && event.streams[0]
      ? event.streams[0]
      : new MediaStream([event.track]);
    if (audioEl.srcObject) {
      audioEl.srcObject.getTracks().forEach((track) => track.stop());
    }
    audioEl.srcObject = stream;
    audioEl.muted = false;
    audioEl.volume = 1.0;
    audioEl.play().catch((err) => {
      console.error("Audio play error:", err);
    });
  };

  let micTrack = null;
  micTrackReady = false;
  try {
    if (window.isSecureContext && navigator.mediaDevices && navigator.mediaDevices.getUserMedia) {
      try {
        micStream = await navigator.mediaDevices.getUserMedia({
          audio: {
            channelCount: 1,
            sampleRate: 48000,
            latency: 0,
            echoCancellation: true,
            noiseSuppression: false,
            autoGainControl: false,
          },
        });
      } catch (_strictErr) {
        // Fallback for devices/browsers that reject strict constraints.
        micStream = await navigator.mediaDevices.getUserMedia({ audio: true });
      }
      micTrack = micStream.getAudioTracks()[0] || null;
      micTrackReady = !!micTrack;
    }
  } catch (err) {
    console.error("Microphone capture error:", err);
    micTrackReady = false;
  }

  if (micTrack) {
    micTrack.enabled = true;
    try {
      pc.addTrack(micTrack, micStream);
    } catch (err) {
      console.error("Error attaching microphone track:", err);
      micTrackReady = false;
    }
  } else {
    pc.addTransceiver("audio", { direction: "recvonly" });
  }

  const offer = await pc.createOffer();
  await pc.setLocalDescription(offer);
  // Keep offer setup ultra-fast on LAN; do not block UI/audio start.
  await waitForIceGatheringComplete(pc, 40);
  const answer = await api("/api/webrtc/offer", "POST", {
    sdp: pc.localDescription.sdp,
    type: pc.localDescription.type,
  });
  await pc.setRemoteDescription(answer);
  webrtcConnected = true;
  applyRxMonitorState();
  audioEl.play().catch(() => {});
  await refreshStatus();
}

async function ensureWebRtcMicReady() {
  if (webrtcConnected && micTrackReady) {
    return true;
  }
  if (!webrtcConnected) {
    await connectWebRTC();
    return !!micTrackReady;
  }
  // Connected but no mic track: force renegotiation.
  await connectWebRTC();
  await connectWebRTC();
  return !!micTrackReady;
}

function waitForIceGatheringComplete(peer, timeoutMs = 120) {
  if (!peer || peer.iceGatheringState === "complete") {
    return Promise.resolve();
  }
  return new Promise((resolve) => {
    let finished = false;
    const done = () => {
      if (finished) return;
      finished = true;
      clearTimeout(timer);
      peer.removeEventListener("icegatheringstatechange", onChange);
      resolve();
    };
    const onChange = () => {
      if (peer.iceGatheringState === "complete") {
        done();
      }
    };
    const timer = setTimeout(done, Math.max(50, Number(timeoutMs || 3000)));
    peer.addEventListener("icegatheringstatechange", onChange);
    onChange();
  });
}

async function setFrequency(raw) {
  const hz = parseFrequencyHz(raw);
  if (!hz) return;
  lastFreqChangeAt = Date.now();
  updateUI({ frequency_hz: hz });
  try {
    await api("/api/tune", "POST", { frequency: hz });
  } catch (err) {
    console.error("Error tuning frequency:", err);
  }
}

async function setPttState(targetState) {
  targetState = !!targetState;
  if (targetState === !!currentState.ptt && !pttPending) {
    return;
  }
  if (targetState === pttDesiredState) {
    return;
  }
  pttDesiredState = targetState;
  if (pttPending) return;
  try {
    pttPending = true;
    pttBtn.disabled = true;
    if (targetState) {
      // Nunca debe bloquear el armado del PTT: si la negociación WebRTC
      // falla (mic denegado, sin HTTPS/localhost, error del servidor al
      // negociar /api/webrtc/offer...) se arma igual el PTT sin audio TX,
      // en vez de abortar toda la función antes de llamar a /api/ptt.
      let ready = false;
      try {
        ready = await ensureWebRtcMicReady();
      } catch (err) {
        console.error("PTT: WebRTC negotiation failed, keying without TX audio:", err);
      }
      pttMicUnavailable = !ready;
      if (!ready) {
        console.error("PTT: microphone track is not available, keying without TX audio");
      }
    } else if (PTT_MIN_ACTIVE_MS > 0 && currentState.ptt && (Date.now() - lastPttStateChangeAt) < PTT_MIN_ACTIVE_MS) {
      // Guard against accidental immediate TX->RX bounces on mobile.
      return;
    } else {
      pttMicUnavailable = false;
    }
    updateUI({ ptt: targetState });
    const result = await api("/api/ptt", "POST", { state: targetState });
    if (!result?.applied) {
      await refreshStatus();
    }
    applyRxMonitorState();
  } catch (err) {
    console.error("Error toggling PTT:", err);
    await refreshStatus();
  } finally {
    pttPending = false;
    pttBtn.disabled = !currentState.radio_on;
  }
}

document.getElementById("loginBtn").onclick = login;
document.getElementById("tuneBtn")?.remove();

const onPttToggle = (event) => {
  event.preventDefault();
  const now = Date.now();
  if (now - pttLastToggleAt < PTT_TOGGLE_DEBOUNCE_MS) {
    return;
  }
  pttLastToggleAt = now;
  const target = !currentState.ptt;
  applyImmediateTxIntent(target);
  setPttState(target).catch((err) => {
    console.error("Error toggling PTT:", err);
    applyRxMonitorState();
  });
};
if (window.PointerEvent) {
  pttBtn.addEventListener("pointerup", (event) => {
    pttPointerHandledAt = Date.now();
    onPttToggle(event);
  });
} else {
  pttBtn.addEventListener("click", (event) => {
    if (Date.now() - pttPointerHandledAt < 700) {
      event.preventDefault();
      return;
    }
    onPttToggle(event);
  });
}
audioSessionBtn.onclick = () => {
  connectWebRTC().catch((err) => {
    console.error("WebRTC connection error:", err);
  });
};

modeSelect.onchange = async () => {
  editingMode = true;
  lastModeChangeAt = Date.now();
  updateUI({ mode: modeSelect.value });
  try {
    await api("/api/mode", "POST", { mode: modeSelect.value });
  } catch (err) {
    console.error("Error changing mode:", err);
  } finally {
    editingMode = false;
  }
};

bandSelect.onchange = async () => {
  editingBand = true;
  try {
    await api("/api/band", "POST", { band: bandSelect.value });
  } catch (err) {
    console.error("Error changing band:", err);
  } finally {
    editingBand = false;
  }
};

stepSelect.onchange = async () => {
  editingStep = true;
  // Refleja la elección al momento, igual que modeSelect/bandSelect: los
  // botones +/- de sintonía usan currentState.step_khz para su
  // incremento, así que debe quedar actualizado de inmediato.
  updateUI({ step_khz: Number(stepSelect.value) });
  try {
    await api("/api/step", "POST", { step_khz: Number(stepSelect.value) });
  } catch (err) {
    console.error("Error changing step:", err);
  } finally {
    editingStep = false;
  }
};

async function sendVolume() {
  // Igual que band/step/mode: mientras dure la petición (y el estado del
  // servidor no haya recogido el nuevo valor), el push de estado por
  // WebSocket llega cada 30 ms y si no se protege, revierte visualmente
  // el slider antes de que la respuesta llegue ("no responde").
  editingVolume = true;
  try {
    await api("/api/volume", "POST", {
      rx: parseFloat(volRxEl.value),
      tx: parseFloat(volTxEl.value),
    });
  } catch (err) {
    console.error("Error setting volume:", err);
  } finally {
    editingVolume = false;
  }
}

volRxEl.onchange = sendVolume;
volTxEl.onchange = sendVolume;

anrToggleEl.onchange = async () => {
  editingAnr = true;
  const enabled = !!anrToggleEl.checked;
  updateUI({ anr_enabled: enabled });
  try {
    await api("/api/anr", "POST", {
      enabled,
      intensity: parseInt(anrIntensityEl.value, 10),
    });
  } catch (err) {
    console.error("Error toggling ANR:", err);
    await refreshStatus();
  } finally {
    editingAnr = false;
  }
};

anrIntensityEl.onchange = async () => {
  editingAnr = true;
  const intensity = Math.max(1, Math.min(10, parseInt(anrIntensityEl.value, 10) || 1));
  updateUI({ anr_intensity: intensity });
  try {
    await api("/api/anr", "POST", { intensity });
  } catch (err) {
    console.error("Error setting ANR intensity:", err);
    await refreshStatus();
  } finally {
    editingAnr = false;
  }
};

freqInput.addEventListener("focus", () => {
  editingFreq = true;
});
freqInput.addEventListener("blur", () => {
  editingFreq = false;
  setFrequency(freqInput.value);
});
freqInput.addEventListener("keydown", (event) => {
  if (event.key === "Enter") {
    event.preventDefault();
    freqInput.blur();
  }
});
freqInput.addEventListener("wheel", (event) => {
  event.preventDefault();
  const delta = event.deltaY < 0 ? 1 : -1;
  const next = Math.max(0, Number(currentState.frequency_hz || 0) + delta * Math.round(Number(currentState.step_khz || 1) * 1000));
  setFrequency(next);
}, { passive: false });

freqUpBtn.onclick = () => {
  const stepHz = Math.round(Number(currentState.step_khz || 1) * 1000);
  const next = Math.max(0, Number(currentState.frequency_hz || 0) + stepHz);
  setFrequency(next);
};

freqDownBtn.onclick = () => {
  const stepHz = Math.round(Number(currentState.step_khz || 1) * 1000);
  const next = Math.max(0, Number(currentState.frequency_hz || 0) - stepHz);
  setFrequency(next);
};

function cleanupAll() {
  wsConnected = false;
  if (wsReconnectTimer) {
    clearTimeout(wsReconnectTimer);
    wsReconnectTimer = null;
  }
  if (statusPollTimer) {
    clearInterval(statusPollTimer);
    statusPollTimer = null;
  }
  if (ws) {
    ws.onclose = null;
    ws.close();
    ws = null;
  }
  if (pc) {
    pc.ontrack = null;
    pc.close();
    pc = null;
  }
  cleanupAudioResources();
}

window.addEventListener("beforeunload", cleanupAll);
