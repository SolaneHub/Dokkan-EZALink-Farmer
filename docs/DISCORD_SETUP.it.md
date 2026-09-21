# 🤖 Guida alla Configurazione del Bot Discord

Questa guida spiega come creare e collegare il proprio bot Discord a **Dokkan-EZALink-Farmer** in meno di 2 minuti.

Funziona sia se esegui il bot dal codice sorgente (`python main.py`) sia se utilizzi l'eseguibile standalone (`dokkan-eza-link.exe` / macOS / Linux).

---

## 📋 Di cosa hai bisogno
1. Un account **Discord**.
2. Un server Discord personale (puoi crearne uno gratuito in 10 secondi con il pulsante `+` "Aggiungi un server" su Discord).

---

## 🛠️ Passo 1: Crea la tua Applicazione su Discord Developer Portal

1. Vai sul [Discord Developer Portal](https://discord.com/developers/applications) ed effettua l'accesso con il tuo account Discord.
2. In alto a destra clicca sul pulsante blu **"New Application"**.
3. Dai un nome al tuo bot (ad esempio `DokkanBot`) e clicca su **Create**.

---

## 🔑 Passo 2: Ottieni il Token del Bot e Abilita i Permessi

1. Nel menu a sinistra dell'applicazione, clicca su **"Bot"**.
2. Nella sezione **Build-A-Bot**, clicca sul pulsante **"Reset Token"** (conferma se richiesto).
3. Clicca su **"Copy"** per copiare il tuo **Token** segreto.  
   *(⚠️ Non condividere mai questo token con nessuno!)*
4. Scorri verso il basso nella stessa pagina fino alla sezione **"Privileged Gateway Intents"** e **attiva**:
   * ✅ **Message Content Intent**
5. Clicca su **Save Changes** in fondo alla pagina.

---

## 📨 Passo 3: Invita il Bot nel tuo Server Discord

1. Nel menu a sinistra, clicca su **"OAuth2"** ➔ **"URL Generator"**.
2. Sotto la voce **SCOPES**, seleziona:
   * ✅ `bot`
   * ✅ `applications.commands`
3. Sotto la voce **BOT PERMISSIONS** (che compare in basso), seleziona:
   * ✅ `Send Messages`
   * ✅ `Attach Files` (per inviare gli screenshot)
   * ✅ `Read Message History`
4. In fondo alla pagina troverai il link generato (**GENERATED URL**): clicca su **Copy**.
5. Incolla questo link nel tuo browser, seleziona il tuo server personale e clicca su **Autorizza**.

---

## 🆔 Passo 4: Trova l'ID del Canale (e il tuo ID Utente)

1. Su Discord, apri le **Impostazioni Utente** (icona a forma di ingranaggio in basso a sinistra).
2. Vai su **Avanzate** (nella barra laterale sinistra) e **attiva** l'opzione **Modalità sviluppatore**.
3. Torna al tuo server:
   * **ID Canale:** Fai clic destro sul canale di testo in cui vuoi che il bot scriva (es. `#generale` o `#dokkan-bot`) e clicca su **"Copia ID canale"**.
   * **(Opzionale) Tuo ID Utente:** Fai clic destro sul tuo profilo/nome utente e clicca su **"Copia ID utente"** (serve se vuoi impedire che altre persone usino i comandi).

---

## ⚡ Passo 5: Collega il Bot

Puoi configurare le credenziali in due modi semplicissimi:

### Modo A: Tramite il Setup Guidato Automatico (Consigliato)
Avvia il bot e digita:
```text
dokkan-farmer> discord setup
```
oppure avvialo da terminale con:
```bash
python main.py --discord
# oppure con l'eseguibile:
.\dokkan-eza-link.exe --discord
```
Il bot ti chiederà di incollare il Token, l'ID del canale e (opzionale) il tuo ID utente, salvando tutto in automatico!

### Modo B: Modificando direttamente `config/settings.yaml`
Apri il file `config/settings.yaml` con qualsiasi editor di testo e incolla i valori:
```yaml
discord:
  token: "INCOLLA_IL_TUO_TOKEN_QUI"
  channel_id: 123456789012345678
  allowed_user_ids: [987654321098765432] # (opzionale, lascia [] per consentire a chiunque nel canale)
```

---

## 🎮 Comandi Disponibili su Discord

Una volta avviato il bot (`python main.py --discord` oppure `discord start` da console), potrai usare questi comandi su Discord:

| Comando | Descrizione |
|---|---|
| `/status` | Mostra lo stato del bot, run completate, statue e Zeni guadagnati |
| `/screenshot` | Cattura e invia in chat lo screenshot in tempo reale di Dokkan Battle |
| `/eza [target_level]` | Avvia la scalata continua dell'EZA (default: 999) |
| `/link [runs]` | Avvia il farm della Stanza dello Spirito e del Tempo |
| `/stop` | Ferma l'attività in corso |
| `/pause` / `/resume` | Mette in pausa o riprende l'attività |
| `/scrcpy [start/stop]` | Apre o chiude la finestra video di mirroring sul PC |
