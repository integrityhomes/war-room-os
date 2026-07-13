from io import BytesIO
from zipfile import ZipFile

import pandas as pd

from xleads_import_automation import (
    build_report,
    clean_phone,
    prepare_sync_dataframe,
    read_xleads_upload,
)


def sample_frame() -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "FirstName": "James",
                "LastName": "Gilbert",
                "RecipientAddress": "312 Chaney Ln",
                "RecipientCity": "Gretna",
                "RecipientState": "VA",
                "RecipientPostalCode": "24557",
                "PropertyAddress": "312 Chaney Ln",
                "PropertyCity": "Gretna",
                "PropertyState": "VA",
                "PropertyPostalCode": "24557",
                "Contact1Phone_1": 7579678360.0,
                "Contact1Phone_1_DNC": "False",
                "Contact1Phone_1_Litigator": "False",
                "Contact1Email_1": "owner@example.com",
            },
            {
                "FirstName": "Fallback",
                "LastName": "Owner",
                "PropertyAddress": "4 Main St",
                "PropertyCity": "Richmond",
                "PropertyState": "VA",
                "PropertyPostalCode": "23219",
                "Contact1Phone_1": 8045551111.0,
                "Contact1Phone_1_DNC": "True",
                "Contact1Phone_1_Litigator": "False",
                "Contact1Phone_2": 8045552222.0,
                "Contact1Phone_2_DNC": "False",
                "Contact1Phone_2_Litigator": "False",
            },
            {
                "FirstName": "Unknown",
                "LastName": "Screen",
                "PropertyAddress": "5 Main St",
                "PropertyCity": "Richmond",
                "PropertyState": "VA",
                "PropertyPostalCode": "23219",
                "Contact1Phone_1": 8045553333.0,
            },
            {
                "FirstName": "Dnc",
                "LastName": "Owner",
                "PropertyAddress": "3 Main St",
                "PropertyCity": "Richmond",
                "PropertyState": "VA",
                "PropertyPostalCode": "23219",
                "Contact1Phone_1": 8045553434.0,
                "Contact1Phone_1_DNC": "True",
                "Contact1Phone_1_Litigator": "False",
            },
            {
                "FirstName": "Multi",
                "LastName": "Owner",
                "PropertyAddress": "1 Main St",
                "PropertyCity": "Richmond",
                "PropertyState": "VA",
                "PropertyPostalCode": "23219",
                "Contact1Phone_1": 8045551212.0,
                "Contact1Phone_1_DNC": "False",
                "Contact1Phone_1_Litigator": "False",
            },
            {
                "FirstName": "Multi",
                "LastName": "Owner",
                "PropertyAddress": "2 Main St",
                "PropertyCity": "Richmond",
                "PropertyState": "VA",
                "PropertyPostalCode": "23219",
                "Contact1Phone_1": 8045551212.0,
                "Contact1Phone_1_DNC": "False",
                "Contact1Phone_1_Litigator": "False",
            },
        ]
    )


def test_float_phone_is_normalized():
    assert clean_phone(2174810610.0) == "2174810610"
    assert clean_phone("2174810610.0") == "2174810610"


def test_property_and_mailing_addresses_remain_separate():
    queue = prepare_sync_dataframe(sample_frame(), "Virginia July")
    james = queue.iloc[0]
    assert james["property_address"] == "312 Chaney Ln, Gretna, VA, 24557"
    assert james["mailing_address"] == "312 Chaney Ln, Gretna, VA, 24557"
    assert james["phone"] == "7579678360"
    assert james["safe_to_sync"]


def test_phone_two_can_replace_dnc_phone_one():
    queue = prepare_sync_dataframe(sample_frame(), "Virginia July")
    fallback = queue[queue["seller_name"] == "Fallback Owner"].iloc[0]
    assert fallback["phone"] == "8045552222"
    assert fallback["sync_action"] == "READY_TO_SYNC"


def test_blank_screening_goes_to_review():
    queue = prepare_sync_dataframe(sample_frame(), "Virginia July")
    unknown = queue[queue["seller_name"] == "Unknown Screen"].iloc[0]
    assert unknown["sync_action"] == "SCREENING_REVIEW"
    assert not unknown["safe_to_sync"]


def test_dnc_row_is_held():
    queue = prepare_sync_dataframe(sample_frame(), "Virginia July")
    dnc = queue[queue["seller_name"] == "Dnc Owner"].iloc[0]
    assert dnc["sync_action"] == "DNC_HOLD"
    assert not dnc["safe_to_sync"]


def test_multi_property_owner_is_held():
    queue = prepare_sync_dataframe(sample_frame(), "Virginia July")
    multi = queue[queue["seller_name"] == "Multi Owner"]
    assert set(multi["sync_action"]) == {"MULTI_PROPERTY_REVIEW"}
    assert not multi["safe_to_sync"].any()


def test_report_counts_lanes():
    report = build_report(prepare_sync_dataframe(sample_frame(), "Virginia July"))
    assert report["total_rows"] == 6
    assert report["ready_to_sync"] == 2
    assert report["dnc_holds"] == 1
    assert report["screening_review"] == 1
    assert report["multi_property_review"] == 2


def test_zip_upload_uses_csv_inside_archive():
    csv_bytes = sample_frame().to_csv(index=False).encode("utf-8")
    buffer = BytesIO()
    with ZipFile(buffer, "w") as archive:
        archive.writestr("nested/xleads.csv", csv_bytes)
    frame, filename = read_xleads_upload("export.zip", buffer.getvalue())
    assert filename == "nested/xleads.csv"
    assert len(frame) == 6
