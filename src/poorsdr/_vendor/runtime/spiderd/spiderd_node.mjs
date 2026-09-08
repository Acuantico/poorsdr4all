#!/usr/bin/env node

import fs from 'fs';
import mqtt from 'mqtt';
import { WebSocketServer } from 'ws';

function parseArgs(argv) {
  const out = { config: 'spiderd.conf' };
  for (let i = 0; i < argv.length; i++) {
    if (argv[i] === '--config' && argv[i + 1]) {
      out.config = argv[i + 1];
      i += 1;
    }
  }
  return out;
}

function parseIni(path) {
  const data = fs.readFileSync(path, 'utf8');
  const cfg = {};
  let section = '';
  for (const rawLine of data.split(/\r?\n/)) {
    const line = rawLine.trim();
    if (!line || line.startsWith('#') || line.startsWith(';')) continue;
    if (line.startsWith('[') && line.endsWith(']')) {
      section = line.slice(1, -1).trim();
      if (!cfg[section]) cfg[section] = {};
      continue;
    }
    const eq = line.indexOf('=');
    if (eq < 0) continue;
    const key = line.slice(0, eq).trim();
    const value = line.slice(eq + 1).trim();
    if (!cfg[section]) cfg[section] = {};
    cfg[section][key] = value;
  }
  return cfg;
}

function toInt(v, def) {
  const n = Number.parseInt(String(v ?? ''), 10);
  return Number.isFinite(n) ? n : def;
}

function parseFrequency(value) {
  if (value == null) return null;
  const n = Number.parseFloat(String(value).replace(',', '.').trim());
  if (!Number.isFinite(n) || n <= 0) return null;
  if (n < 1000) return Math.round(n * 1_000_000);
  if (n < 1_000_000) return Math.round(n * 1000);
  return Math.round(n);
}

function parseIsoTs(v) {
  if (!v) return null;
  const d = new Date(String(v));
  if (Number.isNaN(d.getTime())) return null;
  return Math.floor(d.getTime() / 1000);
}

const BANDS = [
  ['160m', 1800000, 2000000],
  ['80m', 3500000, 4000000],
  ['60m', 5300000, 5400000],
  ['40m', 7000000, 7300000],
  ['30m', 10100000, 10150000],
  ['20m', 14000000, 14350000],
  ['17m', 18068000, 18168000],
  ['15m', 21000000, 21450000],
  ['12m', 24890000, 24990000],
  ['10m', 28000000, 29700000],
  ['6m', 50000000, 54000000],
  ['4m', 70000000, 70500000],
  ['2m', 144000000, 148000000],
];

function bandForFreq(freq) {
  for (const [name, lo, hi] of BANDS) {
    if (freq >= lo && freq <= hi) return name;
  }
  return '';
}

function bandRangeFromLabel(label) {
  const text = String(label || '').trim().toLowerCase();
  if (!text) return null;
  for (const [name, lo, hi] of BANDS) {
    if (text === String(name).toLowerCase()) return [lo, hi];
  }
  return null;
}

function normalizeFreqByBand(freq, bandLabel) {
  const range = bandRangeFromLabel(bandLabel);
  if (!range) return freq;
  const [lo, hi] = range;
  if (freq >= lo && freq <= hi) return freq;
  for (const div of [10, 100, 1000]) {
    const cand = Math.round(freq / div);
    if (cand >= lo && cand <= hi) return cand;
  }
  for (const mul of [10, 100, 1000]) {
    const cand = Math.round(freq * mul);
    if (cand >= lo && cand <= hi) return cand;
  }
  return freq;
}

function normalizeFreqGeneric(freq) {
  let val = Number(freq);
  if (!Number.isFinite(val) || val <= 0) return freq;
  if (bandForFreq(val)) return val;
  for (const _ of [1, 2, 3, 4]) {
    val = Math.round(val / 10);
    if (val <= 0) break;
    if (bandForFreq(val)) return val;
  }
  return freq;
}

function normalizeSpot(topic, raw) {
  let freq = parseFrequency(raw?.qrg ?? raw?.frequency ?? raw?.freq);
  const call = String(raw?.dx ?? raw?.call ?? '').trim().toUpperCase();
  if (!freq || !call) return null;
  const rawBand = String(raw?.band ?? '').trim();
  freq = normalizeFreqByBand(freq, rawBand);
  freq = normalizeFreqGeneric(freq);

  let mode = String(raw?.mode ?? raw?.submode ?? raw?.md ?? '').trim().toUpperCase();
  if (!mode) {
    const t = String(topic || '').toLowerCase();
    if (t.includes('rbn-cw')) mode = 'CW';
    else if (t.includes('rbn-dig')) mode = 'FT8';
    else mode = 'SSB';
  }
  if (mode === 'DIGI' || mode === 'DIG') mode = 'FT8';
  if (mode === 'UNK' || mode === 'UNKNOWN' || mode === 'PHONE' || mode === 'PH' || mode === 'FONIA' || mode === 'VOICE') mode = 'SSB';

  const comment = String(raw?.cmt ?? raw?.comment ?? '');
  const spotter = String(raw?.src ?? raw?.spotter ?? '').toUpperCase();
  const band = rawBand || bandForFreq(freq);
  const time = parseIsoTs(raw?.isots ?? raw?.utc) ?? Math.floor(Date.now() / 1000);

  return {
    freq,
    call,
    mode,
    comment,
    spotter,
    band,
    time,
    source: 'mqtt',
  };
}

