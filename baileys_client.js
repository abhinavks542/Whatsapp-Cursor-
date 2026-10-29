const fs = require('fs');
const http = require('http');
const path = require('path');
const axios = require('axios');
const QRCode = require('qrcode');
const pino = require('pino');
const {
  default: makeWASocket,
  useMultiFileAuthState,
  DisconnectReason,
  makeInMemoryStore,
} = require('@whiskeysockets/baileys');

const logger = pino({
  level: 'info',
  timestamp: pino.stdTimeFunctions.isoTime,
});

const authDir = path.join(__dirname, 'auth_info_baileys');
const BRIDGE_URL = 'http://127.0.0.1:5001/process';
const BRIDGE_HEALTH_URL = 'http://127.0.0.1:5001/health';
const KILL_SWITCH_PATH = path.join(__dirname, 'kill_switch.flag');
const WEB_PAGE_PATH = path.join(__dirname, 'web', 'index.html');
const WEB_PORT = 5002;
const RECONNECT_BASE_DELAY_MS = 1000;
const RECONNECT_MAX_DELAY_MS = 30000;

let reconnectTimer = null;
let reconnectAttempts = 0;
let startupInProgress = false;
let sessionResetInProgress = false;
let whatsappSocket = null;
let connectionState = 'starting';
let qrImage = null;
let liveRepliesEnabled = false;
let lastConnectionError = '';
const activityEntries = [];
let activitySequence = 0;

let pairingCode = null;
let connectedUserInfo = null;

const ENV_PATH = path.join(__dirname, '.env');
const SETTINGS_FILE_PATH = path.join(__dirname, 'config', 'settings.json');
const ROOT_SETTINGS_PATH = path.join(__dirname, 'settings.json');
const RELATIONSHIP_MAP_PATH = path.join(__dirname, 'config', 'relationship_map.json');
const PERSONA_PATH = path.join(__dirname, 'persona', 'persona.json');

function readEnvConfig() {
  let content = '';
  try {
    content = fs.readFileSync(ENV_PATH, 'utf-8');
  } catch {}
  const apiKeyMatch = content.match(/^GROQ_API_KEY=(.*)$/m);
  const modelMatch = content.match(/^GROQ_MODEL=(.*)$/m);
  const apiKey = apiKeyMatch ? apiKeyMatch[1].trim() : (process.env.GROQ_API_KEY || '');
  const model = modelMatch ? modelMatch[1].trim() : (process.env.GROQ_MODEL || 'openai/gpt-oss-20b');
  return { apiKey, model };
}

function writeEnvConfig(apiKey, model) {
  let content = '';
  try {
    content = fs.readFileSync(ENV_PATH, 'utf-8');
  } catch {}
  let lines = content ? content.split(/\r?\n/) : [];
  let keyFound = false;
  let modelFound = false;
  lines = lines.map((line) => {
    if (line.startsWith('GROQ_API_KEY=')) {
      keyFound = true;
      return apiKey !== undefined ? `GROQ_API_KEY=${apiKey.trim()}` : line;
    }
    if (line.startsWith('GROQ_MODEL=')) {
      modelFound = true;
      return model !== undefined ? `GROQ_MODEL=${model.trim()}` : line;
    }
    return line;
  });
  if (!keyFound && apiKey !== undefined) lines.push(`GROQ_API_KEY=${apiKey.trim()}`);
  if (!modelFound && model !== undefined) lines.push(`GROQ_MODEL=${model.trim()}`);
  fs.writeFileSync(ENV_PATH, lines.filter((l) => l !== '').join('\n') + '\n', 'utf-8');
  if (apiKey !== undefined) process.env.GROQ_API_KEY = apiKey.trim();
  if (model !== undefined) process.env.GROQ_MODEL = model.trim();
}

function readRuntimeSettings() {
  const defaults = {
    dry_run: false,
    min_delay_seconds: 3,
    max_delay_seconds: 8,
    ignore_one_word_acks: true,
  };
  for (const p of [SETTINGS_FILE_PATH, ROOT_SETTINGS_PATH]) {
    try {
      if (fs.existsSync(p)) {
        return { ...defaults, ...JSON.parse(fs.readFileSync(p, 'utf-8')) };
      }
    } catch {}
  }
  return defaults;
}

