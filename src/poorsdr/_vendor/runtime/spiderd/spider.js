/*
 * spider DX Cluster overlay plugin for OpenWebRX+
 * Robust build for PoorSDR4
 */

Plugins.spider = Plugins.spider || {};
Plugins.spider._version = 3.0;

Plugins.spider.init = function () {
  if (window.__SPIDER_INIT_DONE) return true;
  window.__SPIDER_INIT_DONE = true;
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

  function sanitizeWsUrl(raw) {
    if (raw === null || raw === undefined) return null;
    var u = String(raw).trim();
    if (!u) return null;
    // Trim accidental wrapping quotes from persisted configs.
    if ((u[0] === '"' && u[u.length - 1] === '"') || (u[0] === "'" && u[u.length - 1] === "'")) {
      u = u.slice(1, -1).trim();
    }
    if (!u) return null;
    try {
      var p = new URL(u);
      if (p.protocol !== 'ws:' && p.protocol !== 'wss:') return null;
      if (!p.hostname) return null;
      return p.toString();
    } catch (_e) {
      return null;
    }
  }

  function buildDefaultWsUrls() {
    var urls = [];
    var isLocal = (window.location.hostname === 'localhost' || window.location.hostname === '127.0.0.1' || window.location.hostname === '::1');
    if (isLocal) {
      urls.push('ws://127.0.0.1:17373/spots');
      urls.push('ws://127.0.0.1:7373/spots');
    } else {
      var targetHost = window.location.hostname;
      urls.push('ws://' + targetHost + ':17373/spots');
      urls.push((window.location.protocol === 'https:' ? 'wss://' : 'ws://') + targetHost + ':17373/spots');
      urls.push('ws://' + targetHost + ':7373/spots');
      urls.push((window.location.protocol === 'https:' ? 'wss://' : 'ws://') + targetHost + ':7373/spots');
    }

    return uniqUrls(urls);
  }

  var defaults = {
    ws_url: null,
    ws_urls: null,
    max_age_sec: 420,
    modes: ['CW', 'SSB', 'FT8', 'DIG', 'DIGI', 'UNKNOWN'],
    enabled: true,
    max_spots: 1200,
    freq_offset_hz: 0
  };

  function getServerEnabled() {
    if (window.__owrx_force_spider_enabled === false) return false;
    // PoorSDR policy: spider visibility is app-driven (Spots button/filters),
    // never disabled by theme/backend defaults.
    return true;
  }

  function loadConfig() {
    var globalCfg = (typeof window.spider_config_global === 'object') ? window.spider_config_global : {};
    var localCfg = {};
    try {
      var raw = localStorage.getItem('spider_config');
      if (raw) {
        var parsed = JSON.parse(raw);
        // Persist only user filters across restarts.
        // Never persist connection endpoints from browser cache.
        if (parsed && typeof parsed === 'object') {
          if (Array.isArray(parsed.modes)) localCfg.modes = parsed.modes.slice();
          if (typeof parsed.enabled === 'boolean') localCfg.enabled = parsed.enabled;
          if (parsed.freq_offset_hz !== undefined) localCfg.freq_offset_hz = Number(parsed.freq_offset_hz) || 0;
        }
      }
    } catch (e) {
      console.warn('spider: invalid localStorage config');
    }

    var cfg = $.extend({}, defaults, globalCfg, localCfg);
    if (!Array.isArray(cfg.modes)) cfg.modes = defaults.modes.slice();
    cfg.modes = cfg.modes.map(function (m) { return String(m).toUpperCase(); });
    if (cfg.modes.indexOf('CW') < 0) cfg.modes.push('CW');
    cfg.max_age_sec = Math.max(10, parseInt(cfg.max_age_sec, 10) || defaults.max_age_sec);
    cfg.max_spots = Math.max(50, parseInt(cfg.max_spots, 10) || defaults.max_spots);
    cfg.freq_offset_hz = Number(cfg.freq_offset_hz) || 0;
    if (Array.isArray(cfg.ws_urls)) {
      cfg.ws_urls = uniqUrls(cfg.ws_urls.map(sanitizeWsUrl).filter(function (u) { return !!u; }));
    } else {
      cfg.ws_urls = [];
    }
    cfg.ws_url = sanitizeWsUrl(cfg.ws_url) || '';
    if (!cfg.ws_url && cfg.ws_urls.length) cfg.ws_url = cfg.ws_urls[0];
    if (!cfg.ws_url) {
      var urls = uniqUrls(buildDefaultWsUrls().map(sanitizeWsUrl).filter(function (u) { return !!u; }));
      cfg.ws_urls = urls;
      cfg.ws_url = urls.length ? urls[0] : '';
    }
    if (!cfg.ws_urls.length && cfg.ws_url) cfg.ws_urls = [cfg.ws_url];
    cfg.enabled = cfg.enabled !== false;
    return cfg;
  }

  function classifySpotMode(mode) {
    var m = classifyMode(mode);
    if (m === 'CW') return 'CW';
    if (m === 'SSB') return 'SSB';
    return 'DIGI';
  }

  function isModeAllowed(mode) {
    var selected = Array.isArray(state.cfg.modes) ? state.cfg.modes : [];
    if (!selected.length) return true;
    var norm = {};
    for (var i = 0; i < selected.length; i++) {
      var key = String(selected[i] || '').toUpperCase();
      if (!key) continue;
      if (key === 'DIG') key = 'DIGI';
      if (key === 'FT8' || key === 'FT4' || key === 'RTTY' || key === 'PSK' || key === 'DATA') key = 'DIGI';
      if (key === 'USB' || key === 'LSB' || key === 'AM' || key === 'FM' || key === 'PHONE') key = 'SSB';
      norm[key] = true;
    }
    return !!norm[classifySpotMode(mode)];
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
    wsMsgCount: 0,
    wsParseErrCount: 0,
    wsSpotAcceptedCount: 0,
    wsLastMsgPreview: '',
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

    var fBias = Number(state.cfg && state.cfg.freq_offset_hz) || 0;
    var f0 = Number(freqHz) + fBias;
    var freqVariants = uniqNumbers([f0, f0 / 1000, f0 / 1000000]);
    if (!freqVariants.length) return null;

    var range = null;
    var rawRange = null;
    try {
      if (typeof get_visible_freq_range === 'function') {
        rawRange = get_visible_freq_range();
        range = parseRange(rawRange);
      }
    } catch (_eR) {}

    if (range && isFinite(range.lo) && isFinite(range.hi) && range.hi > range.lo) {
      // Prefer OWRX native pixel mapping when available for exact alignment.
      if (typeof scale_px_from_freq === 'function' && rawRange) {
        for (var s = 0; s < freqVariants.length; s++) {
          var sx = Number(scale_px_from_freq(freqVariants[s], rawRange));
          if (isFinite(sx) && sx > -200 && sx < (width + 200)) return sx;
        }
      }
      var span = range.hi - range.lo;
      function mapVal(v) {
        var x = ((v - range.lo) / span) * width;
        return (isFinite(x) && x > -200 && x < (width + 200)) ? x : null;
      }

      for (var i = 0; i < freqVariants.length; i++) {
        var direct = mapVal(freqVariants[i]);
        if (direct !== null) return direct;
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

    var maxAge = state.cfg.max_age_sec;

    var spots = state.spots.slice();
    // Stable ordering reduces visible "jumping" in dense traffic.
    spots.sort(function (a, b) {
      if (a.freq !== b.freq) return a.freq - b.freq;
      return b.time - a.time;
    });

    var labelLanes = [];
    var maxLanes = 9;
    var labelCount = 0;
    var maxLabels = 300;
    var minLabelGap = 6;
    var clip = getClipArea(cssW, cssH);
    var clipW = clip.w;
    var clipH = clip.h;

    ctx.font = '11px "DejaVu Sans", Verdana, Geneva, sans-serif';
    ctx.textBaseline = 'top';

    ctx.save();
    ctx.beginPath();
    ctx.rect(0, 0, clipW, clipH);
    ctx.clip();

    for (var i = 0; i < spots.length; i++) {
      var spot = spots[i];
      if (!isModeAllowed(spot.mode)) continue;

      var x = frequencyToX(spot.freq);
      if (x === null) continue;
      if (x < -2 || x > clipW + 2) continue;

      var age = Math.max(0, now - spot.time);
      var alpha = Math.max(0, 1 - (age / maxAge));
      if (alpha <= 0) continue;

      var color = colorForMode(spot.mode);

      if (labelCount >= maxLabels) continue;

      var label = spot.call;
      if (!label) continue;
      if (label.length > 12) label = label.slice(0, 11) + '…';

      var labelW = Math.ceil(ctx.measureText(label).width) + 18;
      var labelH = 15;
      // Anchor label start (left accent stripe) to spot frequency.
      var labelX = Math.max(2, Math.min(cssW - labelW - 2, x));
      if (labelX + labelW > clipW) continue;

      var lane = -1;
      for (var l = 0; l < maxLanes; l++) {
        if (!labelLanes[l]) labelLanes[l] = [];
        var overlaps = false;
        for (var k = 0; k < labelLanes[l].length; k++) {
          var r = labelLanes[l][k];
          if (!(labelX + labelW + minLabelGap < r.start || labelX > r.end + minLabelGap)) {
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

      var topPad = 4;
      var laneStep = 16;
      var compactH = Math.min(labelH, Math.max(11, laneStep - 2));
      var labelY = topPad + lane * laneStep;
      if (labelY + compactH > clipH - 2) continue;

      // Modern mode: no vertical marker lines (clean view).

      ctx.save();
      ctx.globalAlpha = Math.min(1, 0.9 * alpha + 0.1);
      ctx.fillStyle = 'rgba(10, 12, 16, 0.92)';
      drawLabelBackground(ctx, labelX - 1, labelY - 1, labelW + 2, compactH + 2, 5);
      ctx.fill();
      // left accent stripe by mode color (label style)
      ctx.fillStyle = color;
      drawLabelBackground(ctx, labelX - 1, labelY - 1, 4, compactH + 2, 3);
      ctx.fill();
      // subtle border
      ctx.strokeStyle = 'rgba(180, 190, 210, 0.28)';
      ctx.lineWidth = 1;
      drawLabelBackground(ctx, labelX - 1, labelY - 1, labelW + 2, compactH + 2, 5);
      ctx.stroke();
      // mode dot
      ctx.beginPath();
      ctx.fillStyle = color;
      ctx.arc(labelX + 8, labelY + Math.max(6, Math.floor(compactH / 2)), 2.1, 0, Math.PI * 2);
      ctx.fill();
      ctx.restore();

      ctx.save();
      ctx.globalAlpha = Math.min(1, 0.95 * alpha + 0.05);
      ctx.fillStyle = '#EAF2FF';
      ctx.strokeStyle = 'rgba(0, 0, 0, 0.35)';
      ctx.lineWidth = 2;
      ctx.strokeText(label, labelX + 13, labelY);
      ctx.fillText(label, labelX + 13, labelY);
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
    // Merge duplicates conservatively to avoid "disappearing" nearby spots.
    for (var i = state.spots.length - 1; i >= 0; i--) {
      var ex = state.spots[i];
      if (!ex) continue;
      if (ex.call !== normalized.call) continue;
      if (Math.abs(Number(ex.freq) - Number(normalized.freq)) > 120) continue;
      if ((normalized.time - Number(ex.time || 0)) > 1800) continue;
      // Keep exact latest reported frequency to avoid visual drift.
      ex.freq = Math.round(Number(normalized.freq));
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
    state.wsSpotAcceptedCount++;

    scheduleRender();
  }

  function updateConfig(patch) {
    state.cfg = $.extend({}, state.cfg, patch || {});
    if (Array.isArray(state.cfg.modes)) {
      state.cfg.modes = state.cfg.modes.map(function (m) { return String(m || '').toUpperCase(); });
    }
    try {
      // Persist only user filters; keep ws_url/ws_urls from server-side init.js
      // to avoid stale browser endpoints after restart/rebuild.
      localStorage.setItem('spider_config', JSON.stringify({
        enabled: !!state.cfg.enabled,
        modes: Array.isArray(state.cfg.modes) ? state.cfg.modes.slice() : [],
        freq_offset_hz: Number(state.cfg.freq_offset_hz) || 0
      }));
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
    $('#openwebrx-spider-force-toggle').remove();
    state.settingsCheckbox = null;
  }

  function installForcedToggle() {
    return;
  }

  function installToggle() {
    var $panel = $('#openwebrx-panel-receiver');
    if (!$panel.length) {
      $panel = $('#openwebrx-panel .openwebrx-section, .openwebrx-panel, #openwebrx-panel').first();
    }
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
    var $checkboxRow = $panel.find('.openwebrx-checkbox').first().closest('.openwebrx-panel-line');
    if ($checkboxRow.length) {
      $checkboxRow.after($row);
    } else {
      var $modes = $panel.find('.openwebrx-modes').first();
      if ($modes.length) {
        $modes.after($row);
      } else if ($panel.length) {
        $panel.first().append($row);
      } else {
        // Last-resort fallback: visible floating toggle.
        $row.css({
          position: 'fixed',
          right: '12px',
          bottom: '12px',
          zIndex: 99999,
          background: 'rgba(0,0,0,0.7)',
          padding: '6px 10px',
          borderRadius: '6px'
        });
        $('body').append($row);
      }
    }

    state.settingsCheckbox = $input[0];
    syncSettingsUi();
    installForcedToggle();
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
    urls = urls.map(sanitizeWsUrl).filter(function (u) { return !!u; });
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
        state.wsMsgCount++;
        state.wsLastMsgPreview = String(evt.data || '').slice(0, 220);
        var payload = JSON.parse(evt.data);
        if (Array.isArray(payload)) {
          for (var i = 0; i < payload.length; i++) handleSpot(payload[i]);
        } else if (payload && Array.isArray(payload.data)) {
          for (var j = 0; j < payload.data.length; j++) handleSpot(payload.data[j]);
        } else if (payload && payload.data && typeof payload.data === 'object') {
          handleSpot(payload.data);
        } else if (payload && payload.spot && typeof payload.spot === 'object') {
          handleSpot(payload.spot);
        } else {
          handleSpot(payload);
        }
      } catch (e) {
        state.wsParseErrCount++;
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
    installToggle();
    installForcedToggle();
    if (!ensureOverlay()) {
      console.warn('spider: cannot find waterfall container yet; toggle/WS remain active');
      applyEffectiveEnabled();
      connectWs();
      state.running = true;
      return true;
    }
    applyEffectiveEnabled();
    connectWs();
    state.running = true;
    // React quickly to zoom/pan interactions so labels stay aligned.
    if (!state.__interactionHooked) {
      state.__interactionHooked = true;
      var onViewChanged = function () { scheduleRender(); };
      try { window.addEventListener('wheel', onViewChanged, { passive: true }); } catch (_eWheel) {}
      try { window.addEventListener('mousemove', onViewChanged, { passive: true }); } catch (_eMove) {}
      try { $(document).on('event:waterfall_resized event:owrx_initialized', onViewChanged); } catch (_eDoc) {}
    }
    if (!state.renderTimer) state.renderTimer = window.setInterval(render, 250);
    scheduleRender();
    // Keep spot labels aligned immediately after OWRX zoom changes.
    if (!state.__zoomHooked) {
      state.__zoomHooked = true;
      try {
        if (typeof window.zoom_set === 'function' && !window.__spider_zoom_set_wrapped) {
          window.__spider_zoom_set_wrapped = true;
          var _zoomSet = window.zoom_set;
          window.zoom_set = function(level) {
            var r = _zoomSet.apply(this, arguments);
            scheduleRender();
            return r;
          };
        }
      } catch (_eZ1) {}
      try {
        if (typeof window.zoom_step === 'function' && !window.__spider_zoom_step_wrapped) {
          window.__spider_zoom_step_wrapped = true;
          var _zoomStep = window.zoom_step;
          window.zoom_step = function(out, where, onscreen) {
            var r2 = _zoomStep.apply(this, arguments);
            scheduleRender();
            return r2;
          };
        }
      } catch (_eZ2) {}
    }
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
    api.setFilters = function (filters) {
      var patch = {};
      var f = filters || {};
      if (Array.isArray(f.modes)) patch.modes = f.modes.slice();
      if (typeof f.off === 'boolean') patch.enabled = !f.off;
      updateConfig(patch);
      scheduleRender();
    };
    api.getState = function () {
      return {
        enabled: !!state.enabled,
        running: !!state.running,
        wsReadyState: state.ws ? state.ws.readyState : -1,
        wsUrl: (state.wsUrls && state.wsUrls.length) ? state.wsUrls[state.wsUrlIndex || 0] : state.cfg.ws_url,
        spots: state.spots.length,
        wsMsgCount: state.wsMsgCount,
        wsParseErrCount: state.wsParseErrCount,
        wsSpotAcceptedCount: state.wsSpotAcceptedCount,
        wsLastMsgPreview: state.wsLastMsgPreview
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
