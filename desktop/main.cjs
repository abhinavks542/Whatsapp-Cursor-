'use strict';

const path = require('node:path');
const { app, BrowserWindow, shell, session } = require('electron');
const { fileURLToPath } = require('node:url');

const CONSOLE_URL = 'http://127.0.0.1:5002';
const INDEX_PATH = path.resolve(__dirname, '..', 'web', 'index.html');
const APP_ID = 'local.whatsapp.3d.console';
let mainWindow = null;

function isAppPage(value) {
  try {
    const url = new URL(value);
    if (url.origin === 'http://127.0.0.1:5002') return true;
    if (url.protocol !== 'file:') return false;
    url.hash = '';
    url.search = '';
    const resolved = path.resolve(fileURLToPath(url));
    return resolved === INDEX_PATH;
  } catch {
    return false;
  }
}

function openExternalHttps(value) {
  try {
    const url = new URL(value);
    if (url.protocol === 'https:') {
      void shell.openExternal(url.href);
    }
  } catch {
    return;
  }
}

function createWindow() {
  const iconPath = path.resolve(__dirname, '..', 'assets', 'icon.png');
  const window = new BrowserWindow({
    width: 1440,
    height: 960,
    minWidth: 400,
    minHeight: 600,
    show: false,
    autoHideMenuBar: true,
    backgroundColor: '#060a0c',
    title: 'WhatsApp AI Pro Console — Executive Dashboard',
    icon: iconPath,
    webPreferences: {
      nodeIntegration: false,
      contextIsolation: true,
      sandbox: true,
      webSecurity: true,
    },
  });
  mainWindow = window;

  window.removeMenu();
  window.once('ready-to-show', () => window.show());
  window.on('closed', () => {
    if (mainWindow === window) mainWindow = null;
  });

  window.webContents.setWindowOpenHandler(({ url }) => {
    openExternalHttps(url);
    return { action: 'deny' };
  });

  window.webContents.on('will-navigate', (event, url) => {
    if (isAppPage(url)) return;
    event.preventDefault();
    openExternalHttps(url);
  });

  // Try loading live console server first, fallback to local index.html
  window.loadURL(CONSOLE_URL).catch(() => {
    window.loadFile(INDEX_PATH).catch((error) => {
      console.error('WhatsApp 3D console page could not be loaded:', error);
      window.close();
    });
  });
}

app.setAppUserModelId(APP_ID);
app.on('web-contents-created', (_event, contents) => {
  contents.on('will-attach-webview', (event) => event.preventDefault());
});

if (app.requestSingleInstanceLock()) {
  app.on('second-instance', () => {
    if (!mainWindow) {
      createWindow();
      return;
    }
    if (mainWindow.isMinimized()) mainWindow.restore();
    mainWindow.focus();
  });

  app.whenReady().then(() => {
    session.defaultSession.setPermissionRequestHandler((_contents, _permission, callback) => {
      callback(false);
    });

    createWindow();

    app.on('activate', () => {
      if (BrowserWindow.getAllWindows().length === 0) createWindow();
    });
  });
} else {
  app.quit();
}

app.on('window-all-closed', () => {
  if (process.platform !== 'darwin') app.quit();
});
