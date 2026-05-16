from scanner.learning.autotuner import propose_overrides


def test_autotune_holds_when_missed_winners_equal_correct_skips():
    records = []
    for i in range(28):
        records.append(
            {
                "ticker": f"W{i}",
                "final_pass": False,
                "stage_failed": "potter_box",
                "outcome_status": "resolved",
                "outcome_label": "win",
            }
        )
        records.append(
            {
                "ticker": f"L{i}",
                "final_pass": False,
                "stage_failed": "potter_box",
                "outcome_status": "resolved",
                "outcome_label": "loss",
            }
        )

    proposal = propose_overrides(records)
    assert proposal["status"] == "hold_no_edge"
    assert proposal["overrides"] == {}


def test_autotune_can_loosen_when_missed_win_rate_has_edge():
    records = []
    for i in range(40):
        records.append(
            {
                "ticker": f"W{i}",
                "final_pass": False,
                "stage_failed": "potter_box",
                "outcome_status": "resolved",
                "outcome_label": "win",
            }
        )
    for i in range(10):
        records.append(
            {
                "ticker": f"L{i}",
                "final_pass": False,
                "stage_failed": "potter_box",
                "outcome_status": "resolved",
                "outcome_label": "loss",
            }
        )

    proposal = propose_overrides(records)
    assert proposal["status"] == "ok"
    assert proposal["missed_win_rate"] == 0.8
    assert proposal["overrides"]["ATR_COMPRESSION"] > 0.75
