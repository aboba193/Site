# Tenet Telegram CRM Bot

## Features
- Website form sends leads to `POST /api/leads`.
- Admin bot receives each lead with action buttons:
  - `Client registered`
  - `Interest: purchase`
  - `Interest: installment`
  - `Interest: trade-in`
  - `Assign to me`
  - `Call`
  - `Defer`
  - `Cancel`
- Queue summary auto-update.
- Reminder messages for open leads.
- Admin commands:
  - `/queue`, `/status`
  - `/new`, `/pending`, `/done`
  - `/stats`
  - `/find <text>`
  - `/export` (CSV)
- Separate sales bot forwards lead details to manager when admin marks interest.

## Run
```powershell
$env:TELEGRAM_BOT_TOKEN="YOUR_ADMIN_BOT_TOKEN"
$env:TELEGRAM_ADMIN_ID="YOUR_ADMIN_CHAT_ID"
$env:TELEGRAM_MANAGER_BOT_TOKEN="YOUR_MANAGER_BOT_TOKEN"
$env:TELEGRAM_MANAGER_CHAT_ID="YOUR_MANAGER_CHAT_ID"
python server.py
```

Open: `http://localhost:8000`

## Optional env overrides
```powershell
$env:TELEGRAM_BOT_TOKEN="..."
$env:TELEGRAM_ADMIN_ID="..."
$env:TELEGRAM_ADMIN_USERNAME="@..."
$env:TELEGRAM_MANAGER_BOT_TOKEN="..."
$env:TELEGRAM_MANAGER_CHAT_ID="..."
$env:TELEGRAM_MANAGER_USERNAME="@..."
$env:DEFER_MINUTES="30"
$env:REMINDER_MINUTES="30"
python server.py
```
