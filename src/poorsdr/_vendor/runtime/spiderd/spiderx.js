/*
 * spider DX Cluster overlay plugin for OpenWebRX+
 * Robust build for PoorSDR4
 */

Plugins.spider = Plugins.spider || {};
Plugins.spider._version = 2.0;

Plugins.spider.init = function () {
  function uniqUrls(list) {
    var seen = {};
    var out = [];
    for (var i = 0; i < list.length; i++) {
      var url = list[i];
      if (!url || seen[url]) continue;
      seen[url] = true;
      out.push(url);
    }
    return out;
  }

  function buildDefaultWsUrls() {
    var host = location.host;
    var hostname = location.hostname;
    var scheme = (location.protocol === 'https:' ? 'wss://' : 'ws://');
    var urls = [];

    var targetHost = (window.location.hostname==="localhost") ? "127.0.0.1" : window.location.hostname;
    urls.push('ws://' + targetHost + ':7373/spots');
    urls.push('ws://' + targetHost + ':7390/spots');
    urls.push((window.location.protocol === "https:" ? "wss://" : "ws://") + targetHost + ":7373/spots");
    urls.push((window.location.protocol === "https:" ? "wss://" : "ws://") + targetHost + ":7390/spots");

    return uniqUrls(urls);
  }

  var defaults = {
    ws_url: null,
    ws_urls: null,
    max_age_sec: 420,
    modes: ['CW', 'SSB', 'FT8', 'DIG', 'DIGI', 'UNKNOWN'],
    enabled: true,
    max_spots: 1200
  };

  function getServerEnabled() {
    if (window.owrx_config && typeof window.owrx_config.spider_enabled === 'boolean') {
      return window.owrx_config.spider_enabled;
    }
    // In recent OpenWebRX builds custom keys may not be exposed client-side.
    // Keep UI toggle available and assume enabled unless server says otherwise.
    return true;
  }

  function loadConfig() {
    var globalCfg = (typeof window.spider_config_global === 'object') ? window.spider_config_global : {};
    var localCfg = {};
    try {
      var raw = localStorage.getItem('spider_config');
      if (raw) localCfg = JSON.parse(raw);
    } catch (e) {
      console.warn('spider: invalid localStorage config');
    }

    var cfg = $.extend({}, defaults, globalCfg, localCfg);
    if (!Array.isArray(cfg.modes)) cfg.modes = defaults.modes.slice();
    cfg.modes = cfg.modes.map(function (m) { return String(m).toUpperCase(); });
    cfg.max_age_sec = Math.max(10, parseInt(cfg.max_age_sec, 10) || defaults.max_age_sec);
    cfg.max_spots = Math.max(50, parseInt(cfg.max_spots, 10) || defaults.max_spots);
    if (!cfg.ws_url) {
      var urls = buildDefaultWsUrls();
      cfg.ws_url = urls[0];
      cfg.ws_urls = urls;
    }
    cfg.ws_url = String(cfg.ws_url || '');
    if (Array.isArray(cfg.ws_urls)) {
      cfg.ws_urls = uniqUrls(cfg.ws_urls.map(function (u) { return String(u || ''); }));
    }
    cfg.enabled = cfg.enabled !== false;
    return cfg;
  }

  var state = {
    cfg: loadConfig(),
    canvas: null,
    ctx: null,
    dpr: window.devicePixelRatio || 1,
    spots: [],
    ws: null,
    wsUrls: null,
    wsUrlIndex: 0,
    wsBackoff: 1000,
    running: false,
    renderPending: false,
    renderTimer: null,
    lastSize: { w: 0, h: 0 },
    settingsCheckbox: null,
    serverEnabled: getServerEnabled(),
    enabled: false
  };

  function isOwrxReady() {
    if (!getWaterfallContainer()) return false;
    if (typeof get_visible_freq_range === 'function' && typeof scale_px_from_freq === 'function') return true;
    if (typeof waterfallWidth === 'function') return true;
    if (typeof center_freq === 'number' && typeof bandwidth === 'number' && bandwidth > 0) return true;
    return false;
  }

  function getWaterfallContainer() {
    var selectors = [
      '#webrx-canvas-container',
      '#openwebrx-canvas-container',
      '#openwebrx-waterfall-container',
      '.openwebrx-waterfall-container',
      '#waterfall-container',
      '.waterfall-container'
    ];
    for (var i = 0; i < selectors.length; i++) {
      var node = document.querySelector(selectors[i]);
      if (node) return node;
    }
    return null;
  }

  function ensureOverlay() {
    if (state.canvas) return true;

    var container = getWaterfallContainer();
    if (!container) return false;
    if (!container.style.position || container.style.position === 'static') {
      container.style.position = 'relative';
    }

    var canvas = document.createElement('canvas');
    canvas.id = 'openwebrx-spider-overlay';
    canvas.className = 'openwebrx-spider-overlay';
    canvas.setAttribute('aria-hidden', 'true');

    container.appendChild(canvas);
    state.canvas = canvas;
    state.ctx = canvas.getContext('2d');

    resizeCanvas();

    window.addEventListener('resize', resizeCanvas);
    $(document).on('event:waterfall_resized', resizeCanvas);

    return true;
  }

  function resizeCanvas() {
    if (!state.canvas) return;
    var container = getWaterfallContainer();
    if (!container) return;

    var w = (typeof waterfallWidth === 'function') ? waterfallWidth() : 0;
    if (!w) w = container.clientWidth;
    var h = container.clientHeight;
    if (!w || !h) return;

    state.dpr = window.devicePixelRatio || 1;
    state.canvas.width = Math.round(w * state.dpr);
    state.canvas.height = Math.round(h * state.dpr);
    state.canvas.style.width = w + 'px';
    state.canvas.style.height = h + 'px';
    syncOverlayPosition();
    state.ctx.setTransform(state.dpr, 0, 0, state.dpr, 0, 0);
    state.lastSize.w = w;
    state.lastSize.h = h;
  }

  function syncOverlayPosition() {
    if (!state.canvas) return;
    if (typeof zoom_offset_px === 'number') {
      state.canvas.style.left = (-zoom_offset_px) + 'px';
    } else {
      state.canvas.style.left = '0px';
    }
  }

  function uniqNumbers(values) {
    var out = [];
    var seen = {};
    for (var i = 0; i < values.length; i++) {
      var n = Number(values[i]);
      if (!isFinite(n)) continue;
      var key = String(n);
      if (seen[key]) continue;
      seen[key] = true;
      out.push(n);
    }
    return out;
  }

  function parseRange(raw) {
    if (!raw) return null;
    var lo = null;
    var hi = null;
    if (Array.isArray(raw) && raw.length >= 2) {
      lo = Number(raw[0]);
      hi = Number(raw[1]);
    } else if (typeof raw === 'object') {
      var loKeys = ['start', 'from', 'low', 'min', 'left', 'lo'];
      var hiKeys = ['end', 'to', 'high', 'max', 'right', 'hi'];
      for (var i = 0; i < loKeys.length; i++) {
        if (raw[loKeys[i]] !== undefined) { lo = Number(raw[loKeys[i]]); break; }
      }
      for (var j = 0; j < hiKeys.length; j++) {
        if (raw[hiKeys[j]] !== undefined) { hi = Number(raw[hiKeys[j]]); break; }
      }
    }
    if (!isFinite(lo) || !isFinite(hi) || hi <= lo) return null;
    return { lo: lo, hi: hi };
  }

  function centerFreqCandidates() {
    var out = [];

    function pushScaled(v) {
      var n = Number(v);
      if (!isFinite(n)) return;
      out.push(n);
      out.push(n / 1000);
      out.push(n / 1000000);
    }

    try { if (typeof window.center_freq === 'number') pushScaled(window.center_freq); } catch (_e1) {}
    try { if (typeof window.UI !== 'undefined' && window.UI && typeof window.UI.getCenterFrequency === 'function') pushScaled(window.UI.getCenterFrequency()); } catch (_e2) {}
    try {
      if (typeof window.UI !== 'undefined' && window.UI && typeof window.UI.getFrequency === 'function') {
        var f = Number(window.UI.getFrequency());
        var off = 0;
        if (typeof window.UI.getOffsetFrequency === 'function') off = Number(window.UI.getOffsetFrequency()) || 0;
        if (isFinite(f) && isFinite(off)) pushScaled(f - off);
      }
    } catch (_e3) {}

    return uniqNumbers(out);
  }

  function classifyMode(mode) {
    var m = (mode || '').toUpperCase();
    if (m.indexOf('CW') >= 0) return 'CW';
    if (m.indexOf('SSB') >= 0 || m.indexOf('USB') >= 0 || m.indexOf('LSB') >= 0 || m.indexOf('AM') >= 0 || m.indexOf('FM') >= 0) return 'SSB';
    if (m === 'UNK' || m === 'UNKNOWN' || m === 'PHONE' || m === 'PH' || m === 'FONIA' || m === 'VOICE') return 'SSB';
    if (m.indexOf('FT8') >= 0 || m.indexOf('FT4') >= 0 || m.indexOf('RTTY') >= 0 || m.indexOf('PSK') >= 0 || m.indexOf('DIGI') >= 0 || m === 'DIG') return 'FT8';
    // Unknown/non-standard modes from DX feeds are treated as phone/SSB.
    return 'SSB';
  }

  function colorForMode(mode) {
    var m = classifyMode(mode);
    if (m === 'CW') return '#7dfffd';
    if (m === 'SSB') return '#ffe600';
    return '#ff2bd6';
  }

  function modePriority(mode) {
    var m = classifyMode(mode);
    if (m === 'SSB') return 0;
    if (m === 'CW') return 1;
    return 2;
  }

  function frequencyToX(freqHz) {
    var width = state.canvas ? state.canvas.clientWidth : 0;
    if (!width) {
      try { width = (typeof waterfallWidth === 'function') ? waterfallWidth() : 0; } catch (_eW) {}
    }
    if (!width) return null;

    var freqVariants = uniqNumbers([Number(freqHz), Number(freqHz) / 1000, Number(freqHz) / 1000000]);
    if (!freqVariants.length) return null;

    var range = null;
    try {
      if (typeof get_visible_freq_range === 'function') range = parseRange(get_visible_freq_range());
    } catch (_eR) {}

    if (range && isFinite(range.lo) && isFinite(range.hi) && range.hi > range.lo) {
      var span = range.hi - range.lo;
      function mapVal(v) {
        var x = ((v - range.lo) / span) * width;
        return (isFinite(x) && x > -5000 && x < (width + 5000)) ? x : null;
      }

      for (var i = 0; i < freqVariants.length; i++) {
        var direct = mapVal(freqVariants[i]);
        if (direct !== null) return direct;
      }

      var centers = centerFreqCandidates();
      for (var c = 0; c < centers.length; c++) {
        for (var f = 0; f < freqVariants.length; f++) {
          var rel = mapVal(freqVariants[f] - centers[c]);
          if (rel !== null) return rel;
        }
      }
    }

    if (typeof center_freq === 'number' && typeof bandwidth === 'number' && bandwidth > 0) {
      var start = center_freq - bandwidth / 2;
      for (var k = 0; k < freqVariants.length; k++) {
        var x2 = ((freqVariants[k] - start) / bandwidth) * width;
        if (isFinite(x2)) return x2;
      }
    }

    return null;
  }

  function pruneSpots(now) {
    var maxAge = state.cfg.max_age_sec;
    if (!state.spots.length) return;
    state.spots = state.spots.filter(function (s) {
      return (now - s.time) <= maxAge;
    });
  }

  function scheduleRender() {
    if (state.renderPending) return;
    state.renderPending = true;
    window.requestAnimationFrame(render);
  }

  function drawLabelBackground(ctx, x, y, w, h, radius) {
    var r = Math.max(0, Math.min(radius, Math.min(w, h) / 2));
    ctx.beginPath();
    ctx.moveTo(x + r, y);
    ctx.lineTo(x + w - r, y);
    ctx.quadraticCurveTo(x + w, y, x + w, y + r);
    ctx.lineTo(x + w, y + h - r);
    ctx.quadraticCurveTo(x + w, y + h, x + w - r, y + h);
    ctx.lineTo(x + r, y + h);
    ctx.quadraticCurveTo(x, y + h, x, y + h - r);
    ctx.lineTo(x, y + r);
    ctx.quadraticCurveTo(x, y, x + r, y);
    ctx.closePath();
  }

  function getClipArea(cssW, cssH) {
    // Some OpenWebRX themes/panel layouts report overlapping rectangles that
    // collapse clip height to 0, hiding all spider spots. Keep full canvas.
    return { w: cssW, h: cssH };
  }

  function render() {
    state.renderPending = false;
    if (!state.canvas || !state.ctx) return;
    if (!isOwrxReady()) {
      scheduleRender();
      return;
    }

    syncServerConfig();

    var ctx = state.ctx;
    var cssW = state.canvas.clientWidth;
    var cssH = state.canvas.clientHeight;
    if (!cssW || !cssH) return;

    if (cssW !== state.lastSize.w || cssH !== state.lastSize.h) resizeCanvas();
    syncOverlayPosition();

    ctx.clearRect(0, 0, cssW, cssH);

    if (!state.enabled) return;

    var now = Math.floor(Date.now() / 1000);
    pruneSpots(now);

    if (!state.spots.length) return;

    var allowedModes = state.cfg.modes;
    var maxAge = state.cfg.max_age_sec;

    var spots = state.spots.slice();
    // Prioritize phone spots so they stay visible even with heavy DIGI traffic.
    spots.sort(function (a, b) {
      var pa = modePriority(a.mode);
      var pb = modePriority(b.mode);
      if (pa !== pb) return pa - pb;
      return b.time - a.time;
    });

    var labelLanes = [];
    var maxLanes = 9;
    var labelCount = 0;
    var maxLabels = 220;
    var clip = getClipArea(cssW, cssH);
    var clipW = clip.w;
    var clipH = clip.h;

    ctx.font = '12px "DejaVu Sans", Verdana, Geneva, sans-serif';
    ctx.textBaseline = 'top';

    ctx.save();
    ctx.beginPath();
    ctx.rect(0, 0, clipW, clipH);
    ctx.clip();

    for (var i = 0; i < spots.length; i++) {
      var spot = spots[i];
      if (allowedModes.indexOf(classifyMode(spot.mode)) === -1) continue;

      var x = frequencyToX(spot.freq);
      if (x === null) continue;
      if (x < -2 || x > clipW + 2) continue;

      var age = Math.max(0, now - spot.time);
      var alpha = Math.max(0, 1 - (age / maxAge));
      if (alpha <= 0) continue;

      var color = colorForMode(spot.mode);

      ctx.save();
      ctx.globalAlpha = Math.min(1, 0.9 * alpha + 0.1);
      ctx.strokeStyle = color;
      ctx.lineWidth = 1;
      ctx.beginPath();
      ctx.moveTo(Math.round(x) + 0.5, 0);
      ctx.lineTo(Math.round(x) + 0.5, clipH);
      ctx.stroke();
      ctx.restore();

      if (labelCount >= maxLabels) continue;

      var label = spot.call;
      if (!label) continue;

      var labelW = Math.ceil(ctx.measureText(label).width) + 12;
      var labelH = 16;
      var labelX = Math.max(2, Math.min(cssW - labelW - 2, x + 4));
      if (labelX + labelW > clipW) continue;

      var lane = -1;
      for (var l = 0; l < maxLanes; l++) {
        if (!labelLanes[l]) labelLanes[l] = [];
        var overlaps = false;
        for (var k = 0; k < labelLanes[l].length; k++) {
          var r = labelLanes[l][k];
          if (!(labelX + labelW < r.start || labelX > r.end)) {
            overlaps = true;
            break;
          }
        }
        if (!overlaps) {
          lane = l;
          labelLanes[l].push({ start: labelX, end: labelX + labelW });
          break;
        }
      }

      if (lane < 0) continue;

      var labelY = 6 + lane * (labelH + 4);
      if (labelY + labelH > clipH - 4) continue;

      var labelMidY = labelY + (labelH / 2);

      ctx.save();
      ctx.globalAlpha = Math.min(1, 0.85 * alpha + 0.15);
      ctx.strokeStyle = 'rgba(0, 0, 0, 0.55)';
      ctx.lineWidth = 1;
      ctx.setLineDash([3, 3]);
      ctx.beginPath();
      ctx.moveTo(Math.round(x) + 0.5, labelMidY);
      ctx.lineTo(labelX - 3, labelMidY);
      ctx.stroke();
      ctx.setLineDash([]);
      ctx.restore();

      ctx.save();
      ctx.globalAlpha = Math.min(1, 0.85 * alpha + 0.15);
      ctx.fillStyle = 'rgba(0, 0, 0, 0.55)';
      drawLabelBackground(ctx, labelX - 2, labelY - 1, labelW + 4, labelH + 2, 4);
      ctx.fill();
      ctx.restore();

      ctx.save();
      ctx.globalAlpha = Math.min(1, 0.9 * alpha + 0.1);
      ctx.fillStyle = color;
      ctx.strokeStyle = 'rgba(0, 0, 0, 0.9)';
      ctx.lineWidth = 3;
      ctx.strokeText(label, labelX, labelY);
      ctx.fillText(label, labelX, labelY);
      ctx.restore();

      labelCount++;
    }

    if (labelCount > 0 && (Math.floor(now) % 10 === 0)) {
      if (!state.__lastRenderLogTs || (now - state.__lastRenderLogTs) >= 10) {
        state.__lastRenderLogTs = now;
        console.debug('spider: rendered labels=', labelCount, 'spots=', spots.length);
      }
    }

    ctx.restore();
  }

  function handleSpot(spot) {
    if (!spot || typeof spot !== 'object') return;
    var freq = Number(spot.freq);
    if (!isFinite(freq) || freq <= 0 || !spot.call) return;

    var normalized = {
      freq: Math.round(freq),
      call: String(spot.call || '').toUpperCase(),
      mode: String(spot.mode || '').toUpperCase(),
      comment: String(spot.comment || ''),
      spotter: String(spot.spotter || ''),
      band: String(spot.band || ''),
      time: parseInt(spot.time, 10) || Math.floor(Date.now() / 1000),
      source: String(spot.source || '')
    };

    var merged = false;
    // Merge duplicates to avoid fast churn/flicker under high traffic.
    for (var i = state.spots.length - 1; i >= 0; i--) {
      var ex = state.spots[i];
      if (!ex) continue;
      if (ex.call !== normalized.call) continue;
      if (Math.abs(Number(ex.freq) - Number(normalized.freq)) > 300) continue;
      if ((normalized.time - Number(ex.time || 0)) > 1800) continue;
      ex.freq = normalized.freq;
      ex.mode = normalized.mode || ex.mode;
      ex.comment = normalized.comment || ex.comment;
      ex.spotter = normalized.spotter || ex.spotter;
      ex.band = normalized.band || ex.band;
      ex.time = normalized.time;
      ex.source = normalized.source || ex.source;
      merged = true;
      break;
    }

    if (!merged) state.spots.push(normalized);
    if (state.spots.length > state.cfg.max_spots) {
      state.spots.splice(0, state.spots.length - state.cfg.max_spots);
    }

    scheduleRender();
  }

  function updateConfig(patch) {
    state.cfg = $.extend({}, state.cfg, patch || {});
    try {
      localStorage.setItem('spider_config', JSON.stringify(state.cfg));
    } catch (e) {
      console.warn('spider: cannot save config');
    }
    state.wsUrls = null;
    state.wsUrlIndex = 0;
    applyEffectiveEnabled();
  }

  function syncSettingsUi() {
    if (state.settingsCheckbox) {
      state.settingsCheckbox.checked = !!state.cfg.enabled;
    }
  }

  function removeToggle() {
    $('#openwebrx-panel-receiver #openwebrx-spider-toggle, ' +
      '#openwebrx-panel-receiver .openwebrx-spider-setting').remove();
    state.settingsCheckbox = null;
  }

  function installToggle() {
    var $settings = $('#openwebrx-section-settings').next('.openwebrx-section');
    if (!$settings.length) {
      // Newer OpenWebRX layout: inject directly into receiver panel.
      $settings = $('#openwebrx-panel-receiver');
    }
    if (!$settings.length) return;
    removeToggle();
    if ($('#openwebrx-spider-toggle').length) return;

    $('#openwebrx-spider-settings-overlay, #openwebrx-spider-settings-button').remove();

    var $row = $('<div></div>')
      .addClass('openwebrx-panel-line');

    var $label = $('<label></label>')
      .addClass('openwebrx-checkbox openwebrx-spider-setting')
      .attr('title', 'Displays DX cluster spots on the waterfall, color-coded by mode.');

    var $input = $('<input>')
      .attr('type', 'checkbox')
      .attr('id', 'openwebrx-spider-toggle')
      .on('change', function () {
        state.cfg.enabled = !!this.checked;
        updateConfig({ enabled: state.cfg.enabled });
      });

    var $title = $('<span></span>')
      .addClass('openwebrx-spider-setting-title')
      .text('Show DX cluster spots');

    $label.append($input, $title);
    $row.append($label);
    var $checkboxRow = $('#openwebrx-panel-receiver .openwebrx-checkbox').first().closest('.openwebrx-panel-line');
    if ($checkboxRow.length) {
      $checkboxRow.after($row);
    } else {
      var $modes = $('#openwebrx-panel-receiver .openwebrx-modes').first();
      if ($modes.length) {
        $modes.after($row);
      } else {
        $settings.append($row);
      }
    }

    state.settingsCheckbox = $input[0];
    syncSettingsUi();
  }

  function closeWs() {
    if (!state.ws) return;
    try {
      state.ws.onopen = null;
      state.ws.onmessage = null;
      state.ws.onerror = null;
      state.ws.onclose = null;
      state.ws.close();
    } catch (e) {
      // ignore close errors
    }
    state.ws = null;
  }

  function applyEffectiveEnabled() {
    var serverEnabled = (state.serverEnabled === null) ? true : !!state.serverEnabled;
    var effective = !!state.cfg.enabled && serverEnabled;
    if (state.enabled === effective) return;
    state.enabled = effective;
    if (!state.enabled) {
      closeWs();
      if (state.ctx && state.canvas) {
        state.ctx.clearRect(0, 0, state.canvas.clientWidth, state.canvas.clientHeight);
      }
    } else {
      connectWs();
      scheduleRender();
    }
  }

  function syncServerConfig() {
    var serverEnabled = getServerEnabled();
    if (state.serverEnabled === serverEnabled) return;
    state.serverEnabled = serverEnabled;
    installToggle();
    applyEffectiveEnabled();
  }

  function connectWs() {
    var urls = [];
    if (state.cfg.ws_url) urls.push(state.cfg.ws_url);
    if (Array.isArray(state.cfg.ws_urls)) urls = urls.concat(state.cfg.ws_urls);
    if (!urls.length) urls = buildDefaultWsUrls();
    urls = uniqUrls(urls);
    if (!urls.length) return;
    state.wsUrls = urls;
    if (state.wsUrlIndex >= urls.length) state.wsUrlIndex = 0;
    var wsUrl = urls[state.wsUrlIndex];
    if (!state.enabled) return;
    if (state.ws && (state.ws.readyState === WebSocket.CONNECTING || state.ws.readyState === WebSocket.OPEN)) return;

    try {
      state.ws = new WebSocket(wsUrl);
    } catch (e) {
      console.error('spider: websocket init failed', e);
      state.wsUrlIndex = (state.wsUrlIndex + 1) % urls.length;
      scheduleReconnect();
      return;
    }

    var opened = false;
    state.ws.onopen = function () {
      opened = true;
      state.wsBackoff = 1000;
      console.log('spider: websocket connected', wsUrl);
    };

    state.ws.onmessage = function (evt) {
      try {
        var payload = JSON.parse(evt.data);
        handleSpot(payload);
      } catch (e) {
        console.warn('spider: invalid spot payload');
      }
    };

    state.ws.onerror = function () {
      console.warn('spider: websocket error');
    };

    state.ws.onclose = function () {
      if (!opened && urls.length > 1) {
        state.wsUrlIndex = (state.wsUrlIndex + 1) % urls.length;
      }
      scheduleReconnect();
    };
  }

  function scheduleReconnect() {
    if (!state.enabled) return;
    if (state.wsBackoff > 30000) state.wsBackoff = 30000;
    window.setTimeout(function () {
      connectWs();
      state.wsBackoff = Math.min(30000, state.wsBackoff * 1.5);
    }, state.wsBackoff);
  }

  function setEnabled(enabled) {
    updateConfig({ enabled: !!enabled });
    if (enabled) {
      connectWs();
      scheduleRender();
    } else {
      closeWs();
      if (state.ctx && state.canvas) {
        state.ctx.clearRect(0, 0, state.canvas.clientWidth, state.canvas.clientHeight);
      }
    }
  }

  function stopSpider() {
    state.enabled = false;
    closeWs();
    if (state.renderTimer) {
      try { window.clearInterval(state.renderTimer); } catch (e) {}
      state.renderTimer = null;
    }
    state.running = false;
    if (state.ctx && state.canvas) {
      state.ctx.clearRect(0, 0, state.canvas.clientWidth, state.canvas.clientHeight);
    }
  }

  function start() {
    if (!ensureOverlay()) {
      console.error('spider: cannot find waterfall container');
      return false;
    }
    installToggle();
    applyEffectiveEnabled();
    connectWs();
    state.running = true;
    if (!state.renderTimer) state.renderTimer = window.setInterval(render, 250);
    scheduleRender();
    return true;
  }

  function exportApi() {
    var api = window.spider || {};
    api.setEnabled = function (enabled) { setEnabled(!!enabled); };
    api.enable = function () { setEnabled(true); };
    api.disable = function () { setEnabled(false); };
    api.connect = function () { setEnabled(true); };
    api.disconnect = function () { setEnabled(false); };
    api.start = function () { return bootSpider(); };
    api.stop = function () { stopSpider(); };
    api.getState = function () {
      return {
        enabled: !!state.enabled,
        running: !!state.running,
        wsReadyState: state.ws ? state.ws.readyState : -1,
        wsUrl: (state.wsUrls && state.wsUrls.length) ? state.wsUrls[state.wsUrlIndex || 0] : state.cfg.ws_url,
        spots: state.spots.length
      };
    };
    window.spider = api;
    window.Spider = api;
    window.spider_client = api;
  }

  function bootSpider() {
    if (state.running) return true;
    if (!isOwrxReady()) return false;
    return start();
  }

  function scheduleBootRetry() {
    if (state.running) return;
    if (bootSpider()) return;
    window.setTimeout(scheduleBootRetry, 700);
  }

  exportApi();
  scheduleBootRetry();
  $(document).on('event:owrx_initialized event:waterfall_resized', function () {
    scheduleBootRetry();
  });
  if (document && document.addEventListener) {
    document.addEventListener('DOMContentLoaded', function () {
      scheduleBootRetry();
    });
  }

  return true;
};
