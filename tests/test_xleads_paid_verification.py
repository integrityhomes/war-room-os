import pandas as pd

from xleads_paid_verification import verify_paid_leadtrace


def test_phone_and_email_without_screening_are_not_verified():
    frame = pd.DataFrame(
        [
            {
                "Contact1Phone_1": "2175551212",
                "Contact1Email_1": "owner@example.com",
            }
        ]
    )
    result = verify_paid_leadtrace(frame)
    assert not result.verified
    assert result.paired_phone_groups == 0
    assert result.screened_rows == 0


def test_blank_dnc_and_litigator_results_are_not_verified():
    frame = pd.DataFrame(
        [
            {
                "Contact1Phone_1": "2175551212",
                "Contact1Phone_1_DNC": "",
                "Contact1Phone_1_Litigator": "",
            }
        ]
    )
    result = verify_paid_leadtrace(frame)
    assert not result.verified
    assert result.paired_phone_groups == 1
    assert result.screened_rows == 0


def test_populated_phone_dnc_and_litigator_are_verified():
    frame = pd.DataFrame(
        [
            {
                "Contact1Phone_1": 2175551212.0,
                "Contact1Phone_1_DNC": "False",
                "Contact1Phone_1_Litigator": "False",
            }
        ]
    )
    result = verify_paid_leadtrace(frame)
    assert result.verified
    assert result.paired_phone_groups == 1
    assert result.screened_rows == 1


def test_only_completed_screening_rows_are_counted():
    frame = pd.DataFrame(
        [
            {
                "Contact1Phone_1": "2175551212",
                "Contact1Phone_1_DNC": "False",
                "Contact1Phone_1_Litigator": "False",
            },
            {
                "Contact1Phone_1": "2175553434",
                "Contact1Phone_1_DNC": "",
                "Contact1Phone_1_Litigator": "",
            },
            {
                "Contact1Phone_1": "",
                "Contact1Phone_1_DNC": "False",
                "Contact1Phone_1_Litigator": "False",
            },
        ]
    )
    result = verify_paid_leadtrace(frame)
    assert result.verified
    assert result.paired_phone_groups == 1
    assert result.screened_rows == 1
