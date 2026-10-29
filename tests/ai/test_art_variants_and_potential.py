"""Tests for Art Variant cards handling in scanner, teambuilder, and Screen 3 Hidden Potential evaluation."""

import numpy as np

from dokkan_eza_link_farmer.ai.art_variants import (
    are_same_card_identity,
    discover_art_variants_from_catalog,
    get_canonical_card_id,
    is_art_variant,
)
from dokkan_eza_link_farmer.ai.models import BossStage, DokkanCard
from dokkan_eza_link_farmer.ai.solver import DokkanConstraintSolver
from dokkan_eza_link_farmer.automation.scanner.detail_evaluator import (
    DetailEvaluator,
    detect_current_card_detail_page,
    ensure_detail_page_3,
)


class FakeADB:
    """Mock ADBClient for testing Screen 3 page navigation."""

    def __init__(self, initial_page: int = 1, screen_size: tuple[int, int] = (1080, 2400)):
        self.current_page = initial_page
        self.w, self.h = screen_size
        self.taps: list[tuple[int, int]] = []

    def get_screen_size(self) -> tuple[int, int]:
        return self.w, self.h

    def tap(self, x: int, y: int, delay_after: float = 0.0) -> None:
        _ = delay_after
        self.taps.append((x, y))
        # Arrow right tapped: advance page
        if x > self.w * 0.5:
            self.current_page = min(5, self.current_page + 1)
        # Arrow left tapped: rewind page
        else:
            self.current_page = max(1, self.current_page - 1)

    def screencap(self) -> np.ndarray:
        return create_mock_screen(page=self.current_page, potential_pct=100)


def create_mock_screen(page: int = 3, potential_pct: int = 100) -> np.ndarray:
    """Creates a synthetic 1080x2400 screen with pagination dots and Screen 3 potential."""
    _ = potential_pct
    img = np.zeros((2400, 1080, 3), dtype=np.uint8)

    # 1. Draw 5 pagination dots around y=2078
    dot_xs = [450, 496, 541, 588, 634]
    y = 2078
    for idx, x in enumerate(dot_xs):
        p_num = idx + 1
        if p_num == page:
            # Orange active dot: B=30, G=120, R=230
            img[y - 5 : y + 6, x - 5 : x + 6] = [30, 120, 230]
        else:
            # Gray inactive dot: B=150, G=150, R=150
            img[y - 5 : y + 6, x - 5 : x + 6] = [150, 150, 150]

    return img


# =============================================================================
# 1. ART VARIANT IDENTITY & MAPPING TESTS
# =============================================================================


def test_art_variant_mappings_and_canonical_id():
    # Test known pairs
    # Gogeta LR Variant (1034761) -> Base (1012901)
    assert is_art_variant(1034761) is True
    assert is_art_variant(1012901) is False
    assert get_canonical_card_id(1034761) == 1012901
    assert get_canonical_card_id(1012901) == 1012901
    assert are_same_card_identity(1034761, 1012901) is True

    # Vegito LR Variant (1034741) -> Base (1012931)
    assert is_art_variant(1034741) is True
    assert get_canonical_card_id(1034741) == 1012931
    assert are_same_card_identity(1034741, 1012931) is True

    # SSJ3 Goku Angel Variant (1034481) -> Base (1028791)
    assert is_art_variant(1034481) is True
    assert get_canonical_card_id(1034481) == 1028791
    assert are_same_card_identity(1034481, 1028791) is True

    # SSG Goku Variant (1034461) -> Base (1026251)
    assert is_art_variant(1034461) is True
    assert get_canonical_card_id(1034461) == 1026251
    assert are_same_card_identity(1034461, 1026251) is True

    # Unrelated cards must not be equal
    assert are_same_card_identity(1034761, 1034741) is False
    assert are_same_card_identity(1034761, 9999999) is False


