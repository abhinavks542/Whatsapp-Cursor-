# WhatsApp Cursor

WhatsApp Cursor runs a local WhatsApp Web client and a local AI decision bridge.
The existing WhatsApp console stays at `http://127.0.0.1:5002/`; the Sahayak
concept preview is separate at `http://127.0.0.1:5002/sahayak`.

## Start on Windows

Install the Python dependencies once:

```powershell
py -3 -m pip install -r requirements.txt
npm install
```

Then start the local bridge and WhatsApp client together:

```powershell
npm start
```

The launcher opens the console in your browser. Scan its QR code using
**WhatsApp → Linked devices → Link a device**. To sign out and pair a different
account, use **Log out & get a new QR** in the console.

## Enable AI replies

AI replies stay in dry-run until explicitly enabled. To generate replies, set a
valid Groq API key in the project-root `.env` file. If `.env` does not already
exist, create it from the example first (do not overwrite an existing `.env`):

```powershell
Copy-Item .env.example .env
```

```dotenv
GROQ_API_KEY=your_groq_api_key_here
GROQ_MODEL=openai/gpt-oss-20b
```

Keep `.env` private; never paste API keys into chat or commit them. Restart the
launcher after changing the file. The console reports when the bridge is
unavailable or the AI key is missing. Without a key, prompt classification
fails closed and live replies cannot be enabled.

The local login is stored under `auth_info_baileys`. It is only removed when you
explicitly choose the logout/reset action. Incoming messages are processed only
for contacts in the relationship allowlist; groups and unknown contacts are
blocked. Live replies require a separate confirmation in the console.

## Sahayak concept preview

`/sahayak` is a separate visual concept page. It does not read browser tabs,
call an AI service, or perform browser actions.