function log(msg) {
  const now = new Date().toISOString().replace('T', ' ').replace('Z', '');
  console.log(`${now} [INFO] ${msg}`);
}

function warn(msg) {
  const now = new Date().toISOString().replace('T', ' ').replace('Z', '');
  console.warn(`${now} [WARNING] ${msg}`);
}

const args = parseArgs(process.argv.slice(2));
const cfg = parseIni(args.config);

const sourceKind = String(cfg?.source?.kind || 'mqtt').trim().toLowerCase();
if (sourceKind !== 'mqtt') {
  warn(`source.kind=${sourceKind}; this bridge is MQTT-only, waiting idle`);
}

const bindHost = String(cfg?.server?.bind || '0.0.0.0');
const bindPort = toInt(cfg?.server?.port, 7373);
const wsPath = String(cfg?.server?.path || '/spots');

const mqttUrl = String(cfg?.mqtt?.url || 'wss://ws.ure.es:443/mqtt');
const mqttTopics = String(cfg?.mqtt?.topics || 'spider/spots/dx,spider/spots/rbn-cw,spider/spots/rbn-dig')
  .split(',')
  .map(s => s.trim())
  .filter(Boolean);
const mqttUser = String(cfg?.mqtt?.username || '').trim();
const mqttPassword = String(cfg?.mqtt?.password || '');
const mqttClientId = String(cfg?.mqtt?.client_id || `spiderd-node-${Date.now()}`).trim();
const mqttQos = Math.max(0, Math.min(2, toInt(cfg?.mqtt?.qos, 0)));
const mqttKeepalive = Math.max(10, toInt(cfg?.mqtt?.keepalive, 30));

const wss = new WebSocketServer({ host: bindHost, port: bindPort, path: wsPath });
const wsClients = new Set();

wss.on('connection', ws => {
  wsClients.add(ws);
  log(`WebSocket client connected (${wsClients.size} total)`);
  ws.on('close', () => {
    wsClients.delete(ws);
    log(`WebSocket client disconnected (${wsClients.size} total)`);
  });
});

wss.on('listening', () => {
  log(`WebSocket server listening on ws://${bindHost}:${bindPort}${wsPath}`);
});

function broadcast(obj) {
  if (!wsClients.size) return;
  const payload = JSON.stringify(obj);
  for (const ws of wsClients) {
    if (ws.readyState === ws.OPEN) {
      ws.send(payload);
    }
  }
}

const mqttOpts = {
  clientId: mqttClientId,
  clean: true,
  reconnectPeriod: 3000,
  keepalive: mqttKeepalive,
  protocolVersion: 4,
};
if (mqttUser) {
  mqttOpts.username = mqttUser;
  mqttOpts.password = mqttPassword;
}

log(`Spider source selected: mqtt(node)`);
log(`Connecting to MQTT broker ${mqttUrl}`);

const client = mqtt.connect(mqttUrl, mqttOpts);
let spotCount = 0;

client.on('connect', () => {
  log(`MQTT connected (${mqttUrl})`);
  for (const topic of mqttTopics) {
    client.subscribe(topic, { qos: mqttQos }, err => {
      if (err) {
        warn(`MQTT subscribe failed topic=${topic}: ${err.message}`);
      } else {
        log(`MQTT subscribed topic=${topic} qos=${mqttQos}`);
      }
    });
  }
});

client.on('reconnect', () => warn('MQTT reconnecting...'));
client.on('close', () => warn('MQTT disconnected'));
client.on('error', err => warn(`MQTT error: ${err.message}`));

client.on('message', (topic, payload) => {
  try {
    const raw = JSON.parse(payload.toString('utf8'));
    if (String(topic).toLowerCase() === 'solar/wcy') return;
    const spot = normalizeSpot(topic, raw);
    if (!spot) return;
    spotCount += 1;
    if (spotCount <= 5 || spotCount % 50 === 0) {
      log(`MQTT spot #${spotCount} topic=${topic} call=${spot.call} freq=${spot.freq} mode=${spot.mode}`);
    }
    broadcast(spot);
  } catch (err) {
    warn(`MQTT message parse error: ${err.message}`);
  }
});

function shutdown() {
  try { client.end(true); } catch (_) {}
  try { wss.close(); } catch (_) {}
  process.exit(0);
}

process.on('SIGINT', shutdown);
process.on('SIGTERM', shutdown);
