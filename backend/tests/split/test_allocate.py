from app.services.split_engine.allocate import largest_remainder


def test_ties_go_to_priority_then_lowest_id() -> None:
    weights = [("chen", 1), ("ben", 1), ("aditi", 1)]
    assert largest_remainder(200, weights, priority_id="chen") == {
        "chen": 67,
        "aditi": 67,
        "ben": 66,
    }
    assert largest_remainder(200, weights) == {"aditi": 67, "ben": 67, "chen": 66}


def test_priority_never_beats_a_bigger_remainder() -> None:
    # 3:7 of 1001 -> exact 300.3 and 700.7. Ben's .7 wins even though Aditi has priority.
    assert largest_remainder(1001, [("aditi", 3), ("ben", 7)], priority_id="aditi") == {
        "aditi": 300,
        "ben": 701,
    }


def test_zero_weight_never_receives_a_leftover_unit() -> None:
    assert largest_remainder(1, [("aditi", 0), ("ben", 1), ("chen", 1)], priority_id="aditi") == {
        "aditi": 0,
        "ben": 1,
        "chen": 0,
    }


def test_ids_compare_bytewise() -> None:
    # "0..." < "9..." < "a..." in byte order.
    w = [("a1", 1), ("91", 1), ("01", 1)]
    assert largest_remainder(1, w) == {"01": 1, "91": 0, "a1": 0}
