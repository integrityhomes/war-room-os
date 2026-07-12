import pandas as pd

from lead_intelligence import detect_opt_out, run_greatness_test, score_dataframe, score_reply_lead


def test_greatness_suite_passes():
    results = run_greatness_test()
    failures = results.loc[~results["passed"]]
    assert failures.empty, failures.to_dict(orient="records")


def test_stop_by_is_not_opt_out():
    assert not detect_opt_out("Stop by tomorrow to see it")


def test_dnc_overrides_positive_language():
    result = score_reply_lead({"seller_message": "I might sell but stop texting me"})
    assert result["call_lane"] == "Do Not Contact"
    assert result["lead_score"] == 0


def test_high_price_does_not_kill_opportunity():
    result = score_reply_lead({"seller_message": "I need $250,000 firm. Zillow says $260,000"})
    assert result["call_lane"] == "Call Today"
    assert result["price_expectation_review"] is True


def test_duplicate_suppression_keeps_best_record():
    df = pd.DataFrame([
        {"seller_message": "Maybe", "phone": "555-111-2222", "property_address": "1 Main St"},
        {"seller_message": "Call me now, inherited and vacant", "phone": "5551112222", "property_address": "1 Main St"},
    ])
    scored = score_dataframe(df, "Seller Replies")
    assert scored["duplicate_flag"].all()
    assert scored["duplicate_primary"].sum() == 1
    primary = scored.loc[scored["duplicate_primary"]].iloc[0]
    assert primary["call_lane"] == "Call Now"
