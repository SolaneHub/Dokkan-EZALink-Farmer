[ 🇬🇧 English ](COMMANDS.md) | [ 🇮🇹 Italiano ](COMMANDS.it.md)

---

# 🎮 Guida ai Comandi e Utilizzo - Dokkan-EZALink-Farmer

> ⚠️ **FUNZIONALITÀ ENDGAME SPECIALIZZATE:**  
> 1. **Extreme Z-Battle (EZA fino a Lv. 999):** Scalata automatica e farming infinito di Statue di Mister Satan di Platino (~1.5M Zeni a vittoria).
> 2. **Stanza dello Spirito e del Tempo / Quest Link Leveling:** Link Level farming ad alta velocità con ricambio continuo e automatico del team.
> 3. **Scanner Autonomo del Box Personaggi:** Catalogazione OCR on-device del box in `config/box.json` arricchita con DokkanDB.
> 4. **AI Team Builder & Risolutore Missioni:** Risoluzione strategica delle missioni (DeepSeek/Qwen) e ottimizzazione matematica delle rotazioni.

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
| `--link` | `[run]` | Avvia il Link Level farming per N run (o fino a esaurimento stamina se omesso). Richiede lo stage interattivo (Area 39-3, Area 35-1, Stanza) se non preimpostato. Esegue il loop veloce via "Attempt Again" e imposta i filtri solo alla Run 1 |
| `--stage` | `[stage_id\|run]` | Esegue lo stage target per l'Endgame AI (es. `10101`, `rz_broly`) oppure lo stage ripetuto per farming |
| `--ur` | *nessuno* | Filtra il box dei personaggi per rarità UR durante il Link Level farming (cumulabile con `--lr`) |
| `--lr` | *nessuno* | Filtra il box dei personaggi per rarità LR durante il Link Level farming (cumulabile con `--ur`) |
| `--scan-box` | `[max_cards]` | Esegue la scansione autonoma del box tramite RapidOCR on-device, sincronizza e arricchisce i dati da DokkanDB, salvando in `~/.dokkan-farmer/cache/user_box.json` e registrando i log di debug in `~/.dokkan-farmer/box_scan.log` |
| `--ai-run` | `[stage_id]` | Avvia il loop autonomo di Trial & Error con memoria episodica contro i boss di Red Zone e Blue Zone (default: `10101` Broly) |
| `--challenge` | `[nome_evento]`| Analizza le missioni dell'evento con l'AI e genera la composizione ottimale del team attingendo da `config/box.json` |
| `--boost` / `--no-boost` | *nessuno* | Attiva (`--boost`) o disattiva forzatamente (`--no-boost`) l'uso delle cariche Boost durante il Link Level farming |
| `--scrcpy` | *nessuno* | Apre la finestra di mirroring a latenza zero dello schermo del telefono |
| `--discord` | *nessuno* | Avvia il bot in background collegato a Discord per il controllo remoto |
| `--config` | `<percorso>` | Specifica un file di configurazione personalizzato (default: `config/settings.yaml`) |

