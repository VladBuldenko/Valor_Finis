from datetime import date
from decimal import Decimal
from typing import Optional

import pytest

from app.modules.receipts import receipt_parser_service



# Verifies that raw OCR text is converted into structured receipt data.
# This test exists to confirm the complete parser flow for a German receipt.
# Parameters:
# - None.
# Returns:
# - None.
def test_parse_receipt_text_returns_detected_receipt_data() -> None:
    ocr_text = """
        LIDL
        München
        31.07.2026

        Milch       1,49
        Brot        2,19

        SUMME       3,68 EUR
    """

    result = receipt_parser_service.parse_receipt_text(
        ocr_text=ocr_text,
    )

    assert result.merchant_detected == "LIDL"
    assert result.total_amount_detected == Decimal("3.68")
    assert result.currency_detected == "EUR"
    assert result.purchase_date_detected == date(2026, 7, 31)


# Verifies that empty OCR text produces an empty parser result.
# This test exists to keep missing detections explicit
# without raising parser errors.
# Parameters:
# - ocr_text: empty or whitespace-only OCR text.
# Returns:
# - None.
@pytest.mark.parametrize(
    "ocr_text",
    [
        "",
        "   ",
        "\n\t\n",
    ],
)
def test_parse_receipt_text_returns_empty_data_for_empty_text(
    ocr_text: str,
) -> None:
    result = receipt_parser_service.parse_receipt_text(
        ocr_text=ocr_text,
    )

    assert result == receipt_parser_service.ParsedReceiptData()


# Verifies that receipt lines are stripped and internal whitespace is normalized.
# This test exists to prepare inconsistent OCR output for parser operations.
# Parameters:
# - None.
# Returns:
# - None.
def test_normalize_receipt_lines_removes_empty_lines_and_extra_spaces() -> None:
    ocr_text = """
          LIDL

        Milch          1,49
        SUMME     1,49 EUR
    """

    result = receipt_parser_service.normalize_receipt_lines(
        ocr_text=ocr_text,
    )

    assert result == [
        "LIDL",
        "Milch 1,49",
        "SUMME 1,49 EUR",
    ]


# Verifies that common receipt metadata is not selected as the merchant.
# This test exists to detect the first meaningful textual receipt line.
# Parameters:
# - None.
# Returns:
# - None.
def test_detect_merchant_skips_receipt_metadata() -> None:
    lines = [
        "BON 12345",
        "FILIALE 17",
        "31.07.2026 14:30",
        "REWE CITY",
        "SUMME 24,99 EUR",
    ]

    result = receipt_parser_service.detect_merchant(
        lines=lines,
    )

    assert result == "REWE CITY"


# Verifies that merchant detection returns None without a suitable line.
# This test exists to avoid returning numbers or total lines as merchant names.
# Parameters:
# - None.
# Returns:
# - None.
def test_detect_merchant_returns_none_without_meaningful_line() -> None:
    lines = [
        "123456",
        "31.07.2026",
        "SUMME 24,99 EUR",
    ]

    result = receipt_parser_service.detect_merchant(
        lines=lines,
    )

    assert result is None


# Verifies detection of common European and international amount formats.
# This test exists to support German comma decimals,
# dot decimals, and thousands separators.
# Parameters:
# - total_line: receipt line containing a total amount.
# - expected_amount: normalized Decimal value.
# Returns:
# - None.
@pytest.mark.parametrize(
    ("total_line", "expected_amount"),
    [
        ("SUMME 24,99 EUR", Decimal("24.99")),
        ("TOTAL 24.99 USD", Decimal("24.99")),
        ("GESAMTBETRAG 1.234,56 EUR", Decimal("1234.56")),
        ("TOTAL 1,234.56 USD", Decimal("1234.56")),
        ("ZU ZAHLEN EUR 7,40", Decimal("7.40")),
        ("ENDSUMME CHF 12.50", Decimal("12.50")),
    ],
)
def test_detect_total_amount_supports_common_formats(
    total_line: str,
    expected_amount: Decimal,
) -> None:
    amount, source_line = receipt_parser_service.detect_total_amount(
        lines=[
            "Milch 1,49",
            total_line,
        ],
    )

    assert amount == expected_amount
    assert source_line == total_line


# Verifies that the last amount on a total line is selected.
# This test exists because receipt total lines can also contain
# net and tax amounts before the final gross amount.
# Parameters:
# - None.
# Returns:
# - None.
def test_detect_total_amount_uses_last_amount_from_total_line() -> None:
    total_line = "SUMME NETTO 20,00 MWST 3,80 BRUTTO 23,80 EUR"

    amount, source_line = receipt_parser_service.detect_total_amount(
        lines=[total_line],
    )

    assert amount == Decimal("23.80")
    assert source_line == total_line


# Verifies that product prices are not used without a total keyword.
# This test exists to prevent an item price from being treated
# as the final receipt amount.
# Parameters:
# - None.
# Returns:
# - None.
def test_detect_total_amount_returns_none_without_total_keyword() -> None:
    amount, source_line = receipt_parser_service.detect_total_amount(
        lines=[
            "Milch 1,49",
            "Brot 2,19",
            "Käse 4,99",
        ],
    )

    assert amount is None
    assert source_line is None


