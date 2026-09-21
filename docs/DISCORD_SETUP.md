# 🤖 Discord Bot Setup Guide

This guide explains how to create, configure, and connect your own Discord bot to **Dokkan-EZALink-Farmer** in under 2 minutes.

Works seamlessly whether you run the bot from Python source (`python main.py`) or use the standalone executable (`dokkan-eza-link.exe` / macOS / Linux).

---

## 📋 Prerequisites
1. A **Discord** account.
2. A personal Discord server (free to create in 10 seconds with the `+` "Add a Server" button in Discord).

---

## 🛠️ Step 1: Create Your Application on Discord Developer Portal

1. Visit the [Discord Developer Portal](https://discord.com/developers/applications) and sign in with your Discord account.
2. In the top-right corner, click the blue **"New Application"** button.
3. Give your application a name (e.g. `DokkanBot`) and click **Create**.

---

## 🔑 Step 2: Retrieve Bot Token & Enable Intents

1. In the left-hand menu, navigate to **"Bot"**.
2. Under the **Build-A-Bot** section, click **"Reset Token"** (confirm if prompted).
3. Click **"Copy"** to copy your secret **Token**.  
   *(⚠️ Never share this token publicly!)*
4. Scroll down on the same page to **"Privileged Gateway Intents"** and **enable**:
   * ✅ **Message Content Intent**
5. Click **Save Changes** at the bottom of the page.

---

## 📨 Step 3: Invite the Bot to Your Discord Server

1. In the left-hand menu, click **"OAuth2"** ➔ **"URL Generator"**.
2. Under **SCOPES**, check:
   * ✅ `bot`
   * ✅ `applications.commands`
3. Under **BOT PERMISSIONS** (appearing below), check:
   * ✅ `Send Messages`
   * ✅ `Attach Files` (for game screenshots)
   * ✅ `Read Message History`
4. Copy the generated invite link at the bottom (**GENERATED URL**).
5. Paste it in your web browser, select your server, and click **Authorize**.

---

## 🆔 Step 4: Get Channel ID (and your User ID)

1. In Discord, open **User Settings** (gear icon at the bottom left).
2. Go to **Advanced** (in the left sidebar) and **enable** **Developer Mode**.
3. Return to your server:
   * **Channel ID:** Right-click the text channel where you want notifications (e.g. `#general` or `#dokkan-bot`) and click **"Copy Channel ID"**.
   * **(Optional) Your User ID:** Right-click your username and click **"Copy User ID"** (restricts bot command execution to only yourself).

---

## ⚡ Step 5: Connect the Bot

You can configure the bot in two easy ways:

### Option A: Interactive Wizard (Recommended)
Launch the bot console and type:
```text
dokkan-farmer> discord setup
```
Or launch directly from terminal with:
```bash
python main.py --discord
# or with standalone executable:
.\dokkan-eza-link.exe --discord
```
The wizard will prompt you for your Token, Channel ID, and optional User ID, saving everything automatically!

### Option B: Edit `config/settings.yaml` Manually
Open `config/settings.yaml` with any text editor and paste your credentials:
```yaml
discord:
  token: "YOUR_DISCORD_BOT_TOKEN"
  channel_id: 123456789012345678
  allowed_user_ids: [987654321098765432] # (optional, leave [] for anyone in channel)
```

---

## 🎮 Available Discord Commands

Once the bot is running (`python main.py --discord` or `discord start` from console):

| Command | Description |
|---|---|
| `/status` | Shows bot state, completed runs, Hercule statues, and estimated Zeni |
| `/screenshot` | Captures and sends real-time game screenshot |
| `/eza [target_level]` | Starts automated continuous EZA climb (default: 999) |
| `/link [runs]` | Starts Chamber of Spirit and Time farming |
| `/stop` | Stops the running task |
| `/pause` / `/resume` | Pauses or resumes farming |
| `/scrcpy [start/stop]` | Opens or closes scrcpy mirror window on host computer |
