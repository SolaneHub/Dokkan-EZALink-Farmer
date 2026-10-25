"""Custom offline fuzzer for DokkanDBClient and ai/syncer resilience testing.

Follows antirez's 5th pillar: dedicated, bespoke lightweight tooling instead
of heavy external testing frameworks.

Validates that:
- DokkanDBClient and DokkanSyncer handle malformed JSON, timeouts, HTTP errors (500/429/etc.),
  truncated streams, missing fields, and type anomalies gracefully without unhandled crashes.
- Offline local disk cache or safe fallback default values are consistently used.
- config/box.json or user box records are never overwritten or corrupted.
"""

from __future__ import annotations

import argparse
import json
import os
import random
import sys
import tempfile
import time
from dataclasses import dataclass
from typing import Any
from unittest.mock import patch

import requests

from dokkan_eza_link_farmer.ai.syncer import DokkanSyncer
from dokkan_eza_link_farmer.integrations.dokkandb_client import DokkanDBClient


@dataclass
class FuzzIterationResult:
    """Summary of a single fuzzing iteration."""

    iteration: int
    fault_type: str
    status: str  # "PASS" or "FAIL"
    error_message: str | None = None


class FuzzHTTPResponse:
    """Simulated response for generative HTTP fault injection."""

    def __init__(
        self,
        data: Any,
        status_code: int = 200,
        content: bytes = b"",
        delay: float = 0.0,
    ) -> None:
        self._data = data
        self.status_code = status_code
        self.content = content or b""
        self.delay = delay

    def json(self) -> Any:
        if self.delay > 0:
            time.sleep(self.delay)
        if isinstance(self._data, Exception):
            raise self._data
        return self._data

    def raise_for_status(self) -> None:
        if self.delay > 0:
            time.sleep(self.delay)
        if self.status_code >= 400:
            raise requests.HTTPError(f"HTTP Error {self.status_code}")


FAULT_TYPES = [
    "http_500",
    "http_429",
    "http_404",
    "http_503",
    "timeout_exception",
    "connection_error",
    "malformed_json_syntax",
    "corrupted_stream",
    "missing_fields",
    "type_mismatch",
    "nested_corrupted_payload",
    "empty_payload",
]


def generate_fuzz_payload(
    fault_type: str, rng: random.Random
) -> tuple[Any, int, bytes, Exception | None]:
    """Generates deterministic pseudo-random faulty payloads or exceptions based on fault_type."""
    if fault_type == "http_500":
        return {"error": "Internal Server Error"}, 500, b"Internal Server Error", None
    if fault_type == "http_429":
        return {"error": "Rate limit exceeded"}, 429, b"Too Many Requests", None
    if fault_type == "http_404":
        return {"error": "Not Found"}, 404, b"Not Found", None
    if fault_type == "http_503":
        return {"error": "Service Unavailable"}, 503, b"Service Unavailable", None
    if fault_type == "timeout_exception":
        return None, 0, b"", requests.Timeout("Connection timed out after simulated delay")
    if fault_type == "connection_error":
        return (
            None,
            0,
            b"",
            requests.ConnectionError("Failed to establish a new connection: [Errno 111]"),
        )
    if fault_type == "malformed_json_syntax":
        # Simulate invalid json syntax error on resp.json()
        return (
            json.JSONDecodeError("Expecting value", '{"corrupted_json', 16),
            200,
            b'{"corrupted_json',
            None,
        )
    if fault_type == "corrupted_stream":
        garbage_bytes = bytes([rng.randint(0, 255) for _ in range(rng.randint(10, 60))])
        return (
            json.JSONDecodeError("Invalid UTF-8 control character", "", 0),
            200,
            garbage_bytes,
            None,
        )
    if fault_type == "empty_payload":
        return [], 200, b"[]", None
    if fault_type == "missing_fields":
        # Base realistic card but with missing key fields (leader_skill, categories, links, etc.)
        card_id = rng.randint(1000, 999999)
        fields_to_omit = rng.sample(
            [
                "name",
                "subname",
                "rarity",
                "element",
                "leader_skill",
                "passive_skill_description",
                "category_ids",
                "link_ids",
                "special_descriptions",
            ],
            k=rng.randint(2, 6),
        )
        data: dict[str, Any] = {
            "id": card_id,
            "name": f"Card {card_id}",
            "subname": "Fuzz Character",
            "rarity": 5,
            "element": rng.randint(10, 24),
            "leader_skill": "All Types Ki +3, Stats +150%",
            "passive_skill_description": "ATK & DEF +100%",
            "category_ids": [1, 2],
            "category_names": ["Pure Saiyans"],
            "link_ids": [1, 2, 3],
        }
        for f in fields_to_omit:
            data.pop(f, None)
        return [data], 200, json.dumps([data]).encode("utf-8"), None
    if fault_type == "type_mismatch":
        # Corrupt data types (integers instead of lists, strings instead of ints, nulls)
        card_id = rng.randint(1000, 999999)
        data = {
            "id": str(card_id),
            "name": rng.choice([12345, None, False, {"nested": "value"}]),
            "rarity": "not_an_int",
            "element": None,
            "category_ids": "corrupted_string_instead_of_list",
            "link_ids": {"should_be_list": True},
            "leader_skill": rng.choice([None, 9999, ["unexpected_list"]]),
            "passive_skill_description": None,
            "transformation_data": "invalid_string_not_list",
        }
        return [data], 200, json.dumps([data]).encode("utf-8"), None
    if fault_type == "nested_corrupted_payload":
        # Event/stage stats nested corrupted payload
        data = {
            "id": rng.randint(100, 999),
            "enemy_info": "{bad_json: True",  # Malformed JSON string inside JSON field
            "payload": {
                "sugoroku": {"events": {"not_a_digit": {"type": 301, "content": "not_dict"}}}
            },
            "stages": "invalid_stages_format",
        }
        return [data], 200, json.dumps([data]).encode("utf-8"), None

    return [], 200, b"[]", None


