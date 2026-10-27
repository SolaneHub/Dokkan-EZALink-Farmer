"""Downloads all Dokkan Battle cards released from the 10th Anniversary (~2025-01-28) to present

from DokkanDB and saves them into data/dokkan_cards_post_10th_anniversary.json.
Includes all base cards and their transformation/exchange/standby forms.
"""

import json
import logging
import os
import time
from concurrent.futures import ThreadPoolExecutor, as_completed

from dokkan_eza_link_farmer.integrations.dokkandb_client import DokkanDBClient

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("Post10thDownloader")


def download_post_10th_cards(
    output_path: str = "data/dokkan_cards_post_10th_anniversary.json",
    start_date: str = "2025-01-28",
    region: str = "glb",
    max_workers: int = 4,
) -> dict:
    os.makedirs(os.path.dirname(os.path.abspath(output_path)), exist_ok=True)
    db = DokkanDBClient()

    logger.info(f"Fetching card catalog for region: {region}...")
    catalog = db.get_cards_catalog(region=region)
    if not catalog:
        logger.warning("GLB catalog empty, attempting JP catalog...")
        catalog = db.get_cards_catalog(region="jp")
        region = "jp"

    # Filter cards starting from 10th anniversary
    eligible_catalog_cards = [
        c
        for c in catalog
        if str(c.get("open_at") or "") >= start_date
        or str(c.get("open_at_update") or "") >= start_date
    ]
    logger.info(
        f"Found {len(eligible_catalog_cards)} catalog cards released or updated since {start_date}"
    )

    # Collect unique card IDs and transformation IDs
    target_ids = set()
    for c in eligible_catalog_cards:
        cid = c.get("id")
        if cid:
            target_ids.add(int(cid))
        trans_ids = c.get("transformation_ids") or []
        for tid in trans_ids:
            if tid:
                target_ids.add(int(tid))

    logger.info(f"Total unique card IDs to fetch (including transformations): {len(target_ids)}")

    cards_by_id: dict[int, dict] = {}
    completed = 0
    total = len(target_ids)

    def _fetch_single(cid: int):
        card_data = db.get_card(cid, region=region)
        if not card_data and region == "glb":
            # fallback to JP if not in GLB
            card_data = db.get_card(cid, region="jp")
        return cid, card_data

    logger.info(f"Starting download with {max_workers} worker threads...")
    t0 = time.time()
    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        futures = {executor.submit(_fetch_single, cid): cid for cid in target_ids}
        for future in as_completed(futures):
            cid = futures[future]
            completed += 1
            try:
                card_id, data = future.result()
                if data:
                    cards_by_id[card_id] = data
                    # Check if card data reveals additional transformation IDs not in catalog
                    extra_trans = data.get("transformation_ids") or []
                    for etid in extra_trans:
                        if etid and int(etid) not in target_ids and int(etid) not in cards_by_id:
                            extra_data = db.get_card(int(etid), region=region)
                            if extra_data:
                                cards_by_id[int(etid)] = extra_data
                if completed % 25 == 0 or completed == total:
                    logger.info(
                        f"Progress: {completed}/{total} cards fetched ({(completed / total) * 100:.1f}%)"
                    )
            except Exception as e:
                logger.error(f"Error fetching card {cid}: {e}")

    elapsed = time.time() - t0
    logger.info(f"Downloaded {len(cards_by_id)} cards in {elapsed:.1f}s")

    # Sort cards by open_at descending, then ID
    sorted_cards = sorted(
        cards_by_id.values(),
        key=lambda x: (str(x.get("open_at") or ""), int(x.get("id") or 0)),
        reverse=True,
    )

    result_payload = {
        "metadata": {
            "title": "Dokkan Battle Cards (Post-10th Anniversary to Present)",
            "start_date": start_date,
            "generated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "total_cards": len(sorted_cards),
            "region": region,
        },
        "cards": sorted_cards,
    }

    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(result_payload, f, ensure_ascii=False, indent=2)

    logger.info(f"Successfully saved {len(sorted_cards)} cards to {output_path}")
    return result_payload


if __name__ == "__main__":
    download_post_10th_cards()
