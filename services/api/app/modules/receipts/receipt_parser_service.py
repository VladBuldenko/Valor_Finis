import re
from dataclasses import dataclass
from datetime import date
from decimal import Decimal, InvalidOperation
from typing import List, Optional, Sequence, Tuple


TOTAL_KEYWORDS = (
    "ZU ZAHLEN",
    "GESAMTBETRAG",
    "ENDSUMME",
    "GESAMT",
    "SUMME",
    "TOTAL",
    "BETRAG",
)

MERCHANT_EXCLUDED_PREFIXES = (
    "BON",
    "BELEG",
    "KASSE",
    "FILIALE",
    "TEL",
    "TELEFON",
    "WWW",
    "UST-ID",
    "UST ID",
    "MWST",
)

AMOUNT_PATTERN = re.compile(
    r"(?<![\d.,])"
    r"("
    r"\d{1,3}(?:[.\s',]\d{3})+[.,]\d{2}"
    r"|"
    r"\d+[.,]\d{2}"
    r")"
    r"(?![\d.,])"
)

CURRENCY_PATTERN = re.compile(
    r"\b(EUR|USD|CHF|GBP)\b|€|\$|£",
    re.IGNORECASE,
)

DATE_PATTERNS = (
    re.compile(
        r"(?<!\d)"
        r"(?P<day>\d{1,2})[./-]"
        r"(?P<month>\d{1,2})[./-]"
        r"(?P<year>\d{2,4})"
        r"(?!\d)"
    ),
    re.compile(
        r"(?<!\d)"
        r"(?P<year>\d{4})-"
        r"(?P<month>\d{1,2})-"
        r"(?P<day>\d{1,2})"
        r"(?!\d)"
    ),
)


@dataclass(frozen=True)
class ParsedReceiptData:
    """
    Structured data detected in raw receipt OCR text.

    What:
        Contains optional receipt values extracted by parser heuristics.

    Why:
        Keeps text parsing isolated from persistence and API schemas.
    """

    merchant_detected: Optional[str] = None
    total_amount_detected: Optional[Decimal] = None
    currency_detected: Optional[str] = None
    purchase_date_detected: Optional[date] = None


# Parses raw OCR text into structured receipt values.
# This function exists to coordinate merchant, amount, currency,
# and purchase date detection without accessing the database.
# Parameters:
# - ocr_text: raw text returned by the OCR provider.
# Returns:
# - ParsedReceiptData containing all successfully detected values.
def parse_receipt_text(ocr_text: str) -> ParsedReceiptData:
    lines = normalize_receipt_lines(ocr_text)

    if not lines:
        return ParsedReceiptData()

    total_amount, total_line = detect_total_amount(lines)

    currency_detected = None

    if total_line is not None:
        currency_detected = detect_currency(total_line)

    if currency_detected is None:
        currency_detected = detect_currency("\n".join(lines))

    return ParsedReceiptData(
        merchant_detected=detect_merchant(lines),
        total_amount_detected=total_amount,
        currency_detected=currency_detected,
        purchase_date_detected=detect_purchase_date(lines),
    )

# Normalizes OCR text into non-empty receipt lines.
# This function exists to remove surrounding whitespace
# and make later parser operations consistent.
# Parameters:
# - ocr_text: raw OCR text.
# Returns:
# - List of normalized non-empty lines.
def normalize_receipt_lines(ocr_text: str) -> List[str]:
    normalized_lines = []

    for raw_line in ocr_text.splitlines():
        normalized_line = " ".join(raw_line.strip().split())

        if normalized_line:
            normalized_lines.append(normalized_line)

    return normalized_lines