def test_dokkan_card_canonical_identity_and_serialization():
    # Base card
    card_base = DokkanCard(
        id=1012901,
        name="Super Saiyan Goku & Super Saiyan Vegeta",
        subname="Fused Super Power",
        potential_percent=55,
    )
    assert card_base.canonical_identity == 1012901
    assert card_base.is_art_variant is False

    # Variant card
    card_var = DokkanCard(
        id=1034761,
        name="Super Saiyan Goku & Super Saiyan Vegeta",
        subname="Fused Super Power",
        potential_percent=100,
        is_rainbow=True,
    )
    assert card_var.canonical_identity == 1012901
    assert card_var.is_art_variant is True

    # Round-trip serialization
    d = card_var.to_dict()
    assert d["canonical_id"] == 1012901
    assert d["is_art_variant"] is True

    deserialized = DokkanCard.from_dict(d)
    assert deserialized.id == 1034761
    assert deserialized.canonical_identity == 1012901
    assert deserialized.is_art_variant is True


def test_discover_art_variants_from_catalog():
    fake_catalog = [
        {
            "id": 9000001,
            "name": "Test Warrior",
            "subname": "Ultimate Stand",
            "rarity": 5,
            "element": 10,
            "tag": "1",
            "card_unique_info_id": 999,
        },
        {
            "id": 9000002,
            "name": "Test Warrior",
            "subname": "Ultimate Stand",
            "rarity": 5,
            "element": 10,
            "tag": "11",  # Alternative Art tag
            "card_unique_info_id": 999,
        },
    ]
    discovered = discover_art_variants_from_catalog(fake_catalog)
    assert 9000002 in discovered
    assert discovered[9000002] == 9000001
    assert get_canonical_card_id(9000002) == 9000001
    assert are_same_card_identity(9000002, 9000001) is True


# =============================================================================
# 2. TEAMBUILDER & SOLVER DEDUPLICATION TESTS
# =============================================================================


def test_solver_excludes_variant_and_base_on_same_team():
    """Verifies that solver will NEVER put both variant and base card on the same team."""
    solver = DokkanConstraintSolver()

    # Create dummy boss stage
    boss = BossStage(
        stage_id=1,
        event_id=1,
        stage_name="Test Boss",
        event_name="Test Event",
        difficulty=5,
        phases=[],
    )

    # 1. Leader (gives 200% to 'Fused Fighters' - category ID 1)
    from dokkan_eza_link_farmer.ai.models import LeaderSkillSpec

    lead_spec = LeaderSkillSpec(main_category_ids=[1], base_boost_pct=200.0)
    leader = DokkanCard(
        id=2000001,
        name="Leader Unit",
        subname="Mighty Leader",
        element=10,
        categories=["Fused Fighters"],
        category_ids=[1],
        leader_skill="Fused Fighters Ki +3, HP, ATK & DEF +200%",
        leader_spec=lead_spec,
        is_tank_override=True,
    )

    # 2. Base card (55% potential)
    base_gogeta = DokkanCard(
        id=1012901,
        name="Super Saiyan Goku & Super Saiyan Vegeta",
        subname="Fused Super Power",
        element=12,
        categories=["Fused Fighters"],
        category_ids=[1],
        potential_percent=55,
        is_rainbow=False,
        is_tank_override=True,
    )

    # 3. Variant card (100% Rainbow potential)
    var_gogeta = DokkanCard(
        id=1034761,
        name="Super Saiyan Goku & Super Saiyan Vegeta",
        subname="Fused Super Power",
        element=12,
        categories=["Fused Fighters"],
        category_ids=[1],
        potential_percent=100,
        is_rainbow=True,
        is_tank_override=True,
    )

    # 4. Fillers to form 6 units
    fillers = [
        DokkanCard(
            id=3000000 + i,
            name=f"Sub Unit {i}",
            subname=f"Title {i}",
            element=11 + (i % 4),
            categories=["Fused Fighters"],
            category_ids=[1],
            potential_percent=100,
            is_rainbow=True,
            is_tank_override=(i < 2),
        )
        for i in range(1, 8)
    ]

    # Candidate pool contains BOTH base and variant
    pool = [leader, base_gogeta, var_gogeta] + fillers

    result = solver.solve(pool, boss_stage=boss, forced_leader=leader)

    team_ids = [c.id for c in result.team_cards]
    team_canon_ids = [c.canonical_identity for c in result.team_cards]

    # Crucial assertion: Team must NOT contain both 1012901 and 1034761
    assert not (1012901 in team_ids and 1034761 in team_ids)
    # Crucial assertion: All canonical identities on the team must be unique
    assert len(team_canon_ids) == len(set(team_canon_ids))

    # Crucial assertion: The higher potential card (variant at 100%) was prioritized over 55% base
    assert 1034761 in team_ids
    assert 1012901 not in team_ids

    # Crucial assertion: The unused base card must NOT be proposed in the shortlist
    shortlist_ids = [ev.card.id for ev in result.shortlist]
    shortlist_canon_ids = [ev.card.canonical_identity for ev in result.shortlist]
    assert 1012901 not in shortlist_ids
    assert 1012901 not in shortlist_canon_ids


