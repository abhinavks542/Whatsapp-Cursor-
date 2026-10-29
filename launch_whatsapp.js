'use strict';

const { spawn } = require('node:child_process');
const path = require('node:path');

const projectRoot = __dirname;
const target = process.argv[2] === '--bridge' ? 'bridge.py' : 'run_live.py';
const scriptPath = path.join(projectRoot, target);
const venvPythonWin = path.join(projectRoot, '.venv', 'Scripts', 'python.exe');
const venvPythonPosix = path.join(projectRoot, '.venv', 'bin', 'python');
const candidates = process.platform === 'win32'
  ? [
      { command: venvPythonWin, args: [scriptPath] },
      { command: 'py', args: ['-3', scriptPath] },
      { command: 'python', args: [scriptPath] },
    ]
  : [
      { command: venvPythonPosix, args: [scriptPath] },
      { command: 'python3', args: [scriptPath] },
      { command: 'python', args: [scriptPath] },
    ];

function runCandidate(index) {
  const candidate = candidates[index];
  if (!candidate) {
    console.error('Python 3 was not found. Install Python 3 and try again.');
    process.exitCode = 1;
    return;
  }

  const child = spawn(candidate.command, candidate.args, {
    cwd: projectRoot,
    stdio: 'inherit',
    windowsHide: false,
  });

  child.once('error', (error) => {
    if (error.code === 'ENOENT' && index + 1 < candidates.length) {
      runCandidate(index + 1);
      return;
    }
    console.error(`Could not start WhatsApp Cursor: ${error.message}`);
    process.exitCode = 1;
  });

  child.once('exit', (code, signal) => {
    if (signal) {
      process.exitCode = signal === 'SIGINT' ? 130 : 143;
      return;
    }
    process.exitCode = code ?? 1;
  });

  for (const signal of ['SIGINT', 'SIGTERM']) {
    process.once(signal, () => {
      if (!child.killed) child.kill(signal);
    });
  }
}

runCandidate(0);