### Esempi Rapidi:
```bash
# Sincronizza e scansiona il tuo Box completo con arricchimento DokkanDB:
dokkan-farmer scan-box

# Avvia la modalità AI Trial & Error contro Broly Red Zone:
dokkan-farmer ai-run --stage 10101
# oppure con lo slug testuale:
dokkan-farmer ai-run --stage rz_broly

# Avvia l'AI Trial & Error contro Beast Gohan (Blue Zone / SMB):
dokkan-farmer ai-run --stage 20101

# Esegui la diagnosi preliminare dell'ambiente (ADB, Scrcpy, risoluzioni):
./Launch-Dokkan-EZALink --doctor

# Esegui la diagnosi forzando l'interfaccia in italiano:
./Launch-Dokkan-EZALink --lang it --doctor

# Avvia direttamente la scalata continua dell'EZA senza conferme:
./Launch-Dokkan-EZALink --eza

# Esegui 30 run di Link Leveling combinando carte UR e LR:
./Launch-Dokkan-EZALink --link 30 --ur --lr

# Esegui il Link Leveling filtrando solo le carte LR:
./Launch-Dokkan-EZALink --link --lr

# Scansiona l'intero box di carte e aggiorna config/box.json:
./Launch-Dokkan-EZALink --scan-box

# Scansiona le prime 100 carte del box:
./Launch-Dokkan-EZALink --scan-box 100

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
| `link` | `link [run] [--ur] [--lr] [--boost]` | Apre il menu a tendina interattivo per la scelta dello stage (Area 39 Stage 3, Area 35 Stage 1, Stanza dello Spirito e del Tempo). Supporta i flag cumulabili `--ur` e `--lr`. Riavvia istantaneamente tramite "Attempt Again" e controlla i filtri solo alla Run 1 |
| `stage` / `farm` | `stage [run] [--boost]` | Ripete il clear dello stage selezionato manualmente nel gioco finché non finisce la stamina (o per N run). Utilizza "Attempt Again" per riavviare istantaneamente e termina in automatico non appena la stamina si esaurisce |
| `scan-box` | `scan-box [max]` | Scansiona il box di carte a cicli di scorrimento continui, estraendo titoli, stelle rainbow, copie e salvando in `~/.dokkan-farmer/cache/user_box.json` con log di debug in `~/.dokkan-farmer/box_scan.log` |
| `ai-run` | `ai-run [stage_id]` | Avvia il loop autonomo Trial & Error con telemetria di combattimento contro i boss di Red Zone e Blue Zone (es. `10101`, `20101`, `rz_broly`) |
| `challenge` / `ai-team` | `challenge [evento]` | Sintetizza la squadra e le rotazioni ottimali per le missioni tramite AI dal box scansionato |
| `discord` | `discord [setup\|start]` | Avvia il setup guidato interattivo (`discord setup`) o avvia il bot in ascolto (`discord start`) |
| `status` | `status` | Mostra lo stato attuale del bot, le statistiche Zeni e l'attività in corso |
| `lang` | `lang [en\|it]` | Visualizza o cambia la lingua al volo |
| `pause` | `pause` | Mette in pausa temporanea l'attività in corso |
| `resume` | `resume` | Riprende l'attività messa in pausa |
| `stop` | `stop` | Interrompe immediatamente e in sicurezza l'attività in corso |
| `help` | `help` | Mostra la tabella di riepilogo dei comandi nella lingua attiva |
| `exit` / `quit` | `exit` | Chiude l'applicazione |

---

## 🧠 4. AI Autonomous Endgame Runner & Box Scanner (Red Zone / Blue Zone)

Dokkan-EZALink-Farmer integra un motore di intelligenza artificiale locale (Ollama DeepSeek-R1 / Qwen) con un Risolutore di Vincoli Matematici e una memoria episodica per affrontare e superare in completa autonomia gli stage più difficili di Dokkan Battle:

### 1. Scansione del Box (`scan-box`):
Esegue la scansione visiva del box tramite OCR on-device, interroga DokkanDB per arricchire abilità passive, skill leader e link skill, salvando l'inventario in `~/.dokkan-farmer/cache/user_box.json` e memorizzando costantemente i log di debug in `~/.dokkan-farmer/box_scan.log`.
```bash
dokkan-farmer scan-box
```

### 2. Catalogo Boss Endgame (`boss_stages.json`):
Contiene gli stage iconici completi di fasi sequenziali, elementi e gimmick reali:
* **Red Zone: Movie Edition - Broly (`10101` / `rz_broly`):** 4 fasi (AGL -> TEQ -> STR AoE -> AGL Cancella Schivata).
* **Red Zone: Red Ribbon Army - Cell Max (`10102` / `rz_cell_max`):** 3 fasi (PHY -> INT -> TEQ AoE + Cancella Schivata + Blocca Slot).
* **Red Zone: Dismal Future - Fusion Zamasu (`10103` / `rz_zamasu`):** 2 fasi (INT AoE -> PHY Blocca Slot).
* **Red Zone: Majin Buu Saga - Kid Buu (`10104` / `rz_kid_buu`):** 2 fasi (TEQ -> PHY Cancella Schivata).
* **Red Zone: GT Edition - Omega Shenron (`10105` / `rz_omega`):** 3 fasi (AGL -> STR AoE -> INT Blocca Slot + Cancella Schivata).
* **Supreme Magnificent Battle (Blue Zone): Beast Gohan (`20101` / `smb_beast_gohan`):** 3 fasi (TEQ -> PHY Blocca Slot -> STR Cancella Schivata + Blocca Slot).
* **Supreme Magnificent Battle (Blue Zone): Super Gogeta (`20102` / `smb_gogeta`):** 3 fasi (AGL -> STR AoE -> PHY Cancella Schivata).
* **Supreme Magnificent Battle (Blue Zone): Evo Blue Vegeta & UI Goku (`20103` / `smb_evo_ui`):** 3 fasi (INT -> AGL -> TEQ Cancella Schivata + Blocca Slot).

### 3. Macchina a Stati a 4 Fasi del Loop di Gioco (`ai-run`):
* **Step A (Inizializzazione):** Carica `user_box.json` e `ai_memory.json`, genera il miglior team iniziale tramite `TeamBuilder` e il solver a vincoli.
* **Step B (Formazione):** Se il team raccomandato differisce da quello attualmente equipaggiato, applica automaticamente la formazione in-game via ADB.
* **Step C (Avvio & Telemetria):** Seleziona il Friend Leader (usando il refresh se opportuno), clicca start, verifica che l'Auto-Battle sia ON (`btn_auto_battle_on.png`) e avvia il loop di osservazione telemetrica (buffer FIFO a 4 frame pre-KO).
* **Step D (Esito):**
  * **Vittoria (`button_ok.png`):** Registra il team come *Winning Team* in `ai_memory.json` e conclude con successo.
  * **Sconfitta (`button_attempt_again.png`):** Genera il `FailureReport` e applica l'albero decisionale:
    1. `InstantRetry`: Boss con HP < 20% nella fase finale o colpa del Friend Leader (slot 7).
    2. `SurgicalSwap` (`SurgicalReplace`): Sostituzione chirurgica della carta colpevole con controllo partner orfano (< 3 link) o Pair Swap.
    3. `LeaderSwitch` (`DemoteLeader`): Retrocessione del leader in caso di 3 sconfitte consecutive ai turni 1-2.

```bash
# Esempio di esecuzione:
dokkan-farmer ai-run --stage 10101
```

---

## 🤖 5. Controllo Remoto tramite Discord

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
- `/link [runs] [stage] [filter_rarity] [boost]`: Avvia il Link Level farming con selezione dello stage (`Area 39 Stage 3`, `Area 35 Stage 1`, `Chamber of Spirit and Time`), filtri di rarità cumulabili (`UR + LR`, `UR`, `LR`), riavvio rapido automatico con "Attempt Again" e ottimizzazione dei filtri solo alla prima run.
- `/stop`: Interrompe l'attività da remoto in sicurezza.
- `/pause` / `/resume`: Mette in pausa o riprende l'automazione.
- `/scrcpy [start/stop]`: Apre o chiude la finestra video di mirroring sul PC.

---

## 🧠 5. AI Team & Mission Solver (Modelli Universali Supportati)

Dokkan-EZALink-Farmer integra modelli LLM locali (tramite Ollama) per analizzare le missioni degli eventi ad alta difficoltà (Red Zone, Supreme Magnificent Battle) e sintetizzare team ottimali dal box scansionato.

### 🌟 I 3 Modelli Universali Ufficialmente Supportati (PC & Mac):

| Nome Modello | Famiglia AI | Caratteristiche Principali | Ideale Per |
|---|---|---|---|
| **`deepseek-r1:7b`** | `deepseek_r1` | Ragionamento logico profondo passo-passo (`<think>`), analisi turn-by-turn dei boss | **Consigliato per PC (RTX 3060 Ti) & Mac (Apple Silicon M2)** |
| **`qwen2.5:7b`** | `qwen` | Risposte dirette, veloci e strutturate in tabelle Markdown | Risposte istantanee su PC e Mac |
| **`qwen2.5:3b`** | `qwen` | Ultraleggero (2 GB VRAM), consumo di batteria e RAM quasi nullo | MacBook Air M2 in mobilità / risparmio energetico |

### 🛠️ Cambio Modello Rapido da CLI:
Dalla console interattiva:
```text
dokkan-farmer> ai switch
```
Seleziona uno dei 3 modelli universali o inserisci un nome modello personalizzato.

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