function writeRuntimeSettings(settings) {
  const current = readRuntimeSettings();
  const merged = { ...current, ...settings };
  fs.mkdirSync(path.dirname(SETTINGS_FILE_PATH), { recursive: true });
  fs.writeFileSync(SETTINGS_FILE_PATH, JSON.stringify(merged, null, 2), 'utf-8');
  try {
    fs.writeFileSync(ROOT_SETTINGS_PATH, JSON.stringify(merged, null, 2), 'utf-8');
  } catch {}
  return merged;
}

function readRelationshipMap() {
  try {
    if (fs.existsSync(RELATIONSHIP_MAP_PATH)) {
      return JSON.parse(fs.readFileSync(RELATIONSHIP_MAP_PATH, 'utf-8'));
    }
  } catch {}
  return { _default: 'unknown' };
}

function writeRelationshipMap(map) {
  fs.mkdirSync(path.dirname(RELATIONSHIP_MAP_PATH), { recursive: true });
  fs.writeFileSync(RELATIONSHIP_MAP_PATH, JSON.stringify(map, null, 2), 'utf-8');
  return map;
}

function readPersona() {
  try {
    if (fs.existsSync(PERSONA_PATH)) {
      return JSON.parse(fs.readFileSync(PERSONA_PATH, 'utf-8'));
    }
  } catch {}
  return {
    identity: 'Warm, practical, and affectionate; casual with family and friends, concise and respectful at work.',
    hinglish_ratio: 'light Hinglish, about 15-20%',
    avg_message_length_words: 3,
  };
}

function writePersona(updates) {
  const current = readPersona();
  const merged = { ...current, ...updates };
  fs.mkdirSync(path.dirname(PERSONA_PATH), { recursive: true });
  fs.writeFileSync(PERSONA_PATH, JSON.stringify(merged, null, 2), 'utf-8');
  return merged;
}