# Detects the most likely merchant name.
# This function exists to use the first meaningful textual line
# while skipping common receipt metadata.
# Parameters:
# - lines: normalized OCR text lines.
# Returns:
# - Merchant name or None when no suitable line exists.
def detect_merchant(lines: Sequence[str]) -> Optional[str]:
    for line in lines:
        normalized_line = line.strip(" |*_-=.:")
        upper_line = normalized_line.upper()

        if not normalized_line:
            continue

        if len(normalized_line) > 120:
            continue

        if not any(character.isalpha() for character in normalized_line):
            continue

        if any(keyword in upper_line for keyword in TOTAL_KEYWORDS):
            continue

        if upper_line.startswith(MERCHANT_EXCLUDED_PREFIXES):
            continue

        if contains_date(normalized_line):
            continue

        return normalized_line

    return None


# Detects the receipt total from lines containing total-related keywords.
# This function exists to avoid treating product prices or tax values
# as the final receipt amount.
# Parameters:
# - lines: normalized OCR text lines.
# Returns:
# - Tuple containing detected Decimal amount and its source line.
def detect_total_amount(
    lines: Sequence[str],
) -> Tuple[Optional[Decimal], Optional[str]]:
    for keyword in TOTAL_KEYWORDS:
        for line in lines:
            if keyword not in line.upper():
                continue

            amount_matches = AMOUNT_PATTERN.findall(line)

            if not amount_matches:
                continue

            amount = parse_decimal_amount(amount_matches[-1])

            if amount is not None:
                return amount, line

    return None, None


# Converts a localized amount string into Decimal.
# This function exists to support comma and dot decimal separators
# together with optional thousands separators.
# Parameters:
# - value: localized monetary amount.
# Returns:
# - Positive Decimal amount or None when parsing fails.
def parse_decimal_amount(value: str) -> Optional[Decimal]:
    normalized_value = (
        value.replace(" ", "")
        .replace("'", "")
    )

    last_comma_index = normalized_value.rfind(",")
    last_dot_index = normalized_value.rfind(".")

    if last_comma_index > last_dot_index:
        normalized_value = (
            normalized_value.replace(".", "")
            .replace(",", ".")
        )
    elif last_dot_index > last_comma_index:
        normalized_value = normalized_value.replace(",", "")

    try:
        amount = Decimal(normalized_value)
    except InvalidOperation:
        return None

    if amount <= 0:
        return None

    return amount


# Detects currency from OCR text.
# This function exists to normalize supported currency symbols
# and codes into three-letter currency codes.
# Parameters:
# - text: receipt text or the detected total line.
# Returns:
# - Currency code or None when no supported currency is found.
def detect_currency(text: str) -> Optional[str]:
    currency_match = CURRENCY_PATTERN.search(text)

    if currency_match is None:
        return None

    currency_value = currency_match.group(0).upper()

    currency_mapping = {
        "€": "EUR",
        "$": "USD",
        "£": "GBP",
    }

    return currency_mapping.get(
        currency_value,
        currency_value,
    )


# Detects the first valid purchase date in receipt text.
# This function exists to support common European and ISO date formats.
# Parameters:
# - lines: normalized OCR text lines.
# Returns:
# - Parsed date or None when no valid date is found.
def detect_purchase_date(
    lines: Sequence[str],
) -> Optional[date]:
    for line in lines:
        for date_pattern in DATE_PATTERNS:
            date_match = date_pattern.search(line)

            if date_match is None:
                continue

            day = int(date_match.group("day"))
            month = int(date_match.group("month"))
            year = normalize_year(
                int(date_match.group("year")),
            )

            try:
                return date(
                    year=year,
                    month=month,
                    day=day,
                )
            except ValueError:
                continue

    return None


# Checks whether text contains a supported date.
# This function exists to prevent date lines from being selected
# as merchant names.
# Parameters:
# - value: normalized receipt line.
# Returns:
# - True when a supported date pattern is found.
def contains_date(value: str) -> bool:
    return any(
        date_pattern.search(value) is not None
        for date_pattern in DATE_PATTERNS
    )


# Expands a two-digit receipt year into a four-digit year.
# This function exists to support dates such as 29.07.26.
# Parameters:
# - year: parsed two-digit or four-digit year.
# Returns:
# - Normalized four-digit year.
def normalize_year(year: int) -> int:
    if year >= 100:
        return year

    if year <= 69:
        return 2000 + year

    return 1900 + year