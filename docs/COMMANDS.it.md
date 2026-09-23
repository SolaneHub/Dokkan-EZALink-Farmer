[ 🇬🇧 English ](COMMANDS.md) | [ 🇮🇹 Italiano ](COMMANDS.it.md)

---

# 🎮 Guida ai Comandi e Utilizzo - Dokkan-EZALink-Farmer

> ⚠️ **IMPORTANTE - AMBITO DI UTILIZZO:**  
> Questo strumento è **esclusivamente specializzato** per due compiti endgame:
> 1. **Extreme Z-Battle (EZA fino a Lv. 999):** Scalata automatica e farming infinito di Statue di Mister Satan di Platino (~1.5M Zeni a vittoria).
> 2. **Stanza dello Spirito e del Tempo:** Link Level farming via evento dedicato con ricambio continuo e automatico del team.
>
> Il bot **NON** gestisce le Quest/Story Mode, non esegue Summon, né farma medaglie o eventi storia generici.

---

## 💻 1. Avvio del Bot (Launcher 1-Click & Standalone)

Puoi avviare il bot direttamente con un **doppio clic** (senza aprire manualmente il terminale):
* **Su Windows:** Doppio clic su `Launch-Dokkan-EZALink.bat`.
* **Su macOS:** Doppio clic su `Launch-Dokkan-EZALink.command` (apre automaticamente il Terminale ed esegue il binario standalone; rimuove in automatico la quarantena di Gatekeeper).
* **Su Linux:** Doppio clic su `Launch-Dokkan-EZALink.sh` (oppure `./Launch-Dokkan-EZALink.sh` da terminale).

> 💡 **Nota macOS:** Se esegui il binario direttamente da terminale invece di usare `.command`, rimuovi l'attributo di quarantena scaricato dal browser con: `xattr -dr com.apple.quarantine .`

---

In alternativa, puoi aprirlo da qualsiasi riga di comando:

```bash
# Windows (PowerShell / CMD):
.\Launch-Dokkan-EZALink.bat
# oppure con Python:
python main.py

# macOS / Linux:
./Launch-Dokkan-EZALink
```

---

## ⚡ 2. Parametri e Flag da Riga di Comando

Puoi passare argomenti diretti all'eseguibile per eseguire compiti specifici senza entrare nella console interattiva:

| Flag | Argomento | Descrizione |
|---|---|---|
| `--lang`, `-l` | `[en\|it]` | Imposta la lingua dell'interfaccia (default: `en`, opzioni: `en`, `it`) |
| `--doctor` | *nessuno* | Esegue la diagnostica completa dell'ambiente (scrcpy, adb, OS, telefoni collegati) |
| `--devices` | *nessuno* | Mostra l'elenco dei dispositivi Android collegati via USB o Wi-Fi |
| `--eza` | `[livello=999]` | Naviga automaticamente agli Eventi EZA, scorre fino in fondo, individua il primo EZA non a 999 e avvia la scalata fino al livello indicato (default: `999`) |
| `--link` | `[run]` | Avvia il Link Level farming sulla Stanza dello Spirito e del Tempo (stage "1. Saiyan Training", difficoltà SUPER) con ricostruzione automatica del team con filtri "Released" e "Level Up Possible" (opzionale: default fino a esaurimento stamina) |
| `--boost` / `--no-boost` | *nessuno* | Attiva (`--boost`) o disattiva forzatamente (`--no-boost`) l'uso delle cariche Boost durante il Link Level farming |
| `--scrcpy` | *nessuno* | Apre la finestra di mirroring a latenza zero dello schermo del telefono |
| `--discord` | *nessuno* | Avvia il bot in background collegato a Discord per il controllo remoto |
| `--config` | `<percorso>` | Specifica un file di configurazione personalizzato (default: `config/settings.yaml`) |

### Esempi Rapidi:
```bash
# Esegui la diagnosi preliminare dell'ambiente (ADB, Scrcpy, risoluzioni):
./Launch-Dokkan-EZALink --doctor

# Esegui la diagnosi forzando l'interfaccia in italiano:
./Launch-Dokkan-EZALink --lang it --doctor

# Avvia direttamente la scalata continua dell'EZA senza conferme:
./Launch-Dokkan-EZALink --eza

# Esegui 30 run della Stanza dello Spirito e del Tempo per i Link:
./Launch-Dokkan-EZALink --link 30

# Apri la finestra video di mirroring dello smartphone sul computer:
./Launch-Dokkan-EZALink --scrcpy
```

---

## ⌨️ 3. Console Interattiva CLI (`dokkan-farmer>`)

Eseguire il file senza parametri avvia la console interattiva Rich con log colorati in tempo reale e statistiche di farming.

### Comandi Disponibili nella Console:

| Comando | Sintassi | Descrizione |
|---|---|---|
| `doctor` / `check` | `doctor` | Verifica la presenza di ADB, scrcpy, compatibilità del sistema e dispositivi connessi |
| `devices` | `devices` | Mostra l'elenco di tutti i dispositivi Android rilevati |
| `connect` | `connect [seriale]` | Connette al dispositivo specificato o rileva automaticamente il primo disponibile |
| `scrcpy` | `scrcpy` | Apre la finestra di mirroring a schermo del dispositivo fisico |
| `scrcpy-stop` | `scrcpy-stop` | Chiude la finestra di visualizzazione scrcpy |
| `inspect` / `state` | `inspect` | Cattura lo schermo del gioco e identifica la schermata attuale |
| `shot` | `shot [nome.png]` | Scatta e salva uno screenshot dello schermo su disco |
| `eza` | `eza [livello\|auto]` | Apre il menu interattivo DokkanDB (frecce e ricerca) o avvia la scalata fino a 999 |
| `link` | `link [run] [boost]` | Avvia il farming dei link con ricambio continuo delle carte al livello 10 (default: fino a esaurimento stamina) |
| `discord` | `discord [setup\|start]` | Avvia il setup guidato interattivo (`discord setup`) o avvia il bot in ascolto (`discord start`) |
| `status` | `status` | Mostra lo stato attuale del bot, le statistiche Zeni e l'attività in corso |
| `lang` | `lang [en\|it]` | Visualizza o cambia la lingua al volo |
| `pause` | `pause` | Mette in pausa temporanea l'attività in corso |
| `resume` | `resume` | Riprende l'attività messa in pausa |
| `stop` | `stop` | Interrompe immediatamente e in sicurezza l'attività in corso |
| `help` | `help` | Mostra la tabella di riepilogo dei comandi nella lingua attiva |
| `exit` / `quit` | `exit` | Chiude l'applicazione |

---

## 🤖 4. Controllo Remoto tramite Discord

Dokkan-EZALink-Farmer include un bot Discord integrato per controllare e monitorare il farming da remoto tramite Slash Command (`/status`, `/screenshot`, `/eza`, `/link`, ecc.).

### ⚡ Setup Guidato delle Credenziali (Nuovo Metodo Consigliato):

Non è necessario modificare manualmente i file YAML! Puoi configurare il bot in pochi secondi direttamente tramite il wizard interattivo:

1. **Dalla Console Interattiva CLI:**
   ```text
   dokkan-farmer> discord setup
   ```
2. **Oppure da Terminale / Riga di Comando:**
   ```bash
   # Con Python:
   python main.py --discord

   # Con il launcher (Windows):
   .\Launch-Dokkan-EZALink.bat --discord

   # Con l'eseguibile standalone (macOS / Linux):
   ./Launch-Dokkan-EZALink --discord
   ```
   Se il bot non è ancora configurato, il wizard guidato si avvierà automaticamente chiedendoti di incollare:
   - **Bot Token**: il token ottenuto dal Discord Developer Portal
   - **ID Canale**: l'ID del canale testuale in cui inviare aggiornamenti e screenshot
   - **ID Utente (opzionale)**: il tuo ID utente Discord per riservare i comandi solo a te

   Il bot validerà e salverà le impostazioni in modo sicuro e persistente.

> 📖 Per la guida dettagliata passo-passo su come creare l'applicazione su Discord Developer Portal e ottenere il Token in 2 minuti, consulta la [Guida Setup Discord](DISCORD_SETUP.it.md).

### 🚀 Avvio del Bot Discord:

Una volta configurato, puoi avviare la modalità Discord in qualsiasi momento:
- Dalla console CLI: digita `discord start`
- Da terminale: esegui con il flag `--discord` (`.\Launch-Dokkan-EZALink.bat --discord` su Windows o `./Launch-Dokkan-EZALink --discord` su macOS/Linux)

### 🎮 Comandi Slash Disponibili su Discord:
- `/status`: Mostra un riepilogo dettagliato con dispositivo connesso, run completate, stato attuale e statistiche Zeni/Statue di Satan.
- `/screenshot`: Cattura lo schermo dello smartphone/emulatore in tempo reale e invia l'immagine su Discord.
- `/eza [target_level]`: Avvia la navigazione automatica e la scalata dell'EZA fino al livello scelto (default: 999).
- `/link [runs]`: Avvia il farming dei link sulla Stanza dello Spirito e del Tempo.
- `/stop`: Interrompe l'attività da remoto in sicurezza.
- `/pause` / `/resume`: Mette in pausa o riprende l'automazione.
- `/scrcpy [start/stop]`: Apre o chiude la finestra video di mirroring sul PC.

---

## 🛠️ 5. Compilazione dell'Eseguibile Standalone (`scripts/build_dist.py`)

Se modifichi il codice sorgente e desideri ricompilare il pacchetto `dist/Launch-Dokkan-EZALink`:

```bash
# Compilazione in cartella distribuibile (--onedir)
python scripts/build_dist.py

# Oppure compilazione in un singolo file eseguibile (--onefile)
python scripts/build_dist.py --onefile
```
Lo script di compilazione include automaticamente:
1. Python runtime e tutte le dipendenze compilate (`opencv`, `numpy`, `rich`, `discord.py`).
2. Modalità `console=True` (binario console puro, zero interfacce grafiche pesanti).
3. Tutti i template grafici di Dokkan da `templates/glb/`.
4. Copia di `config/settings.yaml`, cataloghi traduzioni `locales/` e guide in `docs/`.
5. Creazione dei file 1-click (`Launch-Dokkan-EZALink.bat`, `Launch-Dokkan-EZALink.command`, `Launch-Dokkan-EZALink.sh`).
