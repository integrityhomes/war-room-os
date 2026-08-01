import pandas as pd

from xleads_email_campaign import cannot_call_email_export, dnc_email_campaign_export


def sample_queue() -> pd.DataFrame:
    return pd.DataFrame([
        {
            "audit_id": "one",
            "first_name": "Call",
            "last_name": "Ready",
            "email": "call@example.com",
            "email_2": "",
            "email_3": "",
            "email_ready": True,
            "phone_ready": True,
            "phone_action": "READY_FOR_XLEADS_PHONE",
            "email_action": "READY_FOR_XLEADS_EMAIL",
            "property_street": "1 Main St",
            "property_city": "Richmond",
            "property_state": "VA",
            "property_zip": "23219",
            "mailing_street": "1 Main St",
            "mailing_city": "Richmond",
            "mailing_state": "VA",
            "mailing_zip": "23219",
            "xleads_tags": "war-room-processed",
        },
        {
            "audit_id": "two",
            "first_name": "Dnc",
            "last_name": "Email",
            "email": "dnc@example.com",
            "email_2": "second@example.com",
            "email_3": "",
            "email_ready": True,
            "phone_ready": False,
            "phone_action": "DNC_PHONE_HOLD",
            "email_action": "READY_FOR_XLEADS_EMAIL",
            "property_street": "2 Main St",
            "property_city": "Norfolk",
            "property_state": "VA",
            "property_zip": "23510",
            "mailing_street": "PO Box 2",
            "mailing_city": "Norfolk",
            "mailing_state": "VA",
            "mailing_zip": "23501",
            "xleads_tags": "war-room-processed,phone-dnc-hold",
        },
        {
            "audit_id": "three",
            "first_name": "Unknown",
            "last_name": "Phone",
            "email": "unknown@example.com",
            "email_2": "",
            "email_3": "",
            "email_ready": True,
            "phone_ready": False,
            "phone_action": "SCREENING_REVIEW",
            "email_action": "READY_FOR_XLEADS_EMAIL",
            "property_street": "3 Main St",
            "property_city": "Roanoke",
            "property_state": "VA",
            "property_zip": "24011",
            "mailing_street": "3 Main St",
            "mailing_city": "Roanoke",
            "mailing_state": "VA",
            "mailing_zip": "24011",
            "xleads_tags": "war-room-processed,phone-screening-review",
        },
        {
            "audit_id": "four",
            "first_name": "Suppressed",
            "last_name": "Email",
            "email": "",
            "email_2": "",
            "email_3": "",
            "email_ready": False,
            "phone_ready": False,
            "phone_action": "DNC_PHONE_HOLD",
            "email_action": "EMAIL_SUPPRESSION_HOLD",
            "property_street": "4 Main St",
            "property_city": "Roanoke",
            "property_state": "VA",
            "property_zip": "24011",
            "mailing_street": "4 Main St",
            "mailing_city": "Roanoke",
            "mailing_state": "VA",
            "mailing_zip": "24011",
            "xleads_tags": "war-room-processed,phone-dnc-hold",
        },
    ])


def test_cannot_call_excludes_call_ready_and_expands_emails():
    output = cannot_call_email_export(sample_queue())
    assert set(output["Email"]) == {"dnc@example.com", "second@example.com", "unknown@example.com"}
    assert "call@example.com" not in set(output["Email"])
    assert "Phone" not in output.columns


def test_dnc_campaign_only_contains_explicit_dnc_hold():
    output = dnc_email_campaign_export(sample_queue())
    assert set(output["Email"]) == {"dnc@example.com", "second@example.com"}
    assert set(output["PhoneCampaignStatus"]) == {"DNC_PHONE_HOLD"}
    assert output["Tags"].str.contains("dnc-email-campaign-ready").all()


def test_suppressed_email_is_not_exported():
    output = dnc_email_campaign_export(sample_queue())
    assert "suppressed@example.com" not in set(output["Email"])
