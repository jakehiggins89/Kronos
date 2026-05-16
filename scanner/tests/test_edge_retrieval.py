from scanner.edge.retrieval import EdgeRecord, find_analogs


def test_find_analogs_ranks_nearest_numeric_features():
    query = {
        "ticker": "AAA",
        "timestamp": "2026-02-01T00:00:00-05:00",
        "breakout_distance_pct": 2.0,
        "volume_expansion": 1.5,
        "rr_ratio": 2.0,
    }
    near = EdgeRecord(
        ticker="BBB",
        timestamp="2026-01-01T00:00:00-05:00",
        direction="bullish",
        features={"breakout_distance_pct": 2.1, "volume_expansion": 1.45, "rr_ratio": 2.1},
        outcome_return_pct=3.0,
        outcome_label="win",
        r_multiple=1.5,
        mae_pct=-1.0,
        mfe_pct=4.0,
    )
    far = EdgeRecord(
        ticker="CCC",
        timestamp="2026-01-01T00:00:00-05:00",
        direction="bullish",
        features={"breakout_distance_pct": 9.0, "volume_expansion": 0.3, "rr_ratio": 0.4},
        outcome_return_pct=-2.0,
        outcome_label="loss",
        r_multiple=-1.0,
        mae_pct=-3.0,
        mfe_pct=1.0,
    )

    analogs = find_analogs(query, [far, near], k=2)

    assert [a["ticker"] for a in analogs] == ["BBB", "CCC"]
    assert analogs[0]["distance"] < analogs[1]["distance"]


def test_find_analogs_excludes_same_ticker_inside_embargo():
    query = {
        "ticker": "AAA",
        "timestamp": "2026-02-10T00:00:00-05:00",
        "breakout_distance_pct": 2.0,
        "volume_expansion": 1.5,
    }
    leaked = EdgeRecord(
        ticker="AAA",
        timestamp="2026-02-08T00:00:00-05:00",
        direction="bullish",
        features={"breakout_distance_pct": 2.0, "volume_expansion": 1.5},
        outcome_return_pct=5.0,
        outcome_label="win",
        r_multiple=2.0,
        mae_pct=-0.5,
        mfe_pct=5.5,
    )
    allowed = EdgeRecord(
        ticker="AAA",
        timestamp="2026-01-01T00:00:00-05:00",
        direction="bullish",
        features={"breakout_distance_pct": 2.2, "volume_expansion": 1.4},
        outcome_return_pct=1.0,
        outcome_label="win",
        r_multiple=0.5,
        mae_pct=-1.0,
        mfe_pct=2.0,
    )

    analogs = find_analogs(query, [leaked, allowed], k=5, embargo_days=5)

    assert [a["timestamp"] for a in analogs] == ["2026-01-01T00:00:00-05:00"]
