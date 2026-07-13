from io import BytesIO
from zipfile import ZipFile

import pandas as pd

from xleads_campaign_control import (
    analyze_returned_export,
    build_report,
    campaign_export,
    clean_phone,
    email_export,
    phone_export,
    prepare_skiptrace_upload,
    read_xleads_upload,
)


def sample_frame() -> pd.DataFrame:
    return pd.DataFrame([
        {
            "FirstName": "Phone",
            "LastName": "Email",
            "PropertyAddress": "1 Main St",
            "PropertyCity": "Richmond",
            "PropertyState": "VA",
            "PropertyPostalCode": "23219",
            "Contact1Phone_1": 8045551111.0,
            "Contact1Phone_1_DNC": "False",
            "Contact1Phone_1_Litigator": "False",
            "Contact1Email_1": "both@example.com",
        },
        {
            "FirstName": "Email",
            "LastName": "Only",
            "PropertyAddress": "2 Main St",
            "PropertyCity": "Richmond",
            "PropertyState": "VA",
            "PropertyPostalCode": "23219",
            "Contact1Phone_1": 8045552222.0,
            "Contact1Phone_1_DNC": "True",
            "Contact1Phone_1_Litigator": "False",
            "Contact1Email_1": "emailonly@example.com",
        },
        {
            "FirstName": "Fallback",
            "LastName": "Phone",
            "PropertyAddress": "3 Main St",
            "PropertyCity": "Richmond",
            "PropertyState": "VA",
            "PropertyPostalCode": "23219",
            "Contact1Phone_1": 8045553333.0,
            "Contact1Phone_1_DNC": "True",
            "Contact1Phone_1_Litigator": "False",
            "Contact1Phone_2": 8045554444.0,
            "Contact1Phone_2_DNC": "False",
            "Contact1Phone_2_Litigator": "False",
        },
        {
            "FirstName": "Unknown",
            "LastName": "Screen",
            "PropertyAddress": "4 Main St",
            "PropertyCity": "Richmond",
            "PropertyState": "VA",
            "PropertyPostalCode": "23219",
            "Contact1Phone_1": 8045555555.0,
        },
        {
            "FirstName": "Email",
            "LastName": "Optout",
            "PropertyAddress": "5 Main St",
            "PropertyCity": "Richmond",
            "PropertyState": "VA",
            "PropertyPostalCode": "23219",
            "Contact1Email_1": "blocked@example.com",
            "Email_Opt_Out": "True",
        },
    ])


def test_float_phone_is_normalized():
    assert clean_phone(2174810610.0) == "2174810610"
    assert clean_phone("2174810610.0") == "2174810610"


def test_phone_and_email_lanes_are_independent():
    queue = analyze_returned_export(sample_frame(), "Virginia July")
    both = queue[queue["seller_name"] == "Phone Email"].iloc[0]
    email_only = queue[queue["seller_name"] == "Email Only"].iloc[0]
    assert both["phone_ready"] and both["email_ready"]
    assert email_only["phone_action"] == "DNC_PHONE_HOLD"
    assert email_only["email_ready"]
    assert email_only["campaign_action"] == "READY_EMAIL_ONLY"


def test_later_clear_phone_is_selected():
    queue = analyze_returned_export(sample_frame())
    fallback = queue[queue["seller_name"] == "Fallback Phone"].iloc[0]
    assert fallback["phone"] == "8045554444"
    assert fallback["phone_ready"]


def test_blank_phone_screening_goes_to_review():
    queue = analyze_returned_export(sample_frame())
    unknown = queue[queue["seller_name"] == "Unknown Screen"].iloc[0]
    assert unknown["phone_action"] == "SCREENING_REVIEW"
    assert not unknown["campaign_ready"]


def test_email_optout_is_held():
    queue = analyze_returned_export(sample_frame())
    row = queue[queue["seller_name"] == "Email Optout"].iloc[0]
    assert row["email_action"] == "EMAIL_SUPPRESSION_HOLD"
    assert not row["email_ready"]


def test_exports_and_report():
    queue = analyze_returned_export(sample_frame())
    report = build_report(queue)
    assert report["total"] == 5
    assert report["phone_ready"] == 2
    assert report["email_ready"] == 2
    assert report["email_only"] == 1
    assert len(campaign_export(queue)) == 3
    assert len(phone_export(queue)) == 2
    assert len(email_export(queue)) == 2


def test_prepare_raw_skiptrace_upload():
    raw = pd.DataFrame([{
        "FirstName": "Raw",
        "LastName": "Owner",
        "PropertyAddress": "10 Main St",
        "PropertyCity": "Norfolk",
        "PropertyState": "VA",
        "PropertyPostalCode": "23510",
    }])
    prepared = prepare_skiptrace_upload(raw)
    assert prepared.iloc[0]["property_address"] == "10 Main St, Norfolk, VA, 23510"


def test_zip_upload_uses_csv_inside_archive():
    csv_bytes = sample_frame().to_csv(index=False).encode("utf-8")
    buffer = BytesIO()
    with ZipFile(buffer, "w") as archive:
        archive.writestr("nested/xleads.csv", csv_bytes)
    frame, filename = read_xleads_upload("export.zip", buffer.getvalue())
    assert filename == "nested/xleads.csv"
    assert len(frame) == 5