function sleep(ms) {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

function randomDelayMs(minMs = 3000, maxMs = 8000) {
  return Math.floor(Math.random() * (maxMs - minMs + 1)) + minMs;
}

function getReconnectDelayMs() {
  const exponent = Math.min(reconnectAttempts, 5);
  const backoffMs = Math.min(
    RECONNECT_MAX_DELAY_MS,
    RECONNECT_BASE_DELAY_MS * (2 ** exponent)
  );
  reconnectAttempts += 1;
  const jitteredDelayMs = Math.floor(backoffMs * (0.75 + Math.random() * 0.5));
  return Math.min(RECONNECT_MAX_DELAY_MS, jitteredDelayMs);
}

function scheduleReconnect() {
  if (reconnectTimer || sessionResetInProgress) return;

  const delayMs = getReconnectDelayMs();
  logger.warn({ delayMs }, '[ROUTE] scheduling reconnect');
  reconnectTimer = setTimeout(() => {
    reconnectTimer = null;
    connectToWhatsApp().catch((error) => {
      connectionState = 'error';
      lastConnectionError = 'WhatsApp reconnect failed. See the local log for details.';
      logger.error({ err: error }, '[ROUTE] reconnect failed');
      scheduleReconnect();
    });
  }, delayMs);
}

function getContextInfo(message) {
  if (!message || typeof message !== 'object') return {};

  const candidates = [
    message.extendedTextMessage,
    message.conversation,
    message.imageMessage,
    message.videoMessage,
    message.audioMessage,
    message.documentMessage,
    message.stickerMessage,
  ];

  for (const candidate of candidates) {
    if (candidate && candidate.contextInfo) {
      return candidate.contextInfo;
    }
  }

  return {};
}

function getMessageText(message) {
  if (!message || typeof message !== 'object') return '';

  if (message.conversation) return message.conversation;
  if (message.extendedTextMessage && message.extendedTextMessage.text) {
    return message.extendedTextMessage.text;
  }

  const mediaTypes = ['imageMessage', 'videoMessage', 'audioMessage'];
  for (const type of mediaTypes) {
    const media = message[type];
    if (media) {
      return media.caption || '';
    }
  }

  return '';
}

function getMessageType(message) {
  if (!message || typeof message !== 'object') return 'other';

  if (message.conversation || message.extendedTextMessage) return 'text';
  if (message.imageMessage) return 'image';
  if (message.videoMessage) return 'video';
  if (message.audioMessage) return 'audio';
  return 'other';
}

function getIsForwarded(message) {
  const contextInfo = getContextInfo(message);
  if (!contextInfo) return false;
  const forwarded = contextInfo.isForwarded;
  return Boolean(forwarded);
}

async function sendToBridge(payload) {
  const response = await axios.post(BRIDGE_URL, payload, {
    headers: { 'Content-Type': 'application/json' },
    timeout: 20000,
  });
  logger.info({ status: response.status }, '[DECISION] bridge response received');
  return response.data;
}

function sendJson(response, statusCode, value) {
  response.writeHead(statusCode, {
    'Content-Type': 'application/json; charset=utf-8',
    'Cache-Control': 'no-store',
  });
  response.end(JSON.stringify(value));
}

async function getBridgeReadiness() {
  try {
    const result = await axios.get(BRIDGE_HEALTH_URL, { timeout: 1500 });
    if (result.data?.status !== 'ok' || typeof result.data.aiConfigured !== 'boolean') {
      return {
        bridgeReady: false,
        aiConfigured: false,
        bridgeError: 'The local decision bridge returned an invalid health response.',
      };
    }
    return {
      bridgeReady: true,
      aiConfigured: result.data.aiConfigured,
      bridgeError: '',
    };
  } catch (error) {
    const status = axios.isAxiosError(error) ? error.response?.status : null;
    return {
      bridgeReady: false,
      aiConfigured: false,
      bridgeError: status
        ? `The local decision bridge returned HTTP ${status}.`
        : 'The local decision bridge is unavailable. Restart WhatsApp Cursor.',
    };
  }
}

function recordActivity(entry) {
  const id = ++activitySequence;
  activityEntries.unshift({ id, timestamp: new Date().toISOString(), ...entry });
  if (activityEntries.length > 40) activityEntries.length = 40;
  return id;
}

function updateActivity(id, updates) {
  const entry = activityEntries.find((item) => item.id === id);
  if (entry) Object.assign(entry, updates);
}

function readRequestJson(request) {
  return new Promise((resolve, reject) => {
    let body = '';
    request.on('data', (chunk) => {
      body += chunk;
      if (body.length > 1024) {
        reject(new Error('Request body is too large'));
        request.destroy();
      }
    });
    request.on('end', () => {
      try {
        resolve(JSON.parse(body || '{}'));
      } catch {
        reject(new Error('Invalid JSON'));
      }
    });
    request.on('error', reject);
  });
}

function startWebConsole() {
  const server = http.createServer(async (request, response) => {
    const requestUrl = new URL(request.url, 'http://127.0.0.1');

    if (request.method === 'GET' && requestUrl.pathname === '/') {
      fs.readFile(WEB_PAGE_PATH, (error, contents) => {
        if (error) {
          response.writeHead(500, { 'Content-Type': 'text/plain; charset=utf-8' });
          response.end('Web console could not be loaded.');
          return;
        }
        response.writeHead(200, {
          'Content-Type': 'text/html; charset=utf-8',
          'Cache-Control': 'no-store',
          'X-Content-Type-Options': 'nosniff',
          'Referrer-Policy': 'no-referrer',
        });
        response.end(contents);
      });
      return;
    }

    if (request.method === 'GET' && requestUrl.pathname === '/sahayak') {
      fs.readFile(SAHAYAK_PAGE_PATH, (error, contents) => {
        if (error) {
          logger.error({ err: error.message }, '[WEB] Sahayak landing page could not be loaded');
          response.writeHead(500, { 'Content-Type': 'text/plain; charset=utf-8' });
          response.end('Sahayak concept page could not be loaded.');
          return;
        }
        response.writeHead(200, {
          'Content-Type': 'text/html; charset=utf-8',
          'Cache-Control': 'no-store',
          'Content-Security-Policy': "default-src 'self'; style-src 'unsafe-inline'; script-src 'unsafe-inline'; img-src 'self' data:; connect-src 'self'; object-src 'none'; base-uri 'none'; frame-ancestors 'none'",
          'X-Content-Type-Options': 'nosniff',
          'Referrer-Policy': 'no-referrer',
          'X-Frame-Options': 'DENY',
        });
        response.end(contents);
      });
      return;
    }

    if (request.method === 'GET' && requestUrl.pathname === '/api/status') {
      const readiness = await getBridgeReadiness();
      sendJson(response, 200, {
        connection: connectionState,
        qr: qrImage,
        pairingCode,
        user: connectedUserInfo,
        liveRepliesEnabled,
        killSwitchActive: fs.existsSync(KILL_SWITCH_PATH),
        lastError: lastConnectionError,
        ...readiness,
      });
      return;
    }

    if (request.method === 'GET' && requestUrl.pathname === '/api/activity') {
      sendJson(response, 200, activityEntries);
      return;
    }

    if (request.method === 'DELETE' && requestUrl.pathname === '/api/activity') {
      activityEntries.length = 0;
      sendJson(response, 200, { success: true, message: 'Activity stream cleared.' });
      return;
    }

    if (request.method === 'GET' && requestUrl.pathname === '/api/metrics') {
      let feedLines = [];
      const feedPath = path.join(__dirname, 'logs', 'console_feed.jsonl');
      try {
        if (fs.existsSync(feedPath)) {
          feedLines = fs.readFileSync(feedPath, 'utf-8').trim().split('\n').filter(Boolean).map((line) => {
            try { return JSON.parse(line); } catch { return null; }
          }).filter(Boolean);
        }
      } catch {}

      const totalCombined = feedLines.length + activityEntries.length;
      const feedReplies = feedLines.filter((f) => f.decision === 'reply').length;
      const actReplies = activityEntries.filter((a) => a.reply && (a.status === 'sent' || a.status === 'candidate')).length;
      const totalReplies = feedReplies + actReplies;

      const relationshipCounts = { family: 0, friend: 0, professional: 0, unknown: 0 };
      for (const item of [...feedLines, ...activityEntries]) {
        const rel = String(item.relationship || 'unknown').toLowerCase();
        if (relationshipCounts[rel] !== undefined) relationshipCounts[rel] += 1;
        else relationshipCounts.unknown += 1;
      }

      const totalGated = Math.max(0, totalCombined - totalReplies);
      const successRate = totalCombined > 0 ? ((totalReplies / totalCombined) * 100).toFixed(1) : '100.0';

      sendJson(response, 200, {
        totalMessages: totalCombined,
        totalReplies,
        totalGated,
        successRate: `${successRate}%`,
        relationships: relationshipCounts,
        uptimeSeconds: Math.floor(process.uptime()),
      });
      return;
    }

    if (request.method === 'POST' && requestUrl.pathname === '/api/session/pairing-code') {
      try {
        const body = await readRequestJson(request);
        const cleanNumber = String(body.phoneNumber || '').replace(/\D/g, '');
        if (cleanNumber.length < 8 || cleanNumber.length > 15) {
          sendJson(response, 400, { error: 'Enter a valid phone number with country code (e.g. 919876543210).' });
          return;
        }
        if (!whatsappSocket) {
          sendJson(response, 409, { error: 'WhatsApp is not ready yet. Please wait a moment.' });
          return;
        }
        const code = await whatsappSocket.requestPairingCode(cleanNumber);
        pairingCode = code;
        logger.info({ cleanNumber, code }, '[AUTH] Pairing code generated');
        sendJson(response, 200, { code });
      } catch (error) {
        sendJson(response, 500, { error: `Could not request pairing code: ${error.message}` });
      }
      return;
    }

    if (request.method === 'POST' && requestUrl.pathname === '/api/session/refresh-qr') {
      try {
        await resetWhatsAppSession();
        sendJson(response, 200, { success: true, message: 'Fresh QR code generated.' });
      } catch (error) {
        sendJson(response, 500, { error: error.message });
      }
      return;
    }

    if (request.method === 'GET' && requestUrl.pathname === '/api/settings') {
      const env = readEnvConfig();
      const runtime = readRuntimeSettings();
      const map = readRelationshipMap();
      const persona = readPersona();
      const contacts = Object.entries(map)
        .filter(([k]) => k !== '_default')
        .map(([number, relationship]) => ({ number, relationship }));

      const apiKeyMasked = env.apiKey
        ? (env.apiKey.length > 8 ? `${env.apiKey.slice(0, 4)}••••••••${env.apiKey.slice(-4)}` : '••••••••')
        : '';

      sendJson(response, 200, {
        compulsory: {
          hasApiKey: Boolean(env.apiKey),
          apiKeyMasked,
          model: env.model,
          liveRepliesEnabled,
          killSwitchActive: fs.existsSync(KILL_SWITCH_PATH),
        },
        addons: {
          minDelaySeconds: Number(runtime.min_delay_seconds) || 3,
          maxDelaySeconds: Number(runtime.max_delay_seconds) || 8,
          ignoreOneWordAcks: Boolean(runtime.ignore_one_word_acks),
          persona: {
            identity: persona.identity || '',
            hinglishRatio: persona.hinglish_ratio || '',
            avgMessageLength: persona.avg_message_length_words || 3,
            relationships: persona.relationships || {},
          },
          contacts,
          defaultRelationship: map._default || 'unknown',
          availableModels: [
            'openai/gpt-oss-20b',
            'llama-3.3-70b-versatile',
            'llama-3.1-8b-instant',
            'mixtral-8x7b-32768',
            'gemma2-9b-it',
          ],
          validRelationships: ['family', 'friend', 'professional', 'unknown'],
        },
      });
      return;
    }

    if (request.method === 'POST' && requestUrl.pathname === '/api/settings') {
      try {
        const body = await readRequestJson(request);
        if (body.apiKey !== undefined || body.model !== undefined) {
          writeEnvConfig(body.apiKey, body.model);
        }
        if (body.minDelaySeconds !== undefined || body.maxDelaySeconds !== undefined || body.ignoreOneWordAcks !== undefined) {
          writeRuntimeSettings({
            ...(body.minDelaySeconds !== undefined ? { min_delay_seconds: Number(body.minDelaySeconds) } : {}),
            ...(body.maxDelaySeconds !== undefined ? { max_delay_seconds: Number(body.maxDelaySeconds) } : {}),
            ...(body.ignoreOneWordAcks !== undefined ? { ignore_one_word_acks: Boolean(body.ignoreOneWordAcks) } : {}),
          });
        }
        if (body.persona && typeof body.persona === 'object') {
          writePersona(body.persona);
        }
        if (typeof body.killSwitchActive === 'boolean') {
          if (body.killSwitchActive && !fs.existsSync(KILL_SWITCH_PATH)) {
            fs.writeFileSync(KILL_SWITCH_PATH, 'active\n', 'utf-8');
          } else if (!body.killSwitchActive && fs.existsSync(KILL_SWITCH_PATH)) {
            fs.unlinkSync(KILL_SWITCH_PATH);
          }
        }
        sendJson(response, 200, { success: true, message: 'Settings saved successfully.' });
      } catch (error) {
        sendJson(response, 400, { error: error.message });
      }
      return;
    }

    if (request.method === 'POST' && requestUrl.pathname === '/api/contacts') {
      try {
        const body = await readRequestJson(request);
        const number = String(body.number || '').replace(/\D/g, '');
        const relationship = String(body.relationship || 'unknown').toLowerCase();
        if (!number || number.length < 8) {
          sendJson(response, 400, { error: 'Invalid phone number.' });
          return;
        }
        const validRel = ['family', 'friend', 'professional', 'unknown'];
        if (!validRel.includes(relationship)) {
          sendJson(response, 400, { error: `Relationship must be one of: ${validRel.join(', ')}` });
          return;
        }
        const map = readRelationshipMap();
        map[number] = relationship;
        writeRelationshipMap(map);
        sendJson(response, 200, {
          success: true,
          contacts: Object.entries(map).filter(([k]) => k !== '_default').map(([num, rel]) => ({ number: num, relationship: rel })),
        });
      } catch (error) {
        sendJson(response, 400, { error: error.message });
      }
      return;
    }

    if (request.method === 'DELETE' && requestUrl.pathname === '/api/contacts') {
      try {
        let number = requestUrl.searchParams.get('number');
        if (!number) {
          const body = await readRequestJson(request);
          number = body.number;
        }
        const cleanNumber = String(number || '').replace(/\D/g, '');
        const map = readRelationshipMap();
        delete map[cleanNumber];
        writeRelationshipMap(map);
        sendJson(response, 200, {
          success: true,
          contacts: Object.entries(map).filter(([k]) => k !== '_default').map(([num, rel]) => ({ number: num, relationship: rel })),
        });
      } catch (error) {
        sendJson(response, 400, { error: error.message });
      }
      return;
    }

    if (request.method === 'POST' && requestUrl.pathname === '/api/test-message') {
      try {
        const body = await readRequestJson(request);
        const text = String(body.text || 'Hello! How are you?').trim();
        const relationship = String(body.relationship || 'friend').trim();
        const jid = body.jid || '919812345670@s.whatsapp.net';
        const payload = {
          jid,
          text,
          message_type: 'text',
          is_forwarded: false,
          from_me: false,
        };
        const activityId = recordActivity({
          jid,
          incoming: `[Simulation] ${text}`,
          messageType: 'text',
          relationship,
          status: 'processing',
          reason: 'Evaluating simulated message',
          reply: '',
        });
        const result = await sendToBridge(payload);
        updateActivity(activityId, {
          relationship: result.relationship || relationship,
          status: result.should_reply ? 'candidate' : 'ignored',
          reason: result.reason || 'Simulation completed',
          reply: result.reply || '',
        });
        sendJson(response, 200, { success: true, activityId, result });
      } catch (error) {
        sendJson(response, 500, { error: error.message });
      }
      return;
    }

    if (request.method === 'POST' && requestUrl.pathname === '/api/session/logout') {
      try {
        const result = await resetWhatsAppSession();
        sendJson(response, 200, {
          connection: connectionState,
          warning: result.warning,
        });
      } catch (error) {
        lastConnectionError = `Could not reset the login: ${error.message}`;
        connectionState = 'error';
        logger.error({ err: error }, '[AUTH] session reset failed');
        sendJson(response, 500, { error: lastConnectionError });
      }
      return;
    }

    if (request.method === 'POST' && requestUrl.pathname === '/api/live') {
      try {
        const body = await readRequestJson(request);
        if (typeof body.enabled !== 'boolean') {
          sendJson(response, 400, { error: 'enabled must be true or false' });
          return;
        }
        if (body.enabled && connectionState !== 'connected') {
          sendJson(response, 409, { error: 'Link your WhatsApp account before enabling live replies.' });
          return;
        }
        if (body.enabled) {
          const readiness = await getBridgeReadiness();
          if (!readiness.bridgeReady) {
            sendJson(response, 503, { error: readiness.bridgeError });
            return;
          }
          if (!readiness.aiConfigured) {
            sendJson(response, 503, {
              error: 'AI replies are unavailable. Configure your GROQ_API_KEY in the settings panel.',
            });
            return;
          }
        }
        if (body.enabled && fs.existsSync(KILL_SWITCH_PATH)) {
          if (body.clearKillSwitch !== true) {
            sendJson(response, 409, { error: 'Confirm clearing the emergency stop before enabling live replies.' });
            return;
          }
          fs.unlinkSync(KILL_SWITCH_PATH);
        }
        liveRepliesEnabled = body.enabled;
        sendJson(response, 200, { liveRepliesEnabled });
      } catch (error) {
        sendJson(response, 400, { error: error.message });
      }
      return;
    }

    sendJson(response, 404, { error: 'Not found' });
  });

  server.listen(WEB_PORT, '127.0.0.1', () => {
    logger.info(`Local web console available at http://127.0.0.1:${WEB_PORT}`);
  });
}

async function resetWhatsAppSession() {
  if (sessionResetInProgress) {
    throw new Error('A login reset is already in progress.');
  }

  sessionResetInProgress = true;
  const wasConnected = connectionState === 'connected';
  connectionState = 'logging_out';
  liveRepliesEnabled = false;
  qrImage = null;
  pairingCode = null;
  connectedUserInfo = null;
  lastConnectionError = '';
  if (reconnectTimer) {
    clearTimeout(reconnectTimer);
    reconnectTimer = null;
  }

  const socket = whatsappSocket;
  whatsappSocket = null;
  let warning = '';
  if (socket) {
    try {
      if (typeof socket.ev?.removeAllListeners === 'function') {
        socket.ev.removeAllListeners('connection.update');
        socket.ev.removeAllListeners('creds.update');
        socket.ev.removeAllListeners('messages.upsert');
      }
      if (wasConnected) {
        await Promise.race([
          socket.logout().catch(() => {}),
          new Promise((resolve) => setTimeout(resolve, 1500)),
        ]);
      }
      try {
        socket.end(new Error('Login reset requested.'));
      } catch {}
    } catch (error) {
      warning = `WhatsApp logout note: ${error.message}`;
      logger.error({ err: error }, '[AUTH] fast logout fallback');
    }
  }

  try {
    await fs.promises.rm(authDir, { recursive: true, force: true });
  } catch (error) {
    logger.warn({ err: error.message }, '[AUTH] could not immediately clean authDir, continuing');
  }

  sessionResetInProgress = false;
  connectionState = 'connecting';
  lastConnectionError = warning;
  await connectToWhatsApp();
  return { warning };
}

async function connectToWhatsApp() {
  if (startupInProgress) {
    logger.warn('[ROUTE] startup already in progress; skipping duplicate connect attempt');
    return null;
  }

  startupInProgress = true;
  connectionState = 'connecting';

  try {
    fs.mkdirSync(authDir, { recursive: true });
    const { state, saveCreds } = await useMultiFileAuthState(authDir);
    const sock = makeWASocket({
      auth: state,
      printQRInTerminal: false,
      logger: pino({ level: 'silent' }),
      browser: ['Chrome', 'macOS', '10.0'],
    });
    whatsappSocket = sock;

    sock.ev.on('connection.update', (update) => {
      if (sock !== whatsappSocket) return;

      const { connection, lastDisconnect, qr } = update;

      if (qr) {
        logger.info('[ROUTE] pairing QR code received');
        QRCode.toDataURL(qr, { margin: 2, width: 260 })
          .then((image) => {
            if (sock === whatsappSocket && connectionState !== 'connected') {
              qrImage = image;
              connectionState = 'pairing';
            }
          })
          .catch((error) => {
            lastConnectionError = `Could not render pairing QR: ${error.message}`;
            logger.error({ err: error.message }, '[ROUTE] QR rendering failed');
          });
      }

      if (connection === 'open') {
        connectionState = 'connected';
        qrImage = null;
        pairingCode = null;
        lastConnectionError = '';
        reconnectAttempts = 0;
        const jid = sock.user?.id || '';
        const phone = jid ? jid.split('@')[0].split(':')[0] : '';
        connectedUserInfo = {
          name: sock.user?.name || 'WhatsApp Account',
          phone,
          jid,
        };
        logger.info({ user: connectedUserInfo }, '[ROUTE] WhatsApp connection open');
        if (reconnectTimer) {
          clearTimeout(reconnectTimer);
          reconnectTimer = null;
        }
      }

      if (connection === 'close') {
        whatsappSocket = null;
        connectedUserInfo = null;
        pairingCode = null;
        if (sessionResetInProgress) {
          connectionState = 'logging_out';
          return;
        }

        const statusCode = lastDisconnect?.error?.output?.statusCode;
        const reason = lastDisconnect?.error?.output?.payload?.message || 'unknown';
        const needsNewLogin = [
          DisconnectReason.loggedOut,
          DisconnectReason.forbidden,
          DisconnectReason.multideviceMismatch,
          DisconnectReason.badSession,
        ].includes(statusCode);
        connectionState = needsNewLogin ? 'logged_out' : 'reconnecting';
        qrImage = null;
        liveRepliesEnabled = false;
        lastConnectionError = statusCode === DisconnectReason.loggedOut
          ? 'WhatsApp logged out this device. Reset the login to scan a new QR code.'
          : statusCode === DisconnectReason.badSession
            ? 'The saved WhatsApp login is invalid. Reset the login to scan a new QR code.'
            : statusCode === DisconnectReason.multideviceMismatch
              ? 'The saved WhatsApp session no longer matches. Reset the login to scan a new QR code.'
              : statusCode === DisconnectReason.forbidden
                ? 'WhatsApp refused the connection. Check your account and network, then reset the login.'
                : reason;
        logger.warn({ statusCode, reason }, '[ROUTE] connection closed');

        const shouldReconnect = !needsNewLogin;
        if (statusCode === DisconnectReason.restartRequired) {
          logger.warn('[ROUTE] restart required');
        }

        if (shouldReconnect) scheduleReconnect();
      }
    });

    sock.ev.on('creds.update', saveCreds);

    sock.ev.on('messages.upsert', async (event) => {
      const messageEvent = event?.messages?.[0];
      if (!messageEvent) return;

      const msgType = event?.type;
      if (msgType !== 'notify') {
        console.log('[SKIP] history sync message, ignoring');
        return;
      }

      const message = messageEvent.message;
      const remoteJid = messageEvent.key?.remoteJid;
      const fromMe = messageEvent.key?.fromMe === true;

      if (fromMe) {
        console.log('[SKIP] own message');
        return;
      }

      if (!remoteJid) {
        console.log('[SKIP] message missing remoteJid');
        return;
      }

      const text = getMessageText(message);
      const messageType = getMessageType(message);
      const isForwarded = getIsForwarded(message);

      const payload = {
        jid: remoteJid,
        text,
        message_type: messageType,
        is_forwarded: isForwarded,
        from_me: false,
      };

      logger.info({ messageType }, '[ROUTE] processing incoming notify message');
      const activityId = recordActivity({
        jid: remoteJid,
        incoming: text || `[${messageType} message]`,
        messageType,
        relationship: 'checking',
        status: 'processing',
        reason: 'Checking reply rules',
        reply: '',
      });

      let response;
      try {
        response = await sendToBridge(payload);
      } catch (error) {
        const status = axios.isAxiosError(error) ? error.response?.status : null;
        const reason = status
          ? `Decision bridge returned HTTP ${status}.`
          : 'Could not reach the local decision bridge.';
        updateActivity(activityId, {
          status: 'error',
          reason,
        });
        logger.error({ err: error.message, status }, '[ROUTE] bridge request failed');
        return;
      }

      if (
        !response
        || typeof response !== 'object'
        || typeof response.should_reply !== 'boolean'
        || (response.should_reply
          ? typeof response.reply !== 'string' || !response.reply.trim()
          : response.reply !== null)
        || typeof response.relationship !== 'string'
        || !response.relationship.trim()
        || typeof response.reason !== 'string'
        || !response.reason.trim()
      ) {
        updateActivity(activityId, {
          status: 'error',
          reason: 'The local decision bridge returned an invalid response.',
        });
        logger.error('[DECISION] invalid response from bridge');
        return;
      }

      const shouldReply = response.should_reply;
      const replyText = response.reply;
      const reason = response.reason;
      const relationship = response.relationship;
      const decisionFailed = !shouldReply && reason.startsWith('intent check failed closed: LLM error:');

      logger.info(
        { shouldReply, relationship, reason },
        '[DECISION] decision from bridge'
      );

      updateActivity(activityId, {
        relationship,
        status: shouldReply && replyText
          ? 'candidate'
          : decisionFailed
            ? 'error'
            : 'ignored',
        reason,
        reply: replyText || '',
      });

      if (shouldReply && replyText && String(replyText).trim()) {
        if (relationship === 'unknown' || relationship === 'group') {
          updateActivity(activityId, { status: 'blocked', reason: 'Sender is not allowlisted' });
          logger.warn({ jid: remoteJid, relationship }, '[SEND] blocked: sender is not allowlisted');
          return;
        }

        if (fs.existsSync(KILL_SWITCH_PATH)) {
          updateActivity(activityId, { status: 'blocked', reason: 'Emergency kill switch is active' });
          logger.warn({ jid: remoteJid }, '[SEND] blocked: emergency kill switch is active');
          return;
        }

        if (!liveRepliesEnabled) {
          updateActivity(activityId, { status: 'dry_run', reason: 'Live replies are disabled' });
          logger.info('[DRY_RUN] live replies are disabled; reply not sent');
          return;
        }

        const currentSettings = readRuntimeSettings();
        const minMs = Math.max(1, Number(currentSettings.min_delay_seconds) || 3) * 1000;
        const maxMs = Math.max(minMs, Number(currentSettings.max_delay_seconds) || 8) * 1000;
        const delayMs = randomDelayMs(minMs, maxMs);
        logger.info({ delayMs }, '[SEND] waiting before reply');
        await sleep(delayMs);

        try {
          await sock.sendMessage(remoteJid, { text: replyText });
          updateActivity(activityId, { status: 'sent', reason: 'Reply sent' });
          logger.info('[REPLY] sent reply');
        } catch (error) {
          updateActivity(activityId, { status: 'failed', reason: error.message });
          logger.error({ err: error.message }, '[SEND] failed to deliver reply');
        }
        return;
      }

      logger.info({ reason }, '[DECISION] ignoring message');
    });

    return sock;
  } finally {
    startupInProgress = false;
  }
}

async function main() {
  startWebConsole();
  await connectToWhatsApp();
}

main().catch((error) => {
  logger.error({ err: error }, '[ROUTE] startup failed');
  process.exit(1);
});
