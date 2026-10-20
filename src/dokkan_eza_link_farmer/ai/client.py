from __future__ import annotations

import logging
import re
from typing import Any

import requests

from dokkan_eza_link_farmer.ai.models import AIConfig, AIModelFamily

logger = logging.getLogger(__name__)


class DokkanAIClient:
    """Client for local or remote open AI models (Qwen 2.5 and DeepSeek-R1-Distill)."""

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

    def chat_completion(
        self,
        messages: list[dict[str, str]],
        temperature: float | None = None,
        max_tokens: int = 2048,
        response_format: dict[str, Any] | None = None,
    ) -> tuple[str, str | None]:
        """
        Sends a chat completion request to the AI model.
        Returns a tuple: (content, reasoning_chain).
        Extracts DeepSeek-R1 <think> tags or reasoning_content fields.
        """
        url = self._get_endpoint("chat/completions")
        headers = {
            "Authorization": f"Bearer {self.config.api_key}",
            "Content-Type": "application/json",
        }
        payload: dict[str, Any] = {
            "model": self.config.model_name,
            "messages": messages,
            "temperature": self.config.temperature if temperature is None else temperature,
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

            choice = res_json.get("choices", [{}])[0]
            message = choice.get("message", {})
            raw_content = message.get("content", "") or ""
            reasoning = message.get("reasoning") or message.get("reasoning_content")

            # If model is DeepSeek-R1 and returned <think> tags in main content
            if not reasoning and "<think>" in raw_content:
                think_match = re.search(r"<think>(.*?)</think>", raw_content, re.DOTALL)
                if think_match:
                    reasoning = think_match.group(1).strip()
                    raw_content = re.sub(
                        r"<think>.*?</think>", "", raw_content, flags=re.DOTALL
                    ).strip()

            return raw_content.strip(), reasoning
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
        Generates tactical advice and turn strategy for a Dokkan team.
        Adapts system instructions according to whether Qwen or DeepSeek-R1 is active,
        enforcing the 3-level Dokkan Battle priority hierarchy:
        1. Leader skill category coverage (200% / 170%)
        2. Card kit effects (Active, Passive, Standby, Stacking, Guard, DR %, Dodge, Revive, Domain, Taunt)
        3. Link skills for rotation pairing and Ki management.
        """
        is_deepseek = self.config.model_family == AIModelFamily.DEEPSEEK_R1
        lang_instruction = "Rispondi in italiano." if language == "it" else "Respond in English."

        if is_deepseek:
            system_prompt = (
                "Sei un assistente esperto e tattico di Dragon Ball Z: Dokkan Battle specializzato "
                "in eventi di altissima difficoltà (Red Zone, Supreme Magnificent Battle, Super Battle Road). "
                "Segui rigorosamente questa gerarchia di priorità tattica nel tuo ragionamento (Chain of Thought):\n"
                "1. PRIORITÀ 1 - Copertura Leader Skill: Verifica che tutte le unità siano coperte al 200% o 170% dalla Leader Skill.\n"
                "2. PRIORITÀ 2 - Effetti delle Carte & Kit: Analizza Passive, Active Skill, Standby, Stacking infinito di ATK/DEF, "
                "Guard garantita, Damage Reduction % e Dodge. Posiziona in Slot 1 le unità con la migliore difesa (Guard/DR/Stacking) "
                "e sfrutta Active/Standby/Revive nei momenti critici del combattimento.\n"
                "3. PRIORITÀ 3 - Link Skill: Ottimizza i collegamenti Ki (Prepared for Battle, Shocking Speed, Over in a Flash) "
                "e i boost alle statistiche (Big Bad Bosses, Fierce Battle) nelle due rotazioni principali (Slot 1 + Slot 2), "
                "delegando buffer, orb changer e unità secondarie al ruolo di Floater (Slot 3).\n"
                f"{lang_instruction}"
            )
        else:
            # Qwen 2.5 optimized: direct, structured, actionable
            system_prompt = (
                "Sei un assistente esperto e tattico di Dragon Ball Z: Dokkan Battle. "
                "Fornisci una guida strategica chiara e strutturata seguendo la gerarchia del gioco:\n"
                "1. **Copertura Leader**: Verifica il moltiplicatore (200%/170%) per tutte le unità.\n"
                "2. **Kit ed Effetti Chiave**: Spiega chi difende in Slot 1 (Guard, Damage Reduction %, DEF Stacking) e chi infligge danni in Slot 2 (Active, Standby, Crits, Additionals).\n"
                "3. **Link Skill & Rotazioni**: Illustra la sinergia dei link nelle rotazioni e il ruolo dei 3 Floater (Slot 3).\n"
                "4. **Gestione Fasi & Item**: Consiglia quando usare Support Item (Whis/Ghost Usher), Revive o Standby contro le fasi del boss.\n"
                f"Sii conciso e diretto. {lang_instruction}"
            )

        user_content = f"Team da analizzare:\n{team_summary}\n"
        if boss_info:
            user_content += f"\nEvento / Boss target:\n{boss_info}\n"

        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_content},
        ]

        return self.chat_completion(messages)
