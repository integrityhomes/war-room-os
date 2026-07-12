import pandas as pd

from lead_intelligence import score_dataframe, score_raw_lead, select_contact, signal


def test_zero_value_signal_does_not_score_as_true():
    row = {"PreForeclosure": "0", "Vacancy": "0", "FreeAndClear": "1"}
    assert signal(row, "PreForeclosure") is False
    assert signal(row, "Vacancy") is False
    assert signal(row, "FreeAndClear") is True


def test_selects_explicitly_clear_phone_over_dnc_phone():
    row = {
        "Contact1Phone_1": "540-111-1111",
        "Contact1Phone_1_DNC": "true",
        "Contact1Phone_1_Litigator": "false",
        "Contact1Phone_2": "540-222-2222",
        "Contact1Phone_2_DNC": "false",
        "Contact1Phone_2_Litigator": "false",
    }
    contact = select_contact(row)
    assert contact["selected_phone"] == "5402222222"
    assert contact["contact_compliance_status"] == "CLEAR"
    assert contact["has_mixed_phone_compliance"] is True


def test_all_dnc_phones_create_compliance_hold():
    row = {
        "PropertyAddress": "1 Main St",
        "PropertyState": "VA",
        "Contact1Phone_1": "5401111111",
        "Contact1Phone_1_DNC": "true",
        "Contact1Phone_1_Litigator": "false",
        "FreeAndClear": "1",
    }
    result = score_raw_lead(row, ["VA"])
    assert result["lead_status"] == "Compliance Hold — All Phones Blocked"
    assert result["xleads_action"] == "DO_NOT_CONTACT"


def test_unknown_dnc_is_review_not_campaign_ready():
    row = {
        "PropertyAddress": "1 Main St",
        "PropertyState": "VA",
        "Contact1Phone_1": "5401111111",
        "Contact1Phone_1_DNC": "",
        "Vacancy": "1",
        "Foreclosures": "1",
    }
    result = score_raw_lead(row, ["VA"])
    assert result["lead_status"] == "Compliance Review — DNC Unknown"
    assert "DNC_STATUS_UNKNOWN" in result["risk_flags"]


def test_dataframe_uses_selected_safe_phone():
    df = pd.DataFrame([{
        "PropertyAddress": "1 Main St",
        "PropertyState": "VA",
        "property_address": "1 Main St, Richmond, VA",
        "property_state": "VA",
        "Contact1Phone_1": "5401111111",
        "Contact1Phone_1_DNC": "true",
        "Contact1Phone_2": "5402222222",
        "Contact1Phone_2_DNC": "false",
        "Vacancy": "1",
        "Foreclosures": "0",
    }])
    scored = score_dataframe(df, "Raw XLeads Property List", ["VA"])
    assert scored.iloc[0]["phone"] == "5402222222"
    assert "foreclosure record" not in scored.iloc[0]["motivation"]