# Verifies localized monetary amount conversion.
# This test exists to convert OCR amount strings into exact Decimal values.
# Parameters:
# - value: localized amount string.
# - expected_amount: normalized Decimal value.
# Returns:
# - None.
@pytest.mark.parametrize(
    ("value", "expected_amount"),
    [
        ("24,99", Decimal("24.99")),
        ("24.99", Decimal("24.99")),
        ("1.234,56", Decimal("1234.56")),
        ("1,234.56", Decimal("1234.56")),
        ("1 234,56", Decimal("1234.56")),
        ("1'234.56", Decimal("1234.56")),
    ],
)
def test_parse_decimal_amount_supports_localized_values(
    value: str,
    expected_amount: Decimal,
) -> None:
    result = receipt_parser_service.parse_decimal_amount(
        value=value,
    )

    assert result == expected_amount


# Verifies that invalid and non-positive amounts are rejected.
# This test exists to prevent unusable values from entering receipt metadata.
# Parameters:
# - value: invalid or non-positive amount value.
# Returns:
# - None.
@pytest.mark.parametrize(
    "value",
    [
        "",
        "invalid",
        "0,00",
        "0.00",
        "-1,00",
    ],
)
def test_parse_decimal_amount_rejects_invalid_values(
    value: str,
) -> None:
    result = receipt_parser_service.parse_decimal_amount(
        value=value,
    )

    assert result is None


# Verifies normalization of currency symbols and currency codes.
# This test exists to provide consistent three-letter currency values.
# Parameters:
# - text: receipt text containing a currency.
# - expected_currency: normalized currency code.
# Returns:
# - None.
@pytest.mark.parametrize(
    ("text", "expected_currency"),
    [
        ("SUMME 24,99 EUR", "EUR"),
        ("TOTAL USD 24.99", "USD"),
        ("TOTAL 24,99 €", "EUR"),
        ("TOTAL 24.99 $", "USD"),
        ("TOTAL 24.99 £", "GBP"),
        ("SUMME CHF 12,50", "CHF"),
        ("TOTAL GBP 10.00", "GBP"),
    ],
)
def test_detect_currency_normalizes_supported_currency(
    text: str,
    expected_currency: str,
) -> None:
    result = receipt_parser_service.detect_currency(
        text=text,
    )

    assert result == expected_currency


# Verifies that parser searches the full receipt when the total line
# does not contain a currency.
# This test exists to support receipts that print payment currency
# separately from the total amount.
# Parameters:
# - None.
# Returns:
# - None.
def test_parse_receipt_text_detects_currency_outside_total_line() -> None:
    ocr_text = """
        ALDI SÜD
        31.07.2026
        SUMME 24,99
        ZAHLUNG EUR
    """

    result = receipt_parser_service.parse_receipt_text(
        ocr_text=ocr_text,
    )

    assert result.total_amount_detected == Decimal("24.99")
    assert result.currency_detected == "EUR"


# Verifies supported European and ISO purchase date formats.
# This test exists to normalize common receipt dates into datetime.date.
# Parameters:
# - receipt_date: date text found in OCR output.
# - expected_date: normalized date.
# Returns:
# - None.
@pytest.mark.parametrize(
    ("receipt_date", "expected_date"),
    [
        ("31.07.2026", date(2026, 7, 31)),
        ("31/07/2026", date(2026, 7, 31)),
        ("31-07-2026", date(2026, 7, 31)),
        ("31.07.26", date(2026, 7, 31)),
        ("2026-07-31", date(2026, 7, 31)),
    ],
)
def test_detect_purchase_date_supports_common_formats(
    receipt_date: str,
    expected_date: date,
) -> None:
    result = receipt_parser_service.detect_purchase_date(
        lines=[
            "LIDL",
            f"DATUM {receipt_date} 14:30",
        ],
    )

    assert result == expected_date


# Verifies that invalid dates are skipped.
# This test exists to prevent impossible calendar values
# from being stored as purchase dates.
# Parameters:
# - None.
# Returns:
# - None.
def test_detect_purchase_date_returns_none_for_invalid_date() -> None:
    result = receipt_parser_service.detect_purchase_date(
        lines=[
            "DATUM 31.02.2026",
            "SUMME 24,99 EUR",
        ],
    )

    assert result is None


# Verifies expansion of two-digit receipt years.
# This test exists to keep short year values deterministic.
# Parameters:
# - year: two-digit or four-digit year.
# - expected_year: normalized four-digit year.
# Returns:
# - None.
@pytest.mark.parametrize(
    ("year", "expected_year"),
    [
        (26, 2026),
        (69, 2069),
        (70, 1970),
        (99, 1999),
        (2026, 2026),
    ],
)
def test_normalize_year_returns_four_digit_year(
    year: int,
    expected_year: int,
) -> None:
    result = receipt_parser_service.normalize_year(
        year=year,
    )

    assert result == expected_year