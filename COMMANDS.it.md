[ 🇬🇧 English ](COMMANDS.md) | [ 🇮🇹 Italiano ](COMMANDS.it.md)

---

# 🎮 Guida ai Comandi e Utilizzo - DokkanBattleBot

Questa guida contiene l'elenco completo di tutti i comandi disponibili, le opzioni di avvio da terminale, l'utilizzo della console interattiva e l'integrazione con Discord.

---

## 💻 1. Avvio dell'Eseguibile Standalone (Cartella `dist/`)

Il bot è compilato come binario terminale puro (console). Non richiede l'installazione di Python né di librerie esterne.

Apri il terminale (PowerShell / Prompt dei Comandi su Windows, Terminale / iTerm su macOS / Linux), posizionati nella cartella estratta ed esegui:

### Su Windows:
```powershell
cd dist\dokkan-bot
.\dokkan-bot.exe
```

### Su macOS / Linux:
```bash
cd dist/dokkan-bot
chmod +x dokkan-bot
./dokkan-bot
```

*(In alternativa, in ambiente di sviluppo con Python, puoi eseguire `python main.py`)*.

---

## ⚡ 2. Parametri e Flag da Riga di Comando

Puoi passare argomenti diretti all'eseguibile per eseguire compiti specifici senza entrare nella console interattiva:

| Flag | Argomento | Descrizione |
|---|---|---|
| `--lang`, `-l` | `[en\|it]` | Imposta la lingua dell'interfaccia (default: `en`, opzioni: `en`, `it`) |
| `--doctor` | *nessuno* | Esegue la diagnostica completa dell'ambiente (scrcpy, adb, OS, telefoni collegati) |
| `--devices` | *nessuno* | Mostra l'elenco dei dispositivi Android collegati via USB o Wi-Fi |
| `--eza` | `[livello=999]` | Naviga automaticamente agli Eventi EZA, scorre fino in fondo, individua il primo EZA non a 999 e avvia la scalata fino al livello indicato (default: `999`) |
| `--farm` | `[run=10]` | Avvia il farming a ripetizione dello stage attualmente aperto sul telefono per N run (default: `10`) |
| `--link` | `[run]` | Avvia il Link Level farming sulla Stanza dello Spirito e del Tempo (stage "1. Saiyan Training", difficoltà SUPER) con ricostruzione automatica del team con filtri "Released" e "Level Up Possible" (opzionale: default fino a esaurimento stamina) |
| `--boost` / `--no-boost` | *nessuno* | Attiva (`--boost`) o disattiva forzatamente (`--no-boost`) l'uso delle cariche Boost durante il Link Level farming |
| `--scrcpy` | *nessuno* | Apre la finestra di mirroring a latenza zero dello schermo del telefono |
| `--discord` | *nessuno* | Avvia il bot in background collegato a Discord per il controllo remoto |
| `--config` | `<percorso>` | Specifica un file di configurazione personalizzato (default: `config/settings.yaml`) |

### Esempi Rapidi:
```bash
# Diagnostica di sistema in inglese (default)
./dokkan-bot --doctor

# Diagnostica di sistema in italiano
./dokkan-bot --lang it --doctor

# Avvia direttamente la scalata EZA fino a 999
./dokkan-bot --eza

# Avvia 30 run di Link Level farming
./dokkan-bot --link 30

# Avvia la finestra video scrcpy
./dokkan-bot --scrcpy
```

---

## ⌨️ 3. Console Interattiva CLI (`dokkan-bot>`)

Avviando l'eseguibile senza parametri aggiuntivi, entrerai nella console interattiva Rich con log colorati in tempo reale.

### Comandi Disponibili nella Console:

| Comando | Sintassi | Descrizione |
|---|---|---|
| `doctor` / `check` | `doctor` | Esegue la verifica di ADB, scrcpy, compatibilità OS e telefoni collegati |
| `devices` | `devices` | Elenca tutti i dispositivi Android connessi |
| `connect` | `connect [seriale]` | Connette al dispositivo specificato o auto-rileva il primo disponibile |
| `scrcpy` | `scrcpy` | Apre la finestra di mirroring dello schermo |
| `scrcpy-stop` | `scrcpy-stop` | Chiude la finestra video di scrcpy |
| `inspect` / `state` | `inspect` | Cattura la schermata corrente e mostra lo stato di gioco rilevato |
| `eza` | `eza [livello\|auto]` | Apre il selettore interattivo DokkanDB (frecce ↑/↓ e ricerca) o avvia direttamente se specificato |
| `events` | `events` | Visualizza gli eventi e Z-Battle disponibili recuperati da DokkanDB |
| `farm` | `farm [run]` | Avvia il farming a ripetizione dello stage selezionato |
| `link` | `link [run] [boost]` | Avvia il Link Level farming con auto-sostituzione delle unità al MAX (default: fino a esaurimento stamina) |
| `status` | `status` | Mostra la tabella di riepilogo con le statistiche e l'attività in corso |
| `lang` | `lang [en\|it]` | Visualizza o modifica dinamicamente a runtime la lingua del bot |
| `pause` | `pause` | Mette temporaneamente in pausa l'attività di farming |
| `resume` | `resume` | Riprende l'attività messa in pausa |
| `stop` | `stop` | Interrompe immediatamente l'attività in esecuzione |
| `help` | `help` | Mostra la tabella di riepilogo di tutti i comandi |
| `exit` / `quit` | `exit` | Chiude l'applicazione in sicurezza |

---

## 🤖 4. Controllo Remoto tramite Discord

Puoi gestire il bot direttamente da qualsiasi canale Discord autorizzato, con supporto completo agli Slash Commands:

### Configurazione (`config/settings.yaml`):
```yaml
discord:
  token: "INSERISCI_IL_TUO_TOKEN_DISCORD"
  channel_id: 123456789012345678  # ID canale per notifiche e screenshot
  allowed_user_ids: []             # ID autorizzati (vuoto = chiunque nel canale)
```

### Avvio modalità Discord:
```bash
./dokkan-bot --discord
```

### Slash Commands Disponibili su Discord:
- `/status`: Mostra una card con dispositivo connesso, run completate, stato attuale e statistiche Zeni/Statue Platino.
- `/screenshot`: Cattura lo schermo del gioco e invia l'immagine istantanea nella chat di Discord.
- `/eza [target_level]`: Avvia la navigazione e il farming dell'EZA fino al livello indicato.
- `/farm [runs]`: Avvia il farming automatico di uno stage.
- `/link [runs]`: Avvia il Link Leveling automatico (opzionale: se omesso, prosegue fino a esaurimento stamina).
- `/stop`: Arresta l'attività in corso da remoto.
- `/pause` / `/resume`: Mette in pausa o riprende l'automazione.
- `/scrcpy [start/stop]`: Controlla la finestra di mirroring sul computer.

---

## 🛠️ 5. Compilazione del Binario Standalone (`build_dist.py`)

Se modifichi il codice sorgente e desideri ricreare la cartella `dist/dokkan-bot`:

```bash
# Compilazione cartella standalone distribuibile (--onedir)
python build_dist.py

# Oppure compilazione in singolo file eseguibile (--onefile)
python build_dist.py --onefile
```
Lo script provvede automaticamente a:
1. Impacchettare l'interprete e tutte le dipendenze native (`opencv`, `numpy`, `rich`, `discord.py`).
2. Configurare la modalità `console=True` (sempre e solo terminale).
3. Incorporare tutti i template grafici categorizzati in `templates/glb/`.
4. Copiare il file modificabile `config/settings.yaml`, i cataloghi di traduzione `locales/` e le guide `COMMANDS.md` / `COMMANDS.it.md` nella cartella di destinazione.
