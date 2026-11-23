"""Phone normalisation (Part 1). Pure functions: no HTTP, no storage.

Goal: turn any accepted spelling into ONE canonical E.164 string such as
+966551234567, so "same phone" is a plain string comparison.

Vocabulary used below
  mobile   = the national significant number, WITHOUT any trunk zero
             AE/SA: 5XXXXXXXX (9 digits)    BH: 3XXXXXXX (8 digits)
  national = trunk + mobile   (AE/SA: 05XXXXXXXX, BH: 3XXXXXXX)
  intl     = dial code + mobile (with or without a leading '+')
"""
import re
from dataclasses import dataclass

from .errors import ApiError


@dataclass(frozen=True)
class CountryRule:
    dial: str    # country calling code
    mobile: str  # regex for the mobile part (ASCII digits only!)
    trunk: str   # prefix used in national format ("0" for AE/SA, none for BH)


RULES: dict[str, CountryRule] = {
    "AE": CountryRule("971", r"5[0-9]{8}", "0"),
    "SA": CountryRule("966", r"5[0-9]{8}", "0"),
    "BH": CountryRule("973", r"3[0-9]{7}", ""),
}
COUNTRIES = tuple(RULES)

# Step 1 of the spec: remove spaces, hyphens and round brackets (nothing else).
_STRIP = {ord(" "): None, ord("-"): None, ord("("): None, ord(")"): None}
# Step 2: only digits and ONE optional leading '+' may remain.
# NB: [0-9], not \d, because in Python \d also matches Arabic-Indic digits etc.
_SHAPE = re.compile(r"\+?[0-9]+")


@dataclass(frozen=True)
class ParsedPhone:
    kind: str                 # "international" or "national"
    digits: str               # cleaned digits, '+' removed
    countries: tuple[str, ...]  # intl: the one dial-code country
                                # national: every country whose national shape fits


def _invalid(message: str) -> ApiError:
    return ApiError(422, "INVALID_PHONE", message)


def parse_phone(raw: str) -> ParsedPhone:
    """Clean + classify. Raises INVALID_PHONE if it is none of the 3 spellings."""
    cleaned = raw.translate(_STRIP)
    if not _SHAPE.fullmatch(cleaned):
        raise _invalid("Phone may contain only digits and one leading '+'")
    has_plus = cleaned.startswith("+")
    digits = cleaned.lstrip("+")

    # Spellings 1 and 2: "+<dial><mobile>" or "<dial><mobile>"
    for code, rule in RULES.items():
        if digits.startswith(rule.dial) and re.fullmatch(rule.mobile, digits[len(rule.dial):]):
            return ParsedPhone("international", digits, (code,))

    # A '+' followed by anything that is not dial+mobile is invalid
    # (covers "+0551234567"; "00966..." has no '+' but also fits nothing below).
    if has_plus:
        raise _invalid("Number after '+' is not a valid Gulf mobile")

    # Spelling 3: national mobile. AE and SA look identical, so collect all fits.
    fits = tuple(c for c, r in RULES.items() if re.fullmatch(r.trunk + r.mobile, digits))
    if fits:
        return ParsedPhone("national", digits, fits)

    raise _invalid("Not a valid UAE, Saudi or Bahraini mobile number")


def _national_to_e164(parsed: ParsedPhone, country: str) -> str:
    """Read a national number inside `country`; it must fit that country's shape."""
    if country not in parsed.countries:
        raise _invalid(f"Number is not a valid {country} national mobile")
    rule = RULES[country]
    return "+" + rule.dial + parsed.digits[len(rule.trunk):]


def normalize_for_member(raw: str, member_country: str) -> str:
    """POST /members: international from ANY of the 3 countries is fine
    (foreign SIMs); a national number is read in the member's own country."""
    parsed = parse_phone(raw)
    if parsed.kind == "international":
        return "+" + parsed.digits
    return _national_to_e164(parsed, member_country)


def normalize_for_lookup(raw: str, country: str | None) -> str:
    """GET /members/lookup: stricter, because there is no member country."""
    parsed = parse_phone(raw)
    if parsed.kind == "international":
        if country is not None and country != parsed.countries[0]:
            raise ApiError(422, "PHONE_COUNTRY_MISMATCH",
                           "country parameter disagrees with the dial code")
        return "+" + parsed.digits
    # national
    if country is None:
        # parse_phone already proved it fits at least one national shape
        raise ApiError(422, "PHONE_NEEDS_COUNTRY",
                       "National numbers need a country parameter")
    return _national_to_e164(parsed, country)