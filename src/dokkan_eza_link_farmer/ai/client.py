from __future__ import annotations

import contextlib
import logging
import re
from typing import Any

import requests

from dokkan_eza_link_farmer.ai.models import AIConfig

logger = logging.getLogger(__name__)


class DokkanAIClient:
    """Client for local Ollama AI model Qwen 3.5 4B."""

    def __init__(self, config: AIConfig | None = None):
        self.config = config or AIConfig()

    def _get_endpoint(self, path: str = "chat/completions") -> str:
        base = self.config.base_url.rstrip("/")
        clean_path = path.lstrip("/")
        return f"{base}/{clean_path}"

    def is_available(self, timeout: float = 3.0) -> bool:
        """Checks if the local AI inference server (Ollama / vLLM / LM Studio) is responding."""
        if self._is_ollama():
            base_root = self.config.base_url.replace("/v1", "").rstrip("/")
            try:
                resp = requests.get(f"{base_root}/api/tags", timeout=timeout)
                if resp.status_code == 200:
                    return True
            except Exception:
                pass
            try:
                resp = requests.get(base_root, timeout=timeout)
                return resp.status_code == 200
            except Exception:
                return False

        models_url = self._get_endpoint("models")
        headers = {
            "Authorization": f"Bearer {self.config.api_key}",
            "Accept": "application/json",
        }
        try:
            resp = requests.get(models_url, headers=headers, timeout=timeout)
            if resp.status_code == 200:
                return True
        except Exception:
            pass

        # Fallback to ping root or health
        try:
            base_root = self.config.base_url.split("/v1")[0].rstrip("/")
            resp = requests.get(base_root, timeout=timeout)
            return resp.status_code in (200, 404)
        except Exception:
            return False

    def list_available_models(self, timeout: float = 5.0) -> list[str]:
        """Lists model IDs currently registered on the server."""
        models_url = self._get_endpoint("models")
        headers = {
            "Authorization": f"Bearer {self.config.api_key}",
            "Accept": "application/json",
        }
        try:
            resp = requests.get(models_url, headers=headers, timeout=timeout)
            if resp.status_code == 200:
                data = resp.json()
                if "data" in data and isinstance(data["data"], list):
                    return [str(m.get("id")) for m in data["data"] if "id" in m]
        except Exception as e:
            logger.debug(f"Failed to query models list: {e}")
        return []

    def _is_ollama(self) -> bool:
        """Checks if the configured backend is local Ollama."""
        return getattr(self.config, "provider", "").lower() == "ollama" or "11434" in getattr(
            self.config, "base_url", ""
        )

    def chat_completion(
        self,
        messages: list[dict[str, str]],
        temperature: float | None = None,
        max_tokens: int = 2048,
        response_format: dict[str, Any] | None = None,
    ) -> tuple[str, str | None]:
        """
        Sends a chat completion request to Qwen 3.5 4B on Ollama.
        Returns a tuple: (content, reasoning_chain).
        Disables slow <think> tokens for lightning-fast zero-latency inference on RTX 3060 Ti.
        """
        temp = self.config.temperature if temperature is None else temperature
        headers = {
            "Authorization": f"Bearer {self.config.api_key}",
            "Content-Type": "application/json",
        }

        if self._is_ollama():
            url = self.config.base_url.replace("/v1", "").rstrip("/") + "/api/chat"
            payload: dict[str, Any] = {
                "model": self.config.model_name,
                "messages": messages,
                "stream": False,
                "options": {
                    "num_ctx": 8192,
                    "temperature": temp,
                    "num_predict": max_tokens,
                },
                "think": False,
            }
            if response_format and response_format.get("type") == "json_object":
                payload["format"] = "json"
        else:
            url = self._get_endpoint("chat/completions")
            payload = {
                "model": self.config.model_name,
                "messages": messages,
                "temperature": temp,
                "max_tokens": max_tokens,
            }
            if response_format:
                payload["response_format"] = response_format

        try:
            resp = requests.post(
                url, headers=headers, json=payload, timeout=self.config.timeout_seconds
            )
            resp.raise_for_status()
            res_json = resp.json()

            reasoning_content = None
            if "message" in res_json:
                message = res_json["message"]
                raw_content = message.get("content", "") or ""
                reasoning_content = (
                    message.get("thinking") or message.get("reasoning_content") or None
                )
            else:
                choice = res_json.get("choices", [{}])[0]
                message = choice.get("message", {})
                raw_content = message.get("content", "") or ""
                reasoning_content = (
                    message.get("reasoning_content") or choice.get("reasoning") or None
                )
            # Strip any residual <think> tags from output
            if "<think>" in raw_content.lower():
                raw_content = re.sub(
                    r"(?i)<think>.*?</think>", "", raw_content, flags=re.DOTALL
                ).strip()

            return raw_content.strip(), (reasoning_content.strip() if reasoning_content else None)
        except requests.HTTPError as e:
            err_body = ""
            with contextlib.suppress(Exception):
                err_body = e.response.text[:500]
            logger.error(
                f"HTTP error communicating with AI model ({self.config.model_name}): {e}. Server response: {err_body}"
            )
            raise
        except Exception as e:
            logger.error(f"Error communicating with AI model ({self.config.model_name}): {e}")
            raise

    def analyze_team_strategy(
        self,
        team_summary: str,
        boss_info: str | None = None,
        language: str = "it",
    ) -> tuple[str, str | None]:
        """
        Generates tactical advice and turn strategy for a Dokkan team using Qwen 3.5,
        enforcing strict Dokkan Battle mechanics, dynamic rotations, multi-battle stacking resets,
        and zero hallucinations.
        """
        if language == "it":
            system_prompt = (
                "Sei l'assistente tattico esperto di Dragon Ball Z: Dokkan Battle.\n"
                "Genera una guida strategica in ITALIANO, sintetica, professionale e priva di allucinazioni di gioco.\n\n"
                "REGOLE TASSATIVE DI DOKKAN BATTLE:\n"
                "1. NON usare tabelle Markdown (usa ESCLUSIVAMENTE elenchi puntati con emoji per una visualizzazione ottimale a terminale).\n"
                "2. VERITÀ SUI LINK SKILL: I Link Skill aumentano ESCLUSIVAMENTE statistiche (Ki, % ATK, % DEF) quando due carte adiacenti condividono lo stesso link. I Link NON riducono mai il danno subito, NON riducono il Ki del nemico e NON danno recupero HP.\n"
                "3. MECCANICHE DIFENSIVE & ORDINE OPERAZIONI: Formula danno = {[(ATK Nemico x Mod. Tipo) x (1 - DR%)] - DEF Alleato} x Riduzione Guardia (0.5). La Damage Reduction (DR%) agisce A MONTE della DEF (comprime l'attacco del boss prima di sottrarre la DEF). La Guardia agisce A VALLE della DEF (dimezza per 0.5 solo il residuo dopo la DEF, oltre a forzare il Type Mod a 0.8). Non confondere MAI la Guardia con il 50% di DR: unità con sola Guardia e DEF pre-super ordinaria (Naked Guard) subiscono oltre 1 milione di danno da Super Attack Endgame (> 2.5M) e muoiono se messe in Slot 1! Invece, la combinazione Guardia + DR (es. Beast Gohan) è la sinergia suprema. Inoltre, il vantaggio di tipo conferisce già Guardia Naturale (0.9x mod + 0.5 riduzione), rendendo la guardia da passiva ridondante su tali elementi.\n"
                "4. ROTAZIONI DINAMICHE: Le rotazioni A e B fungono da coppie d'ancoraggio, ma NON sono vincolanti né fisse per l'intero evento. Spiega come adattarle dinamicamente in base alle battaglie, al cambio di elemento del boss e alla presenza di gimmick letali (es. Slot Lock o Cancels Dodge).\n"
                "5. MECCANICA MULTI-BATTAGLIA (RESET STACKING): Se l'evento è composto da battaglie separate, evidenzia chiaramente che lo stacking di ATK & DEF si AZZERA a inizio di ciascuna nuova battaglia! Le unità dipendenti solo dallo stacking necessitano di protezione al Turno 1.\n"
                "6. OGGETTI DI SUPPORTO (EFFETTI REALI):\n"
                "   - Whis: Riduce il danno subito del 40% per 2 turni.\n"
                "   - Ghost Usher: Salta l'intero turno di attacco del nemico per 1 turno.\n"
                "   - Princess Snake: Recupera il 55% di HP e riduce il danno subito del 30% per 1 turno.\n"
                "   (Revive, Standby e Active Skill NON sono oggetti usabili, ma abilità intrinseche dei singoli personaggi).\n"
                "7. REGOLA CRITICA SLOT 1 (NO TANK ON-HIT IN SLOT 1) & OTTIMIZZAZIONE SLOT 2:\n"
                "   - Slot 1 Tank: Riservato SOLO a unità con difese garantite PRE-ATTACCO in grado di reggere Super Attack da 2.5M+ (Guardia + DR >= 30%, DR pura >= 65-70%, o Schivata >= 70% se non annullata).\n"
                "   - NON suggerire MAI come Slot 1 primario unità con 'Naked Guard' (guardia passiva senza DR e con bassa DEF pre-super), unità la cui difesa si attiva solo 'quando ricevono un attacco' (when receiving an attack / after receiving an attack / for every attack received / on-hit buildup) o con abilità difensive ad attivazione singola (once only). Se subiscono una Super Attack nemica come primo colpo (Turno 1 / colpo 1), la loro difesa o riduzione non è ancora attiva e vengono ONESHOTTATE!\n"
                "   - Slot 2 Specialist: Le unità con build-up on-hit, Naked Guard o che accumulano difesa su Super Attacco (Stacking DEF) VANNO TASSATIVAMENTE IN SLOT 2. In Slot 2 effettuano prima la Super Attack (attivando il boost DEF post-super e accumulando stack) e solo successivamente subiscono i colpi in sicurezza, attivando le abilità on-hit senza rischio di oneshot pre-super. Mantienile in rotazione principale (Slot 2 ogni 2 turni) per massimizzare la frequenza di stacking e build-up invece di sprecarle come floater in Slot 3.\n"
                "8. REGOLA CRITICA PASSIVE CONDIZIONALI SULLA CATEGORIA/CLASSE NEMICA:\n"
                "   - Unità come Goku God TEQ (1016031) o Caulifla TEQ la cui Riduzione Danno, Guardia o Schivata dipendono da una Categoria o Classe nemica specifica (es. 77% DR solo contro nemici 'Movie Bosses' o 'Pure Saiyans') NON DEVONO MAI essere posizionate come tank o in rotazione principale se anche solo una fase dell'evento (es. Toppo, Goku Black, Cell, Buu) NON appartiene a tale categoria.\n"
                "   - In qualsiasi fase non corrispondente, tali unità hanno 0% DR, 0 Guardia e statistiche base inadeguate, venendo oneshottate in qualsiasi slot vengano messe!\n"
                "9. REGOLA CRITICA DIFENSORI VINCOLATI ALLO SLOT 1 (DIVIETO DI FLOATING IN SLOT 3):\n"
                "   - Unità la cui Guardia o Riduzione Danno si attiva SOLO come 1° attaccante del turno ('As the 1st attacker in a turn' / 'in the 1st slot') NON DEVONO MAI ESSERE MANDATE COME FLOATER IN SLOT 3!\n"
                "   - In Slot 3, la loro condizione non è soddisfatta, perdono ogni guardia e riduzione (0% guardia, 0% DR) e vengono istantaneamente oneshottate. Inoltre, se le loro statistiche base non bastano a reggere la Super Attack del boss in Slot 1, NON devono essere selezionate nel team.\n"
                "10. Rispondi TASSATIVAMENTE in lingua ITALIANA in modo chiaro e schematico (massimo 20-30 righe).\n\n"
                "STRUTTURA OBBLIGATORIA:\n"
                "### 🛡️ Rotazioni Tattiche & Flessibilità Dinamica\n"
                "- **Rotazione A**: Spiega perché lo Slot 1 difende (tank) e il ruolo di Slot 2 (dps/link). Se un'unità accumula difesa subendo colpi (on-hit), specifica di tenerla in Slot 2.\n"
                "- **Rotazione B**: Ruolo difensivo di Slot 1 e offensivo di Slot 2.\n"
                "- **Floaters (Slot 3)**: Unità che ruotano fuori turno, il loro compito (supporto/cambio orbi/danni secondari) e raccomandazioni sui colpi nemici.\n\n"
                "### ⚔️ Guida Fasi & Strategia di Combattimento\n"
                "- **Avvio Scontro (Fase 1 / Battaglia 1)**: Come gestire il Turno 1 e i primi nemici (inclusi gruppi multi-target o attacchi multipli prima di aver accumulato stack di difesa).\n"
                "- **Fasi Intermedie**: Gestione dello stacking, timing delle trasformazioni e Standby skill.\n"
                "- **Fase Finale**: Gestione del boss conclusivo, uso degli oggetti di supporto (Whis, Ghost Usher, Princess Snake) e chiusura della battaglia."
            )
            user_content = f"Composizione del Team selezionato:\n{team_summary}\n"
            if boss_info:
                user_content += f"\nEvento / Boss target:\n{boss_info}\n"
        else:
            system_prompt = (
                "You are an expert tactical advisor for Dragon Ball Z: Dokkan Battle.\n"
                "Generate a concise, factual strategy guide in English with zero game hallucinations.\n\n"
                "STRICT DOKKAN BATTLE RULES:\n"
                "1. DO NOT use Markdown tables (use ONLY bullet points with emojis for clean terminal display).\n"
                "2. LINK SKILL FACTS: Link skills ONLY increase stats (Ki, % ATK, % DEF) between adjacent cards. Links NEVER reduce damage, reduce enemy Ki, or recover HP.\n"
                "3. DEFENSIVE MECHANICS & ORDER OF OPERATIONS: Damage Formula = {[(Enemy ATK x Type Mod) x (1 - DR%)] - Ally DEF} x Guard Reduction (0.5). Damage Reduction (DR%) acts BEFORE DEF subtraction (shrinking raw boss attack). Guard acts AFTER DEF subtraction (halving by 0.5 only what passes DEF, while forcing 0.8x Type Mod). NEVER equate Guard to 50% DR: 'Naked Guard' (guard without DR and average pre-super DEF) takes >1M damage from 2.5M+ Super Attacks in Slot 1 and dies! Conversely, Guard + DR (e.g. Beast Gohan) is the ultimate survival synergy. Also, Natural Type Advantage already confers Natural Guard (0.9x mod + 0.5 reduction), making passive guard mostly redundant on those elements.\n"
                "4. DYNAMIC ROTATIONS: Rotations A & B serve as anchor pairs, but are NOT rigid. Explain how to flexibly adapt positioning across battles based on enemy typing and lethal gimmicks (Cancels Dodge, Slot Lock).\n"
                "5. MULTI-BATTLE MECHANICS: In multi-battle stages, emphasize that ATK & DEF stacking RESETS to 0 at the start of each new battle! Units relying purely on stacking must be protected on Turn 1.\n"
                "6. REAL SUPPORT ITEMS:\n"
                "   - Whis: Reduces damage received by 40% for 2 turns.\n"
                "   - Ghost Usher: Delays all enemy attacks for 1 turn.\n"
                "   - Princess Snake: Recovers 55% HP and reduces damage received by 30% for 1 turn.\n"
                "   (Revive, Standby, and Active Skills are NOT support items, but character abilities).\n"
                "7. CRITICAL SLOT 1 RULE (NO ON-HIT TANKS IN SLOT 1) & SLOT 2 OPTIMIZATION:\n"
                "   - Slot 1 Tank: EXCLUSIVELY for units with guaranteed PRE-ATTACK defenses able to withstand 2.5M+ Super Attacks (Guard + DR >= 30%, raw DR >= 65-70%, or Dodge >= 70% if uncancelled).\n"
                "   - NEVER suggest units with 'Naked Guard' (guard without DR or high pre-super DEF), on-hit buildup (when receiving an attack / after receiving an attack), or once-only defenses as primary Slot 1 tanks. If they take an enemy Super Attack on hit 1, they will be ONESHOTTED!\n"
                "   - Slot 2 Specialist: Units with on-hit buildup, Naked Guard, or DEF stacking on Super Attack MUST BE PLACED IN SLOT 2. In Slot 2, they launch their Super Attack first (triggering post-SA DEF boosts and stacking), allowing them to safely absorb subsequent hits and activate on-hit mechanics without pre-super oneshot risk. Keep them in the main rotation (Slot 2 every 2 turns) to maximize stacking speed instead of wasting them as Slot 3 floaters.\n"
                "8. CRITICAL ENEMY-CONDITIONAL PASSIVE VALIDATION:\n"
                "   - Units such as TEQ SSG Goku (1016031) or TEQ Caulifla whose Damage Reduction, Guard, or Dodge depend on specific enemy categories or classes (e.g. 77% DR against 'Movie Bosses' or 'Pure Saiyans') MUST NEVER be recommended as tanks or main rotation units if ANY phase of the stage (e.g. Toppo, Goku Black, Cell, Buu) lacks those categories.\n"
                "   - In non-matching phases, such units lose all conditional defense and suffer instant fatal oneshots!\n"
                "9. CRITICAL SLOT 1-RESTRICTED DEFENSE (DO NOT FLOAT TO SLOT 3):\n"
                "   - Units whose Guard or Damage Reduction is restricted to 'As the 1st attacker in a turn' / 'in the 1st slot' MUST NEVER BE FLOATED TO SLOT 3!\n"
                "   - In Slot 3, their condition is inactive, they lose all guard and DR (0% guard, 0% DR) and suffer instant oneshots. If they lack raw stats to survive boss Super Attacks in Slot 1, DO NOT include them in the team.\n"
                "10. Keep the response concise (max 20-30 lines).\n\n"
                "MANDATORY STRUCTURE:\n"
                "### 🛡️ Tactical Rotations & Dynamic Flexibility\n"
                "- **Rotation A**: Why Slot 1 defends (tank) and Slot 2 damages (dps/links). If a unit builds defense on-hit, explicitly specify placing them in Slot 2.\n"
                "- **Rotation B**: Defensive role of Slot 1 and offensive role of Slot 2.\n"
                "- **Floaters (Slot 3)**: Units rotating off-turn and their utility (support/orb changing).\n\n"
                "### ⚔️ Phase-by-Phase Battle Strategy\n"
                "- **Battle Opening (Phase 1 / Battle 1)**: How to handle Turn 1 and initial enemies (including multi-target groups or attack barrages before defense stacks build up).\n"
                "- **Mid Phases**: Managing DEF/ATK stacking, transformation timing, and Standby skills.\n"
                "- **Final Phase**: Handling the final boss, optimal support item timing (Whis, Ghost Usher, Princess Snake), and closing out the battle."
            )
            user_content = f"Selected Team Composition:\n{team_summary}\n"
            if boss_info:
                user_content += f"\nTarget Boss / Event:\n{boss_info}\n"

        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_content},
        ]

        return self.chat_completion(messages)
