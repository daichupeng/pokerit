from ai_functions.preflop_ranges import RANGE_PACKS, normalize_starting_hand


def test_exactly_four_versioned_packs_are_exposed():
    assert set(RANGE_PACKS) == {
        "mtt_bba_6max_40bb_v1",
        "mtt_bba_8max_40bb_v1",
        "cash_6max_100bb_v1",
        "cash_8max_100bb_v1",
    }
    assert all(pack.version == "1.0.0" for pack in RANGE_PACKS.values())
    assert all(pack.source_url.startswith("https://rangeconverter.com/") for pack in RANGE_PACKS.values())
    assert all(len(pack.source_sha256) == 64 for pack in RANGE_PACKS.values())


def test_pack_decisions_preserve_pure_mixed_and_derived_boundaries():
    mtt8 = RANGE_PACKS["mtt_bba_8max_40bb_v1"]
    assert mtt8.decision("UTG", "A4s").actions == ("raise",)
    assert mtt8.decision("UTG", "A2s").actions == ("fold",)
    assert set(mtt8.decision("UTG", "44").actions) == {"raise", "fold"}

    # 6-max UTG maps to the source's MP node by players behind.
    mtt6 = RANGE_PACKS["mtt_bba_6max_40bb_v1"]
    assert mtt6.decision("UTG", "A2s").actions == ("raise",)
    assert mtt6.derivation is not None

    cash6 = RANGE_PACKS["cash_6max_100bb_v1"]
    assert cash6.decision("UTG", "A2s").actions == ("fold",)
    assert set(cash6.decision("SB", "AA").actions) == {"raise", "limp"}

    cash8 = RANGE_PACKS["cash_8max_100bb_v1"]
    assert set(cash8.decision("UTG", "AJo").actions) == {"raise", "fold"}


def test_card_codes_normalize_to_a_169_grid_class():
    assert normalize_starting_hand("As Kh") == "AKo"
    assert normalize_starting_hand("7d7c") == "77"
    assert normalize_starting_hand("Qh5h") == "Q5s"
    assert normalize_starting_hand("AsAs") is None
