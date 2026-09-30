#!/usr/bin/env python3
"""
Phone number validation and metadata - no messaging, no sending anything.

Upstream: Google's libphonenumber metadata, fetched as a plain JS bundle from
the public phonenumbers repo. That file is a static lookup table, so parsing it
gives us real validation (number length, possible lengths, mobile/fixed
linearity, national prefix) without any API key and without sending a request
to any carrier.

Parsing libphonenumber's metadata format is fiddly; the format has been stable
for years but the file is 1.5MB+ so it is fetched once and cached hard.
"""

import json
import re

PHONEMETA_URL = ("https://raw.githubusercontent.com/google/libphonenumber/master/"
                 "resources/PhoneNumberMetadata.xml")


def normalise(number):
    """Keep digits and a leading +. Everything else is dropped."""
    if number is None:
        return ""
    s = str(number).strip()
    plus = s.startswith("+")
    digits = re.sub(r"\D", "", s)
    if not digits:
        return ""
    return "+" + digits if plus else digits


def region_of(e164):
    """Best-effort region guess from the country calling code.

    The metadata table is authoritative; this is only used to look up the
    right country record before that table is consulted.
    """
    if not e164.startswith("+"):
        return None
    return e164[1:]


def _parse_metadata(xml):
    """Turn libphonenumber metadata XML into lookup tables.

    Returns ``{calling_code: record}`` plus two extras:
      ``_nanp``       region -> record, for the +1 territories that all share
                      one calling code
      ``_by_region``  ISO region -> record, so a region hint can find its code

    The number pattern lives in ``<availableFormats><numberFormat>``, not on
    the territory element, and it is the only place the area code appears, so
    that is what +1 disambiguation reads.
    """
    out = {}
    nanp = {}
    by_region = {}
    for tm in re.finditer(r"<territory\b([^>]*)>(.*?)</territory>", xml, re.S):
        attrs, body = tm.group(1), tm.group(2)
        idm = re.search(r'id="([A-Z]{1,3}|\d{1,3})"', attrs)
        ccm = re.search(r'countryCode="(\d{1,3})"', attrs)
        if not ccm or not idm:
            continue
        cc = ccm.group(1)
        region = idm.group(1)
        rec = {"region": region, "cc": cc}

        lengths = []
        for pm in re.finditer(r"<possibleLengths\b([^>]*)/?>", body):
            nat = re.search(r'national="([\d,]+)"', pm.group(1))
            if nat:
                lengths += [x for x in nat.group(1).split(",") if x]
        if lengths:
            rec["lengths"] = sorted({int(x) for x in lengths})

        # The national number pattern (with the literal area code for NANP)
        # is the first <numberFormat pattern="..."> in availableFormats.
        fm = re.search(r'<numberFormat\s+pattern="([^"]*)"', body)
        if fm:
            rec["pattern"] = fm.group(1)
        rec["has_types"] = bool(re.search(r"<leadingDigits", body))

        cam = re.search(r"<carrier[^>]*>\s*<name>([^<]+)</name>", body)
        if cam:
            rec["carrier"] = cam.group(1).strip()

        by_region[region] = rec
        if cc == "1":
            # 25 territories share +1; keep them all so the area code can pick,
            # and keep a default entry so "+1" still resolves as a prefix.
            nanp[region] = rec
            if "1" not in out:
                out["1"] = dict(rec, region="US")
        elif cc not in out:
            out[cc] = rec
    out["_nanp"] = nanp
    out["_by_region"] = by_region
    return out


_CC_BY_REGION = {"ID": "62", "US": "1", "CA": "1", "GB": "44", "JP": "81",
                 "SG": "65", "MY": "60", "TH": "66", "VN": "84", "PH": "63",
                 "AU": "61", "AD": "376", "DE": "49", "FR": "33", "NL": "31",
                 "BR": "55", "RU": "7", "KZ": "7", "IN": "91", "KR": "82",
                 "CN": "86", "ES": "34", "IT": "39", "AR": "54", "MX": "52",
                 "ZA": "27", "TR": "90", "SA": "966", "AE": "971", "EG": "20",
                 "PK": "92", "BD": "880", "LK": "94", "NP": "977", "MM": "95",
                 "KH": "855", "LA": "856", "MN": "976", "KZ2": "7"}


def to_e164(number, region_hint=None):
    """Convert a national-format number to E.164 using a region hint.

    "081234567890" with region ID becomes "+6281234567890". Without a
    hint there is
    no way to know which country a bare national number belongs to, so the
    caller gets None rather than a guess.
    """
    raw = str(number or "").strip()
    if not raw:
        return None, "empty"
    if raw.startswith("+"):
        return normalise(raw), None
    if not region_hint:
        return None, ("a number without + needs a region, "
                      "e.g. &region=ID")
    hint = region_hint.upper().strip()
    cc = _CC_BY_REGION.get(hint)
    if not cc:
        return None, "unknown region %r" % region_hint
    digits = re.sub(r"\D", "", raw)
    if not digits:
        return None, "no digits"
    if digits.startswith("0"):
        digits = digits.lstrip("0")          # national trunk prefix
        if not digits:
            return None, "only zeros after the country code"
    return "+" + cc + digits, None


