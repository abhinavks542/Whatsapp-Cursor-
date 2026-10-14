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
const KILL_SWITCH_PATH = path.join(__dirname, 'kill_switch.flag');
const WEB_PAGE_PATH = path.join(__dirname, 'web', 'index.html');
const WEB_PORT = 5002;

let reconnectTimer = null;
let startupInProgress = false;
let sessionResetInProgress = false;
let whatsappSocket = null;
let connectionState = 'starting';
let qrImage = null;
let liveRepliesEnabled = false;
let lastConnectionError = '';
const activityEntries = [];
let activitySequence = 0;

function sleep(ms) {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

function randomDelayMs(minMs = 3000, maxMs = 8000) {
  return Math.floor(Math.random() * (maxMs - minMs + 1)) + minMs;
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
  logger.info({ payload }, '[ROUTE] sending payload to bridge');
  try {
    const response = await axios.post(BRIDGE_URL, payload, {
      headers: { 'Content-Type': 'application/json' },
      timeout: 20000,
    });
    logger.info({ status: response.status }, '[DECISION] bridge response received');
    return response.data;
  } catch (error) {
    logger.error({ err: error.message }, '[ROUTE] bridge request failed');
    return null;
  }
}

function sendJson(response, statusCode, value) {
  response.writeHead(statusCode, {
    'Content-Type': 'application/json; charset=utf-8',
    'Cache-Control': 'no-store',
  });
  response.end(JSON.stringify(value));
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

    if (request.method === 'GET' && requestUrl.pathname === '/api/status') {
      sendJson(response, 200, {
        connection: connectionState,
        qr: qrImage,
        liveRepliesEnabled,
        killSwitchActive: fs.existsSync(KILL_SWITCH_PATH),
        lastError: lastConnectionError,
      });
      return;
    }

    if (request.method === 'GET' && requestUrl.pathname === '/api/activity') {
      sendJson(response, 200, activityEntries);
      return;
    }

    if (request.method === 'POST' && requestUrl.pathname === '/api/session/logout') {
      if (!['connected', 'logged_out', 'pairing'].includes(connectionState)) {
        sendJson(response, 409, {
          error: 'Wait for WhatsApp to finish connecting before resetting the login.',
        });
        return;
      }

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
  lastConnectionError = '';
  if (reconnectTimer) {
    clearTimeout(reconnectTimer);
    reconnectTimer = null;
  }

  const socket = whatsappSocket;
  let warning = '';
  if (socket) {
    try {
      if (wasConnected) {
        await socket.logout();
      } else {
        socket.end(new Error('Login reset requested.'));
      }
    } catch (error) {
      warning = `WhatsApp could not confirm remote logout: ${error.message}`;
      logger.error({ err: error }, '[AUTH] remote logout failed');
    }
  }

  whatsappSocket = null;
  try {
    await fs.promises.rm(authDir, { recursive: true, force: true });
  } catch (error) {
    sessionResetInProgress = false;
    throw new Error(`Could not remove saved login files: ${error.message}`);
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

  fs.mkdirSync(authDir, { recursive: true });

  try {
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
        lastConnectionError = '';
        logger.info('[ROUTE] WhatsApp connection open');
        if (reconnectTimer) {
          clearTimeout(reconnectTimer);
          reconnectTimer = null;
        }
      }

      if (connection === 'close') {
        whatsappSocket = null;
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

        if (shouldReconnect && !reconnectTimer) {
          logger.warn('[ROUTE] scheduling reconnect in 3s');
          reconnectTimer = setTimeout(() => {
            reconnectTimer = null;
            connectToWhatsApp().catch((error) => {
              logger.error({ err: error }, '[ROUTE] reconnect failed');
            });
          }, 3000);
        }
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

      logger.info({ payload }, '[ROUTE] processing incoming notify message');
      const activityId = recordActivity({
        jid: remoteJid,
        incoming: text || `[${messageType} message]`,
        messageType,
        relationship: 'checking',
        status: 'processing',
        reason: 'Checking reply rules',
        reply: '',
      });

      const response = await sendToBridge(payload);
      if (!response || typeof response !== 'object') {
        updateActivity(activityId, {
          status: 'error',
          reason: 'No valid response from the local decision bridge',
        });
        logger.warn('[DECISION] no valid response from bridge');
        return;
      }

      const shouldReply = Boolean(response.should_reply);
      const replyText = response.reply || null;
      const reason = response.reason || 'unknown';
      const relationship = response.relationship || 'unknown';

      logger.info(
        { shouldReply, relationship, reason },
        '[DECISION] decision from bridge'
      );

      updateActivity(activityId, {
        relationship,
        status: shouldReply && replyText ? 'candidate' : 'ignored',
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
          logger.info(
            { jid: remoteJid, reply: replyText },
            `[DRY_RUN] live replies are disabled; would reply to ${remoteJid}: ${replyText}`
          );
          return;
        }

        const delayMs = randomDelayMs(3000, 8000);
        logger.info({ jid: remoteJid, delayMs }, '[SEND] waiting before reply');
        await sleep(delayMs);

        try {
          await sock.sendMessage(remoteJid, { text: replyText });
          updateActivity(activityId, { status: 'sent', reason: 'Reply sent' });
          logger.info({ jid: remoteJid, reply: replyText }, '[REPLY] sent reply');
        } catch (error) {
          updateActivity(activityId, { status: 'failed', reason: error.message });
          logger.error({ jid: remoteJid, err: error.message }, '[SEND] failed to deliver reply');
        }
        return;
      }

      logger.info({ jid: remoteJid, reason }, '[DECISION] ignoring message');
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