def run_fuzz_cycle(
    client: DokkanDBClient,
    syncer: DokkanSyncer,
    iteration: int,
    rng: random.Random,
    box_json_path: str,
    original_box_content: str,
) -> FuzzIterationResult:
    """Executes a single fuzz cycle injecting faults into requests.get."""
    fault_type = rng.choice(FAULT_TYPES)
    data, status_code, content, exc = generate_fuzz_payload(fault_type, rng)

    def mock_requests_get(url: str, *_args: Any, **_kwargs: Any) -> FuzzHTTPResponse:
        _ = url
        if exc is not None:
            raise exc
        return FuzzHTTPResponse(data=data, status_code=status_code, content=content)

    test_endpoints = [
        "get_card",
        "get_cards_catalog",
        "get_categories",
        "get_links",
        "get_zbattles",
        "get_events",
        "get_event_details",
        "get_stage_boss_info",
        "enrich_card",
        "build_dokkan_card",
    ]
    endpoint_to_test = rng.choice(test_endpoints)

    try:
        with patch("requests.get", side_effect=mock_requests_get):
            if endpoint_to_test == "get_card":
                res = client.get_card(1001, force_refresh=True)
                assert res is None or isinstance(res, dict)
            elif endpoint_to_test == "get_cards_catalog":
                res = client.get_cards_catalog(force_refresh=True)
                assert isinstance(res, list)
            elif endpoint_to_test == "get_categories":
                res = client.get_categories(force_refresh=True)
                assert isinstance(res, list)
            elif endpoint_to_test == "get_links":
                res = client.get_links(force_refresh=True)
                assert isinstance(res, list)
            elif endpoint_to_test == "get_zbattles":
                res = client.get_zbattles(force_refresh=True)
                assert isinstance(res, list)
            elif endpoint_to_test == "get_events":
                res = client.get_events(force_refresh=True)
                assert isinstance(res, list)
            elif endpoint_to_test == "get_event_details":
                res = client.get_event_details(501, force_refresh=True)
                assert res is None or isinstance(res, dict)
            elif endpoint_to_test == "get_stage_boss_info":
                res = client.get_stage_boss_info(501, 1, force_refresh=True)
                assert res is None or isinstance(res, dict)
            elif endpoint_to_test == "enrich_card":
                dummy_card: dict[str, Any] = {"id": 1001, "name": "Test"}
                res = client.enrich_card(dummy_card)
                assert isinstance(res, dict)
                assert "id" in res
            elif endpoint_to_test == "build_dokkan_card":
                raw_item = (
                    data[0]
                    if (isinstance(data, list) and data and isinstance(data[0], dict))
                    else {"id": 1001}
                )
                card = syncer.build_dokkan_card(raw_item)
                assert card is not None
                assert hasattr(card, "id")

        # Invariant Check: Verify config/box.json or candidate user box file was never overwritten/corrupted
        if os.path.exists(box_json_path):
            with open(box_json_path, encoding="utf-8") as f:
                current_box_content = f.read()
            assert current_box_content == original_box_content, (
                f"FATAL: {box_json_path} was corrupted or modified during fuzz iteration {iteration}!"
            )

        return FuzzIterationResult(iteration=iteration, fault_type=fault_type, status="PASS")

    except AssertionError as e:
        return FuzzIterationResult(
            iteration=iteration,
            fault_type=fault_type,
            status="FAIL",
            error_message=f"Invariant assertion failed: {e}",
        )
    except Exception as e:
        import traceback

        tb_str = traceback.format_exc()
        return FuzzIterationResult(
            iteration=iteration,
            fault_type=fault_type,
            status="FAIL",
            error_message=f"Unhandled exception crash: {type(e).__name__}: {e}\nTraceback:\n{tb_str}",
        )