# =============================================================================
# 3. SCREEN 3 & HIDDEN POTENTIAL % EVALUATION TESTS
# =============================================================================


def test_detect_current_card_detail_page():
    # Page 1 screen
    s1 = create_mock_screen(page=1)
    assert detect_current_card_detail_page(s1) == 1

    # Page 2 screen
    s2 = create_mock_screen(page=2)
    assert detect_current_card_detail_page(s2) == 2

    # Page 3 screen
    s3 = create_mock_screen(page=3)
    assert detect_current_card_detail_page(s3) == 3


def test_ensure_detail_page_3_navigation():
    # Test starting from Page 1 -> taps arrow right twice to reach Page 3
    fake_adb = FakeADB(initial_page=1)
    screen1 = fake_adb.screencap()
    assert detect_current_card_detail_page(screen1) == 1

    final_screen = ensure_detail_page_3(fake_adb, screen1)
    assert detect_current_card_detail_page(final_screen) == 3
    assert fake_adb.current_page == 3
    assert len(fake_adb.taps) == 2

    # Test when already on Page 3 -> no taps performed
    fake_adb_p3 = FakeADB(initial_page=3)
    screen3 = fake_adb_p3.screencap()
    final_p3 = ensure_detail_page_3(fake_adb_p3, screen3)
    assert detect_current_card_detail_page(final_p3) == 3
    assert len(fake_adb_p3.taps) == 0


def test_extract_potential_and_rainbow_screen_3():
    class MockOCR:
        def __init__(self, detected_text: str):
            self.text = detected_text

        def __call__(self, crop=None):
            _ = crop
            return [([[0, 0], [10, 0], [10, 10], [0, 10]], self.text, 0.99)], None

    screen = np.zeros((2400, 1080, 3), dtype=np.uint8)

    # 1. 100% Rainbow test
    ocr_100 = MockOCR("Activation 100%")
    eval_100 = DetailEvaluator(ocr=ocr_100)
    is_rb, pot = eval_100.extract_potential_and_rainbow(screen)
    assert is_rb is True
    assert pot == 100

    # 2. 55% non-rainbow test
    ocr_55 = MockOCR("Activation 55%")
    eval_55 = DetailEvaluator(ocr=ocr_55)
    is_rb_55, pot_55 = eval_55.extract_potential_and_rainbow(screen)
    assert is_rb_55 is False
    assert pot_55 == 55

    # 3. 69% non-rainbow test
    ocr_69 = MockOCR("Activation 69%")
    eval_69 = DetailEvaluator(ocr=ocr_69)
    is_rb_69, pot_69 = eval_69.extract_potential_and_rainbow(screen)
    assert is_rb_69 is False
    assert pot_69 == 69

    # 4. 79% non-rainbow test
    ocr_79 = MockOCR("Potential 79%")
    eval_79 = DetailEvaluator(ocr=ocr_79)
    is_rb_79, pot_79 = eval_79.extract_potential_and_rainbow(screen)
    assert is_rb_79 is False
    assert pot_79 == 79

    # 5. 90% non-rainbow test
    ocr_90 = MockOCR("Activation 90%")
    eval_90 = DetailEvaluator(ocr=ocr_90)
    is_rb_90, pot_90 = eval_90.extract_potential_and_rainbow(screen)
    assert is_rb_90 is False
    assert pot_90 == 90

    # 6. 0% non-rainbow test
    ocr_0 = MockOCR("Activation 0%")
    eval_0 = DetailEvaluator(ocr=ocr_0)
    is_rb_0, pot_0 = eval_0.extract_potential_and_rainbow(screen)
    assert is_rb_0 is False
    assert pot_0 == 0

    # 7. Noisy OCR snaps to nearest canonical milestone (e.g. 54% -> 55%, 89% -> 90%)
    ocr_noisy_54 = MockOCR("Activation 54%")
    eval_noisy_54 = DetailEvaluator(ocr=ocr_noisy_54)
    is_rb_n54, pot_n54 = eval_noisy_54.extract_potential_and_rainbow(screen)
    assert is_rb_n54 is False
    assert pot_n54 == 55

    ocr_noisy_89 = MockOCR("Activation 89%")
    eval_noisy_89 = DetailEvaluator(ocr=ocr_noisy_89)
    is_rb_n89, pot_n89 = eval_noisy_89.extract_potential_and_rainbow(screen)
    assert is_rb_n89 is False
    assert pot_n89 == 90

    # 8. Fallback OCR text without % sign (e.g. 'Actlvation 79')
    ocr_no_pct = MockOCR("Actlvation 79")
    eval_no_pct = DetailEvaluator(ocr=ocr_no_pct)
    is_rb_np, pot_np = eval_no_pct.extract_potential_and_rainbow(screen)
    assert is_rb_np is False
    assert pot_np == 79