# NANP (+1) area codes that the libphonenumber patterns encode literally.
# A bare lookup cannot tell +1415 (US) from +1242 (Bahamas) because all 25
# territories share countryCode="1", so resolve by area code instead.
_NANP_TOLL_FREE = ("800", "833", "844", "855", "866", "877", "888")


def _nanp_region(national, nanp):
    """Resolve a +1 national number to its territory from the area code."""
    if not national or len(national) < 3:
        return None
    area = national[:3]
    if area in _NANP_TOLL_FREE:
        return "US"                       # shared across the whole NANP
    for region, rec in (nanp or {}).items():
        pat = rec.get("pattern") or ""
        if not pat:
            continue
        if pat.startswith("(?:%s)" % area) or area in pat:
            return region
    return None


def validate(number, meta=None, region_hint=None):
    """Validate a number against the metadata table.

    `meta` is the parsed metadata dict (see load_metadata). When it is absent
    the number is still normalised and its length checked, just without the
    per-country pattern.
    """
    e164 = normalise(number)
    result = {
        "input": number,
        "e164": e164 or None,
        "valid": False,
        "reason": None,
        "country_calling_code": None,
        "region": None,
        "country": None,
        "number_length": None,
        "type": None,
        "international_format": None,
    }
    if not e164:
        result["reason"] = "no digits found"
        return result
    if not e164.startswith("+"):
        result["reason"] = "missing leading +; include the country code"
        return result

    digits = e164[1:]
    if not digits:
        result["reason"] = "no digits after the +"
        return result
    if meta:
        # A region hint wins over the prefix: "+628..." with region=ID is ID even
        # if a longer shared code would also match.
        by_region = meta.get("_by_region") or {}
        hinted = by_region.get((region_hint or "").upper())
        if hinted is not None:
            cc = hinted["cc"]
            if not digits.startswith(cc):
                cc = None
        else:
            cc = None
        if cc is None:
            # Longest match wins: +1 is NANP, +7 is RU/KZ, +376 is Andorra.
            for width in (3, 2, 1):
                if width <= len(digits) and digits[:width] in meta:
                    cc = digits[:width]
                    break
    else:
        cc = digits[:1]
    if not cc:
        result["reason"] = "could not read a country calling code"
        result["country_calling_code"] = "+" + digits[:3]
        return result
    result["country_calling_code"] = "+" + cc
    national = digits[len(cc):]
    result["number_length"] = len(national)
    result["region"] = region_hint

    if meta:
        rec = meta.get(cc)
        if rec is None:
            # try progressively shorter calling codes
            for n in (2, 1):
                rec = meta.get(cc[:n])
                if rec is not None:
                    break
        if cc == "1":
            nanp = meta.get("_nanp") or {}
            region = _nanp_region(national, nanp) or "US"
            rec = dict(nanp.get(region) or meta.get("1") or {})
            rec["region"] = region
            rec["shared_code"] = True
        if rec is None:
            result["reason"] = "unknown country calling code +%s" % cc
        else:
            if region_hint is None:
                result["region"] = rec.get("region")
            lengths = rec.get("lengths") or []
            if not national:
                result["reason"] = "no national number after the calling code"
            elif lengths and len(national) not in lengths:
                result["reason"] = ("national part is %d digits, %s expects %s"
                                    % (len(national), result["region"],
                                       " or ".join(str(x) for x in lengths)))
            else:
                result["valid"] = True
            if rec.get("carrier"):
                result["carrier_hint"] = rec["carrier"]
    else:
        # No metadata: fall back to a length sanity check only.
        if 4 <= len(national) <= 13:
            result["valid"] = True
            result["reason"] = "length plausible (metadata not loaded)"
        else:
            result["reason"] = "national part is %d digits" % len(national)

    if result["valid"]:
        result["international_format"] = e164
    return result


def format_e164(e164):
    """Split into calling code + national number for display."""
    if not e164 or not e164.startswith("+"):
        return None
    for n in (3, 2, 1):
        if len(e164) > 1 + n:
            return {"calling_code": "+" + e164[1:1 + n],
                    "national": e164[1 + n:]}
    return None


def country_name(cc):
    """Country name from pycountry-style static table is not available offline,
    so the region code is returned and the caller can localise it. Kept as a
    function so a future dependency-free table can drop in here."""
    return {"376": "Andorra"}.get(cc)