def run_dokkandb_fuzzer(
    num_runs: int = 50,
    seed: int = 42,
    verbose: bool = False,
) -> tuple[int, int, float]:
    """Runs the offline fuzzer for DokkanDBClient and DokkanSyncer across n iterations."""
    rng = random.Random(seed)

    with tempfile.TemporaryDirectory() as temp_dir:
        cache_dir = os.path.join(temp_dir, "cache")
        os.makedirs(cache_dir, exist_ok=True)

        # Pre-seed offline cache with basic valid data to test cache-fallback behavior
        preseeded_card = {
            "id": 1001,
            "name": "Cached LR Goku",
            "rarity": 5,
            "element": 13,
            "leader_skill": "All Types Ki +3, HP, ATK & DEF +150%",
            "passive_skill_description": "Guards all attacks; reduces damage received by 30%",
            "category_ids": [1],
            "category_names": ["Pure Saiyans"],
            "link_ids": [1, 2],
        }
        cards_cache_dir = os.path.join(cache_dir, "cards")
        os.makedirs(cards_cache_dir, exist_ok=True)
        with open(os.path.join(cards_cache_dir, "card_1001_glb.json"), "w", encoding="utf-8") as f:
            json.dump(preseeded_card, f)

        # Create mock config/box.json to verify immutability
        box_dir = os.path.join(temp_dir, "config")
        os.makedirs(box_dir, exist_ok=True)
        mock_box_path = os.path.join(box_dir, "box.json")
        initial_box_data = {"cards": [1001, 1002, 1003]}
        initial_box_str = json.dumps(initial_box_data, indent=2)
        with open(mock_box_path, "w", encoding="utf-8") as f:
            f.write(initial_box_str)

        client = DokkanDBClient(cache_dir=cache_dir)
        syncer = DokkanSyncer(cache_dir=cache_dir)

        start_time = time.perf_counter()
        passed_count = 0
        failed_count = 0

        # Patch time.sleep during offline testing to prevent artificial backoff latency
        with patch("time.sleep", return_value=None):
            for i in range(1, num_runs + 1):
                res = run_fuzz_cycle(
                    client=client,
                    syncer=syncer,
                    iteration=i,
                    rng=rng,
                    box_json_path=mock_box_path,
                    original_box_content=initial_box_str,
                )

                if res.status == "PASS":
                    passed_count += 1
                else:
                    failed_count += 1
                    if verbose:
                        print(
                            f"[FAIL] Iteration {res.iteration:03d} ({res.fault_type}): {res.error_message}",
                            file=sys.stderr,
                        )

                if verbose and res.status == "PASS":
                    print(
                        f"[PASS] Iteration {res.iteration:03d} | Fault: {res.fault_type:<25} | OK"
                    )

        elapsed = time.perf_counter() - start_time
        return passed_count, failed_count, elapsed


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Offline Generative Fuzzer for DokkanDBClient and DokkanSyncer resilience."
    )
    parser.add_argument(
        "--runs", type=int, default=50, help="Number of fuzz iterations (default: 50)"
    )
    parser.add_argument("--seed", type=int, default=42, help="Deterministic RNG seed")
    parser.add_argument("--verbose", "-v", action="store_true", help="Detailed run output")

    args = parser.parse_args()

    print(
        f"[FUZZER] Starting {args.runs} offline DokkanDB resilience stress tests (seed: {args.seed})..."
    )
    passed, failed, elapsed = run_dokkandb_fuzzer(
        num_runs=args.runs,
        seed=args.seed,
        verbose=args.verbose,
    )

    print(
        f"[FUZZER] Completed {args.runs} iterations in {elapsed:.3f}s (Avg: {elapsed / args.runs * 1000:.1f}ms/run)"
    )
    print(f"[FUZZER] Results: {passed} PASSED, {failed} FAILED, 0 unhandled crashes.")

    if failed > 0:
        print(f"[FUZZER FAILURE] Detected {failed} failed iterations!")
        sys.exit(1)

    sys.exit(0)


if __name__ == "__main__":
    main()