# =============================================================================
# 4. CANONICAL HIDDEN POTENTIAL PERCENTAGES (0, 55, 69, 79, 90, 100) TESTS
# =============================================================================


def test_canonical_potential_percentages_and_snapping():
    from dokkan_eza_link_farmer.ai.card_models import (
        CANONICAL_POTENTIAL_PERCENTAGES,
        snap_potential_percentage,
    )

    # Must strictly match the canonical Dokkan activation tiers
    assert CANONICAL_POTENTIAL_PERCENTAGES == (0, 55, 69, 79, 90, 100)

    # Exact matches
    for step in (0, 55, 69, 79, 90, 100):
        assert snap_potential_percentage(step) == step
        assert snap_potential_percentage(str(step)) == step

    # Snapping noisy / intermediate values
    assert snap_potential_percentage(10) == 0
    assert snap_potential_percentage(27) == 0
    assert snap_potential_percentage(28) == 55
    assert snap_potential_percentage(54) == 55
    assert snap_potential_percentage(56) == 55
    assert snap_potential_percentage(65) == 69
    assert snap_potential_percentage(68) == 69
    assert snap_potential_percentage(70) == 69
    assert snap_potential_percentage(78) == 79
    assert snap_potential_percentage(80) == 79
    assert snap_potential_percentage(88) == 90
    assert snap_potential_percentage(92) == 90
    assert snap_potential_percentage(96) == 100
    assert snap_potential_percentage(99) == 100
    assert snap_potential_percentage(105) == 100
    assert snap_potential_percentage(-10) == 0

    # Invalid / None inputs
    assert snap_potential_percentage(None) == 0
    assert snap_potential_percentage("invalid") == 0


def test_card_model_potential_quantization_and_heuristics():
    # DokkanCard post-init quantizes potential_percent to canonical values
    c1 = DokkanCard(id=1001, name="Test Card", potential_percent=68)
    assert c1.potential_percent == 69
    assert c1.is_rainbow is False

    c2 = DokkanCard(id=1002, name="Rainbow Card", potential_percent=98)
    assert c2.potential_percent == 100
    assert c2.is_rainbow is True

    c3 = DokkanCard(id=1003, name="Free Dupe Card", potential_percent=55)
    assert c3.potential_percent == 55
    assert c3.is_rainbow is False

    # Serialization roundtrip preserves quantized potential
    d = c1.to_dict()
    assert d["potential_percent"] == 69
    restored = DokkanCard.from_dict(d)
    assert restored.potential_percent == 69
    assert restored.is_rainbow is False

    # Heuristic scoring rewards higher potential%
    from dokkan_eza_link_farmer.ai.card_heuristics import evaluate_kit_power

    score_55, b_55 = evaluate_kit_power(c3)
    score_69, b_69 = evaluate_kit_power(c1)
    score_100, b_100 = evaluate_kit_power(c2)
    assert score_100 > score_69 > score_55
    assert b_100.get("rainbow") == 4.0
    assert b_69.get("potential") == 2.76
    assert b_55.get("potential") == 2.2


