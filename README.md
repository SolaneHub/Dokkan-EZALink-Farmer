# 💥 Dokkan Battle Automation Bot (scrcpy + ADB + Discord)

Bot di automazione avanzato per **Dragon Ball Z: Dokkan Battle (Versione Global)** su dispositivi Android fisici (USB/Wi-Fi), con supporto al controllo via **Terminale interattivo** e **Bot Discord**.

---

## 🚀 Caratteristiche Principali

- 🖥️ **Supporto scrcpy**: Visualizza e interagisci con lo schermo del tuo smartphone direttamente dal Mac a latenza zero.
- 🔄 **Farming Stage Automatico**: Ripete qualsiasi evento o missione selezionata (selezione amico, avvio team, avanzamento mappa, auto-battle 2x, chiusura schermata premi/risultati, rifiuto richieste amicizia).
- ⚔️ **Extreme Z-Battle (EZA) Auto-Climb**: Scala i livelli consecutivi degli EZA (fino al Lv. 30 o oltre per farmare Zeni/Statue di Hercule).
- 🔗 **Link Level Farming**: Ottimizzato per run rapide e ripetute su Quest (es. Area 31-4 o 34-4) con gestione carni (Aged Meat) o stamina.
- 📱 **Terminale Interattivo (Rich CLI)**: Interfaccia a riga di comando con log in tempo reale e tabella di stato.
- 🤖 **Bot Discord Integrato**: Controlla il bot a distanza tramite Slash Commands (`/status`, `/farm`, `/eza`, `/link`, `/screenshot`, `/stop`, `/scrcpy`) e ricevi gli screenshot del gioco direttamente in chat!

---

## 🛠️ Configurazione Iniziale dello Smartphone Android

1. **Abilita le Opzioni Sviluppatore**:
   - Vai su *Impostazioni* -> *Informazioni sul telefono*.
   - Tocca 7 volte la voce *Numero build* (o *Versione MIUI/HyperOS* su Xiaomi).
2. **Abilita il Debug USB**:
   - Vai in *Impostazioni* -> *Sistema* (o *Impostazioni aggiuntive*) -> *Opzioni sviluppatore*.
   - Attiva **Debug USB**.
   - *(Solo Xiaomi/Redmi/Poco)*: Attiva anche **Debug USB (Impostazioni sicurezza)** per consentire al bot di inviare tocchi via ADB.
3. **Collega lo smartphone al Mac**:
   - Collega il cavo USB.
   - Sullo schermo del telefono comparirà un popup: seleziona **Consenti sempre da questo computer** e premi **OK**.

> 💡 **Connessione Senza Cavi (Wi-Fi)**:
> Dopo aver collegato il cavo USB la prima volta, esegui:
> ```bash
> adb tcpip 5555
> adb connect <IP_DEL_TUO_TELEFONO>:5555
> ```
> Ora puoi scollegare il cavo USB e controllare il telefono via Wi-Fi!

---

## 💻 Utilizzo da Terminale (CLI)

1. **Attiva l'ambiente virtuale**:
   ```bash
   cd /Users/veronicalostimolo/Desktop/DokkanBattleBot
   source venv/bin/activate
   ```

2. **Avvia il bot in modalità interattiva**:
   ```bash
   python main.py
   ```

3. **Comandi disponibili nella console `dokkan-bot>`**:
   - `devices` - Mostra la lista dei dispositivi Android rilevati.
   - `connect` - Connette automaticamente il dispositivo.
   - `scrcpy` - Apre la finestra sul Mac per vedere il display del telefono.
   - `scrcpy-stop` - Chiude la finestra di scrcpy.
   - `inspect` - Analizza lo schermo attuale e mostra lo stato rilevato dal bot.
   - `shot [nome.png]` - Salva uno screenshot della schermata attuale.
   - `farm [run]` - Avvia il farming dello stage attuale (es. `farm 15`).
   - `eza [livello]` - Avvia la scalata dell'EZA selezionato fino al livello target (es. `eza 30`).
   - `link [run]` - Avvia il Link Level farming a oltranza (es. `link 30`).
   - `status` - Mostra lo stato e il progresso attuale.
   - `pause` / `resume` - Mette in pausa o riprende l'attività in corso.
   - `stop` - Interrompe l'attività corrente.
   - `exit` - Chiude il programma.

---

## 🤖 Configurazione e Utilizzo con Discord

Il bot include un'integrazione completa con Discord per monitorare e comandare il farming da qualunque luogo (anche da smartphone via Discord!).

### 1. Creare il Bot Discord
1. Vai su [Discord Developer Portal](https://discord.com/developers/applications).
2. Crea una **New Application** (es. `DokkanBot`).
3. Vai nella sezione **Bot**:
   - Clicca su **Reset Token** e copia il tuo Token.
   - Nella sezione **Privileged Gateway Intents**, attiva **Message Content Intent**.
4. Vai nella sezione **OAuth2** -> **URL Generator**:
   - Seleziona gli scope `bot` e `applications.commands`.
   - Seleziona i permessi: `Send Messages`, `Attach Files`, `Embed Links`, `Read Message History`.
   - Copia l'URL generato e aprilo nel browser per invitare il bot nel tuo server Discord.

### 2. Inserire il Token in `config/settings.yaml`
Apri `config/settings.yaml` e inserisci il token:
```yaml
discord:
  token: "IL_TUO_TOKEN_DISCORD"
  channel_id: 123456789012345678  # ID numerico del canale per le notifiche (opzionale)
  allowed_user_ids: []             # ID degli utenti abilitati ai comandi (vuoto = chiunque nel server)
```

### 3. Avviare il Bot in modalità Discord
```bash
python main.py --discord
```

### 4. Comandi Slash su Discord
- `/status` - Mostra lo stato del dispositivo, attività e contatore run.
- `/screenshot` - Cattura lo schermo del gioco e lo invia direttamente nella chat di Discord.
- `/farm [runs]` - Avvia il farming automatico di N run.
- `/eza [target_level]` - Avvia l'avanzamento automatico in Extreme Z-Battle fino al livello desiderato.
- `/link [runs]` - Avvia il Link Level farming.
- `/stop` - Arresta il bot da remoto.
- `/pause` / `/resume` - Mette in pausa o riprende l'automazione.
- `/scrcpy [start/stop]` - Controlla la finestra di mirroring sul Mac.

---

## ⚙️ Configurazione Dettagliata (`config/settings.yaml`)

- `stamina_refill_mode`:
  - `"none"`: Il bot si ferma quando finisce la stamina.
  - `"meat"`: Il bot consuma le Aged Meat disponibili.
  - `"stones"`: Ricarica la stamina usando Dragon Stone.
- `loop_delay`: Intervallo in secondi tra i controlli dello stato di gioco (default `1.5`s).
- `confidence_threshold`: Soglia di accuratezza per il template matching (default `0.78`).

---

## 🎯 Cattura dei Template Personalizzati

I file immagine dei pulsanti sono archiviati in `templates/glb/`. Il bot include coordinate e modelli euristici di fallback per tutte le risoluzioni standard, ma puoi anche catturare template esatti dal tuo dispositivo con lo strumento integrato:

```bash
# Salva uno screenshot completo del gioco
python tools/template_helper.py --screenshot --out schermo.png

# Ritaglia un pulsante e salvalo come template per il bot
# Sintassi: --crop <X> <Y> <Larghezza> <Altezza> <nome_template>
python tools/template_helper.py --crop 750 2100 250 80 button_start
```
