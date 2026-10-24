from __future__ import annotations

import logging
import re
from typing import Any

import requests

from dokkan_eza_link_farmer.ai.models import AIConfig, AIModelFamily

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
        models_url = self._get_endpoint("models")
        headers = {
            "Authorization": f"Bearer {self.config.api_key}",
            "Accept": "application/json",
        }
        try:
            resp = requests.get(models_url, headers=headers, timeout=timeout)
            return resp.status_code == 200
        except Exception:
            # Fallback to ping root or health
            try:
                base_root = self.config.base_url.split("/v1")[0]
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
        return (
            getattr(self.config, "provider", "").lower() == "ollama"
            or "11434" in getattr(self.config, "base_url", "")
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

            if "message" in res_json:
                message = res_json["message"]
                raw_content = message.get("content", "") or ""
                reasoning = None
            else:
                choice = res_json.get("choices", [{}])[0]
                message = choice.get("message", {})
                raw_content = message.get("content", "") or ""
                reasoning = None

            # Strip any residual <think> tags from output
            if "<think>" in raw_content:
                raw_content = re.sub(r"<think>.*?</think>", "", raw_content, flags=re.DOTALL).strip()

            return raw_content.strip(), None
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
                "3. MECCANICHE DIFENSIVE (PASSIVE SKILL): Guardia (Guard), Riduzione Danno (Damage Reduction %), Schivata (Dodge) e Stacking DEF derivano SOLO dalla Passive Skill o Super Attack dell'unità, MAI dai link.\n"
                "4. ROTAZIONI DINAMICHE: Le rotazioni A e B fungono da coppie d'ancoraggio, ma NON sono vincolanti né fisse per l'intero evento. Spiega come adattarle dinamicamente in base alle battaglie, al cambio di elemento del boss e alla presenza di gimmick letali (es. Slot Lock o Cancels Dodge).\n"
                "5. MECCANICA MULTI-BATTAGLIA (RESET STACKING): Se l'evento è composto da battaglie separate, evidenzia chiaramente che lo stacking di ATK & DEF si AZZERA a inizio di ciascuna nuova battaglia! Le unità dipendenti solo dallo stacking necessitano di protezione al Turno 1.\n"
                "6. OGGETTI DI SUPPORTO (EFFETTI REALI):\n"
                "   - Whis: Riduce il danno subito del 40% per 2 turni.\n"
                "   - Ghost Usher: Salta l'intero turno di attacco del nemico per 1 turno.\n"
                "   - Princess Snake: Recupera il 55% di HP e riduce il danno subito del 30% per 1 turno.\n"
                "   (Revive, Standby e Active Skill NON sono oggetti usabili, ma abilità intrinseche dei singoli personaggi).\n"
                "7. Rispondi TASSATIVAMENTE in lingua ITALIANA in modo chiaro e schematico (massimo 18-25 righe).\n\n"
                "STRUTTURA OBBLIGATORIA:\n"
                "### 🛡️ Rotazioni Tattiche & Flessibilità Dinamica\n"
                "- **Rotazione A**: Spiega perché lo Slot 1 difende (tank) e il ruolo di Slot 2 (dps/link).\n"
                "- **Rotazione B**: Ruolo difensivo di Slot 1 e offensivo di Slot 2.\n"
                "- **Floaters (Slot 3)**: Unità che ruotano fuori turno, il loro compito (supporto/cambio orbi/danni secondari) e raccomandazioni sui colpi nemici.\n"
                "- **Adattamento Dinamico**: Come aggiustare le rotazioni nelle varie battaglie/fasi in base ai tipi elementali del boss e ai gimmick (es. Cancels Dodge/Coercion).\n\n"
                "### 💊 Gestione Oggetti di Supporto & Meccaniche Fasi\n"
                "- **Whis / Ghost Usher / Princess Snake**: Quando attivarli strategicamente (es. turni iniziali di nuova battaglia con stacking azzerato, turni con molti attacchi sul floater o contro la Super Attack della fase finale)."
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
                "3. DEFENSIVE MECHANICS: Guard, Damage Reduction %, Dodge, and Stacking DEF come SOLELY from Passive Skills or Super Attacks, NEVER from links.\n"
                "4. DYNAMIC ROTATIONS: Rotations A & B serve as anchor pairs, but are NOT rigid. Explain how to flexibly adapt positioning across battles based on enemy typing and lethal gimmicks (Cancels Dodge, Slot Lock).\n"
                "5. MULTI-BATTLE MECHANICS: In multi-battle stages, emphasize that ATK & DEF stacking RESETS to 0 at the start of each new battle! Units relying purely on stacking must be protected on Turn 1.\n"
                "6. REAL SUPPORT ITEMS:\n"
                "   - Whis: Reduces damage received by 40% for 2 turns.\n"
                "   - Ghost Usher: Delays all enemy attacks for 1 turn.\n"
                "   - Princess Snake: Recovers 55% HP and reduces damage received by 30% for 1 turn.\n"
                "   (Revive, Standby, and Active Skills are NOT support items, but character abilities).\n"
                "7. Keep the response concise (max 18-25 lines).\n\n"
                "MANDATORY STRUCTURE:\n"
                "### 🛡️ Tactical Rotations & Dynamic Flexibility\n"
                "- **Rotation A**: Why Slot 1 defends (tank) and Slot 2 damages (dps/links).\n"
                "- **Rotation B**: Defensive role of Slot 1 and offensive role of Slot 2.\n"
                "- **Floaters (Slot 3)**: Units rotating off-turn and their utility (support/orb changing).\n"
                "- **Dynamic Adaptation**: How to adjust positioning across battles/phases based on boss typing and mechanics.\n\n"
                "### 💊 Support Item Strategy & Battle Phases\n"
                "- **Whis / Ghost Usher / Princess Snake**: When to activate them against dangerous enemy turns, fresh battles with reset stacks, or lethal Super Attacks."
            )
            user_content = f"Selected Team Composition:\n{team_summary}\n"
            if boss_info:
                user_content += f"\nTarget Boss / Event:\n{boss_info}\n"

        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_content},
        ]

        return self.chat_completion(messages)