# =============================================================================
# 5. ADVANCE CHEVRON COORDINATES & TRANSITION ROBUSTNESS TESTS
# =============================================================================


def test_is_right_arrow_visible_detection():
    from dokkan_eza_link_farmer.automation.scanner.swipe_controller import (
        is_right_arrow_visible,
    )

    # 1. Screen with bright white chevron in ROI
    screen_with_arrow = np.zeros((2400, 1080, 3), dtype=np.uint8)
    y1, y2 = int(2400 * (1010 / 2400.0)), int(2400 * (1120 / 2400.0))
    x1, x2 = int(1080 * (980 / 1080.0)), int(1080 * (1060 / 1080.0))
    # Draw white chevron pixels
    screen_with_arrow[y1 + 20 : y2 - 20, x1 + 10 : x2 - 10] = 230
    assert is_right_arrow_visible(screen_with_arrow) is True

    # 2. Blank / dark screen without chevron
    screen_no_arrow = np.zeros((2400, 1080, 3), dtype=np.uint8)
    assert is_right_arrow_visible(screen_no_arrow) is False


def test_advance_to_next_card_polling_and_single_tap():
    from dokkan_eza_link_farmer.automation.scanner.swipe_controller import (
        advance_to_next_card,
    )

    class MockTask:
        def __init__(self):
            self.tap_count = 0
            self.taps = []
            self.w, self.h = 1080, 2400
            self._ocr = None
            outer_self = self

            class ADB:
                def __init__(self_adb):
                    self_adb.parent = outer_self

                def get_screen_size(self_adb):
                    return (outer_self.w, outer_self.h)

                def tap(self_adb, x, y, delay_after=0.0):
                    _ = delay_after
                    outer_self.tap_count += 1
                    outer_self.taps.append((x, y))

                def screencap(self_adb):
                    img = np.zeros((2400, 1080, 3), dtype=np.uint8)
                    # Chevron visible
                    img[1010:1120, 980:1060] = 230
                    if outer_self.tap_count >= 1:
                        # Change art
                        img[600:1400, 200:800] = 200
                    return img

            self.adb = ADB()

        def _extract_banner_text(self, screen_img):
            _ = screen_img
            return "Next Card Subname" if self.tap_count >= 1 else "Current Card Subname"

        def _extract_element_badge(self, screen_img):
            _ = screen_img
            return "SUPER", "AGL"

        def _match_card_candidate(self, text, detected_class=None, detected_elem=None):
            _ = (text, detected_class, detected_elem)
            if self.tap_count >= 1:
                return {"id": 1034201, "name": "Super Saiyan 3 Goku"}, 0.95
            return {"id": 1020281, "name": "Tien"}, 0.95

    task = MockTask()
    initial_screen = np.zeros((2400, 1080, 3), dtype=np.uint8)
    initial_screen[1010:1120, 980:1060] = 230  # chevron visible

    next_screen, advanced = advance_to_next_card(task, initial_screen, current_card_id=1020281)
    assert advanced is True
    # Crucial: Must perform only 1 single tap without double-tapping or skipping
    assert task.tap_count == 1
    # Crucial: Chevron tap coordinate must be centered at x=1015, y=1065
    tap_x, tap_y = task.taps[0]
    assert abs(tap_x - 1015) <= 2
    assert abs(tap_y - 1065) <= 2


