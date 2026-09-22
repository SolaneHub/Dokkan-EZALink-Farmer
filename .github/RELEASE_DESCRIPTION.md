# ⚡ Dokkan-EZALink-Farmer v1.0.0

Automazione da terminale e controllo remoto per **Dragon Ball Z Dokkan Battle**. Specializzato esclusivamente nelle due attività endgame più ripetitive e time-consuming: **scalata continua delle Extreme Z-Battle (EZA fino al livello 999)** e **Link Leveling automatico nella Stanza dello Spirito e del Tempo**.

---

## 🌟 Caratteristiche Principali / Key Features

### ⚔️ Extreme Z-Battle (EZA) Auto-Climber (Lv. 999 & Zeni Farming)
- **Scalata Continua Automatica:** Navigazione automatica tra gli eventi EZA, rilevamento del livello corrente e avanzamento ininterrotto fino al livello 999.
- **Farming Zeni Illimitato:** Guadagno costante di Statue di Mister Satan di Platino (~1.500.000 Zeni per ogni vittoria oltre il livello 30).
- **Gestione Schermate Completa:** Rilevamento automatico di vittoria, sconfitta, amici di supporto, schermate di caricamento e riconnessione.

### 🔮 Link Level Farming (Stanza dello Spirito e del Tempo)
- **Farming Automatico dei Link:** Esecuzione continua dello stage dedicato *"1. Saiyan Training"* a difficoltà SUPER.
- **Ricambio Continuo del Team (Smart Rotation):** Quando un personaggio raggiunge il livello 10 su tutti i link, il bot lo rileva, apre la selezione del team, applica automaticamente i filtri *"Sbloccato"* e *"Aumento livello possibile"* e lo sostituisce con una nuova unità da livellare.
- **Gestione Boost & Stamina:** Utilizzo opzionale delle cariche Boost e controllo automatico della barra stamina.

### 🤖 Controllo Remoto tramite Bot Discord Integrato
- **Setup Guidato in 1 Minuto:** Configura Token e ID Canale direttamente dalla console interattiva con `discord setup` o `--discord`.
- **Slash Commands Remoti:** Gestisci il bot da qualunque canale Discord autorizzato con `/status`, `/screenshot`, `/eza`, `/link`, `/stop`, `/pause`, `/resume`, `/scrcpy`.
- **Screenshot in Tempo Reale:** Invia uno snapshot istantaneo dello schermo del telefono direttamente nella chat Discord.

### 🖥️ Console Interattiva CLI & Diagnostica di Sistema
- **Interfaccia Console Rich:** Tabella dei comandi, log colorati e statistiche di farming in tempo reale.
- **Suite Diagnostica (`--doctor`):** Verifica immediata dell'ambiente, versione ADB, Scrcpy e rilevamento dispositivi Android (USB / Wi-Fi).
- **Mirroring a Schermo Zero-Latenza:** Visualizzazione della schermata di gioco tramite Scrcpy con il comando `scrcpy`.

### 🌐 Supporto Multi-Lingua (EN / IT)
- Interfaccia, diagnostica e comandi completamente bilingue (Inglese e Italiano), commutabili anche al volo con `lang it` / `lang en` o tramite flag `--lang it`.

### 📦 Eseguibili Standalone Zero-Dipendenze
- Distribuzioni standalone compilate per **Windows (x64)**, **macOS (Apple Silicon & Intel)** e **Linux (x64)**.
- Nessuna necessità di installare Python, OpenCV o altre librerie esterne.
- Avvio rapido con 1 clic tramite `Launch-Dokkan-EZALink.bat` (Windows), `Launch-Dokkan-EZALink.command` (macOS) o `Launch-Dokkan-EZALink.sh` (Linux).

---

## 📥 Istruzioni Rapide / Quick Start

1. Scarica lo zip corrispondente al tuo sistema operativo dagli Assets sottostanti:
   - **Windows:** `dokkan-eza-link-windows-x64.zip`
   - **macOS:** `dokkan-eza-link-macos.zip`
   - **Linux:** `dokkan-eza-link-linux-x64.zip`
2. Estrai la cartella sul tuo computer.
3. Collega il tuo smartphone Android con Debug USB attivo (o avvia il tuo emulatore).
4. Fai doppio clic sul launcher per il tuo OS:
   - Su Windows: `Launch-Dokkan-EZALink.bat` (o `dokkan-eza-link.exe`)
   - Su macOS: `Launch-Dokkan-EZALink.command`
   - Su Linux: `Launch-Dokkan-EZALink.sh`
5. Per collegare Discord: digita `discord setup` nella console interattiva oppure avvia con `--discord`.

---

**Full Changelog**: https://github.com/SolaneHub/Dokkan-EZALink-Farmer/commits/v1.0.0