def test_base_and_art_variant_sequential_matching_not_marked_as_dupe():
    """Validates that a base card (e.g. 1012931) and art variant (1034741) appearing sequentially

    are both correctly identified as their distinct card IDs and never falsely collapsed as a dupe.
    """
    from dokkan_eza_link_farmer.automation.scanner.catalog_matcher import (
        CatalogMatcher,
    )

    catalog = [
        {
            "id": 1012931,
            "name": "Super Saiyan Goku (Angel) & Super Saiyan Vegeta (Angel)",
            "subname": "Fused Fighting Force",
            "element": 14,  # PHY
            "rarity": 5,
            "tag": 1,
        },
        {
            "id": 1034741,
            "name": "Super Saiyan Goku (Angel) & Super Saiyan Vegeta (Angel)",
            "subname": "Fused Fighting Force",
            "element": 14,  # PHY
            "rarity": 5,
            "tag": 11,  # Art Variant
        },
    ]

    matcher = CatalogMatcher(catalog)
    text = "Fused Fighting Force Super Saiyan Goku (Angel) & Super Saiyan Vegeta (Angel)"

    # Card 1: Scanning Base Card
    seen_ids: set[int] = set()
    cand1, score1 = matcher.match_card_candidate(
        text,
        detected_class="SUPER",
        detected_elem="PHY",
        detected_rarity=5,
        session_seen_ids=seen_ids,
        last_registered_card_id=None,
    )
    assert cand1 is not None
    # Must pick the base canonical card first
    assert cand1["id"] == 1012931
    assert score1 >= 0.90

    # Register Card 1 in seen set
    seen_ids.add(1012931)
    last_registered_id = 1012931

    # Card 2: Scanning Art Variant Card
    cand2, score2 = matcher.match_card_candidate(
        text,
        detected_class="SUPER",
        detected_elem="PHY",
        detected_rarity=5,
        session_seen_ids=seen_ids,
        last_registered_card_id=last_registered_id,
    )
    assert cand2 is not None
    # Crucial: Must pick the unseen art variant (1034741) and NOT repeat 1012931 as a duplicate
    assert cand2["id"] == 1034741
    assert cand2["id"] != last_registered_id
    assert score2 >= 0.90


def test_exact_card_not_preempted_by_unrelated_partial_match():
    from dokkan_eza_link_farmer.automation.scanner.catalog_matcher import CatalogMatcher

    catalog = [
        {
            "id": 1024871,
            "name": "Super Saiyan Goku & Super Saiyan Vegeta",
            "subname": "Super Saiyan Duo",
            "element": 10,  # AGL
            "rarity": 4,
            "tag": 1,
        },
        {
            "id": 1034031,
            "name": "Super Saiyan Goku",
            "subname": "Furious Fighter's Immense Power",
            "element": 10,  # AGL
            "rarity": 5,
            "tag": 2,
        },
    ]

    matcher = CatalogMatcher(catalog)
    text = "Furious Fighter's Immense Power Super Saiyan Goku"

    cand, score = matcher.match_card_candidate(
        text,
        detected_class="SUPER",
        detected_elem="AGL",
        detected_rarity=None,
    )
    assert cand is not None
    # Crucial: Must match 1034031 and NOT 1024871 despite lower card ID of 1024871
    assert cand["id"] == 1034031
    assert cand["name"] == "Super Saiyan Goku"
    assert score >= 0.98


def test_candidate_tie_resolution_orders_by_release_date_descending():
    from dokkan_eza_link_farmer.automation.scanner.catalog_matcher import CatalogMatcher

    # Two distinct cards with same title and name released at different dates
    catalog = [
        {
            "id": 1000010,
            "name": "Super Saiyan Goku",
            "subname": "Legendary Super Saiyan",
            "element": 10,  # AGL
            "rarity": 4,
            "tag": 1,
            "open_at": "2018-05-01T00:00:00",
        },
        {
            "id": 2000020,
            "name": "Super Saiyan Goku",
            "subname": "Legendary Super Saiyan",
            "element": 10,  # AGL
            "rarity": 4,
            "tag": 1,
            "open_at": "2024-09-01T00:00:00",
        },
    ]

    matcher = CatalogMatcher(catalog)
    text = "Legendary Super Saiyan Super Saiyan Goku"

    # In a box sorted by Release Date (newest first), the newer card must win ties
    cand, score = matcher.match_card_candidate(
        text,
        detected_class="SUPER",
        detected_elem="AGL",
        detected_rarity=4,
    )
    assert cand is not None
    assert cand["id"] == 2000020
    assert score >= 0.98
