#!/usr/bin/env python3
"""
Country detection for a phone number, and the country table the WhatsApp
contact form's selector is driven from.

The table is the one the bot already ships: calling code -> (Indonesian name,
flag emoji, digits used for the form's search box). 206 entries, 160 of them
three-digit codes, so matching must be longest-prefix-first or +211/+212/+249
collide. The bot's own comment calls this out:

    # Sudan (+249) vs Sudan Selatan (+211): harus cocok kode juga

Nothing here sends anything. It answers "which country is this number in, and
what should the form's country picker be told" - the lookup that has to be
right before any other step.
"""

import json
import re

COUNTRIES = {
    '+211': ('Sudan Selatan', '🇸🇸', '211'),
    '+212': ('Maroko', '🇲🇦', '212'),
    '+213': ('Aljazair', '🇩🇿', '213'),
    '+216': ('Tunisia', '🇹🇳', '216'),
    '+218': ('Libya', '🇱🇾', '218'),
    '+220': ('Gambia', '🇬🇲', '220'),
    '+221': ('Senegal', '🇸🇳', '221'),
    '+222': ('Mauritania', '🇲🇷', '222'),
    '+223': ('Mali', '🇲🇱', '223'),
    '+224': ('Guinea', '🇬🇳', '224'),
    '+225': ('Pantai Gading', '🇨🇮', '225'),
    '+226': ('Burkina Faso', '🇧🇫', '226'),
    '+227': ('Niger', '🇳🇪', '227'),
    '+228': ('Togo', '🇹🇬', '228'),
    '+229': ('Benin', '🇧🇯', '229'),
    '+230': ('Mauritius', '🇲🇺', '230'),
    '+231': ('Liberia', '🇱🇷', '231'),
    '+232': ('Sierra Leone', '🇸🇱', '232'),
    '+233': ('Ghana', '🇬🇭', '233'),
    '+234': ('Nigeria', '🇳🇬', '234'),
    '+235': ('Chad', '🇹🇩', '235'),
    '+236': ('Republik Afrika Tengah', '🇨🇫', '236'),
    '+237': ('Kamerun', '🇨🇲', '237'),
    '+238': ('Tanjung Verde', '🇨🇻', '238'),
    '+239': ('Sao Tome', '🇸🇹', '239'),
    '+240': ('Guinea Khatulistiwa', '🇬🇶', '240'),
    '+241': ('Gabon', '🇬🇦', '241'),
    '+242': ('Kongo', '🇨🇬', '242'),
    '+243': ('Kongo', '🇨🇩', '243'),
    '+244': ('Angola', '🇦🇴', '244'),
    '+245': ('Guinea-Bissau', '🇬🇼', '245'),
    '+246': ('Diego Garcia', '🇮🇴', '246'),
    '+248': ('Seychelles', '🇸🇨', '248'),
    '+249': ('Sudan', '🇸🇩', '249'),
    '+250': ('Rwanda', '🇷🇼', '250'),
    '+251': ('Ethiopia', '🇪🇹', '251'),
    '+252': ('Somalia', '🇸🇴', '252'),
    '+253': ('Djibouti', '🇩🇯', '253'),
    '+254': ('Kenya', '🇰🇪', '254'),
    '+255': ('Tanzania', '🇹🇿', '255'),
    '+256': ('Uganda', '🇺🇬', '256'),
    '+257': ('Burundi', '🇧🇮', '257'),
    '+258': ('Mozambik', '🇲🇿', '258'),
    '+260': ('Zambia', '🇿🇲', '260'),
    '+261': ('Madagaskar', '🇲🇬', '261'),
    '+262': ('Reunion', '🇷🇪', '262'),
    '+263': ('Zimbabwe', '🇿🇼', '263'),
    '+264': ('Namibia', '🇳🇦', '264'),
    '+265': ('Malawi', '🇲🇼', '265'),
    '+266': ('Lesotho', '🇱🇸', '266'),
    '+267': ('Botswana', '🇧🇼', '267'),
    '+268': ('Swaziland', '🇸🇿', '268'),
    '+269': ('Komoro', '🇰🇲', '269'),
    '+290': ('St Helena', '🇸🇭', '290'),
    '+291': ('Eritrea', '🇪🇷', '291'),
    '+297': ('Aruba', '🇦🇼', '297'),
    '+298': ('Kepulauan Faroe', '🇫🇴', '298'),
    '+299': ('Greenland', '🇬🇱', '299'),
    '+350': ('Gibraltar', '🇬🇮', '350'),
    '+351': ('Portugal', '🇵🇹', '351'),
    '+352': ('Luksemburg', '🇱🇺', '352'),
    '+353': ('Irlandia', '🇮🇪', '353'),
    '+354': ('Islandia', '🇮🇸', '354'),
    '+355': ('Albania', '🇦🇱', '355'),
    '+356': ('Malta', '🇲🇹', '356'),
    '+357': ('Siprus', '🇨🇾', '357'),
    '+358': ('Finlandia', '🇫🇮', '358'),
    '+359': ('Bulgaria', '🇧🇬', '359'),
    '+370': ('Lituania', '🇱🇹', '370'),
    '+371': ('Latvia', '🇱🇻', '371'),
    '+372': ('Estonia', '🇪🇪', '372'),
    '+373': ('Moldova', '🇲🇩', '373'),
    '+374': ('Armenia', '🇦🇲', '374'),
    '+375': ('Belarus', '🇧🇾', '375'),
    '+376': ('Andorra', '🇦🇩', '376'),
    '+377': ('Monako', '🇲🇨', '377'),
    '+378': ('San Marino', '🇸🇲', '378'),
    '+380': ('Ukraina', '🇺🇦', '380'),
    '+381': ('Serbia', '🇷🇸', '381'),
    '+382': ('Montenegro', '🇲🇪', '382'),
    '+383': ('Kosovo', '🇽🇰', '383'),
    '+385': ('Kroasia', '🇭🇷', '385'),
    '+386': ('Slovenia', '🇸🇮', '386'),
    '+387': ('Bosnia', '🇧🇦', '387'),
    '+389': ('Makedonia Utara', '🇲🇰', '389'),
    '+420': ('Ceko', '🇨🇿', '420'),
    '+421': ('Slowakia', '🇸🇰', '421'),
    '+423': ('Liechtenstein', '🇱🇮', '423'),
    '+500': ('Kepulauan Falkland', '🇫🇰', '500'),
    '+501': ('Belize', '🇧🇿', '501'),
    '+502': ('Guatemala', '🇬🇹', '502'),
    '+503': ('El Salvador', '🇸🇻', '503'),
    '+504': ('Honduras', '🇭🇳', '504'),
    '+505': ('Nikaragua', '🇳🇮', '505'),
    '+506': ('Kosta Rika', '🇨🇷', '506'),
    '+507': ('Panama', '🇵🇦', '507'),
    '+508': ('Saint Pierre', '🇵🇲', '508'),
    '+509': ('Haiti', '🇭🇹', '509'),
    '+590': ('Guadeloupe', '🇬🇵', '590'),
    '+591': ('Bolivia', '🇧🇴', '591'),
    '+592': ('Guyana', '🇬🇾', '592'),
    '+593': ('Ekuador', '🇪🇨', '593'),
    '+594': ('Guyana Prancis', '🇬🇫', '594'),
    '+595': ('Paraguay', '🇵🇾', '595'),
    '+596': ('Martinik', '🇲🇶', '596'),
    '+597': ('Suriname', '🇸🇷', '597'),
    '+598': ('Uruguay', '🇺🇾', '598'),
    '+599': ('Antillen Belanda', '🇧🇶', '599'),
    '+670': ('Timor Leste', '🇹🇱', '670'),
    '+672': ('Antartika', '🇦🇶', '672'),
    '+673': ('Brunei', '🇧🇳', '673'),
    '+674': ('Nauru', '🇳🇷', '674'),
    '+675': ('Papua Nugini', '🇵🇬', '675'),
    '+676': ('Tonga', '🇹🇴', '676'),
    '+677': ('Kepulauan Solomon', '🇸🇧', '677'),
    '+678': ('Vanuatu', '🇻🇺', '678'),
    '+679': ('Fiji', '🇫🇯', '679'),
    '+680': ('Palau', '🇵🇼', '680'),
    '+681': ('Wallis', '🇼🇫', '681'),
    '+682': ('Kepulauan Cook', '🇨🇰', '682'),
    '+683': ('Niue', '🇳🇺', '683'),
    '+684': ('Samoa', '🇼🇸', '684'),
    '+685': ('Samoa', '🇼🇸', '685'),
    '+686': ('Kiribati', '🇰🇮', '686'),
    '+687': ('Kaledonia Baru', '🇳🇨', '687'),
    '+688': ('Tuvalu', '🇹🇻', '688'),
    '+689': ('Polinesia Prancis', '🇵🇫', '689'),
    '+690': ('Tokelau', '🇹🇰', '690'),
    '+691': ('Mikronesia', '🇫🇲', '691'),
    '+692': ('Marshall', '🇲🇭', '692'),
    '+850': ('Korea Utara', '🇰🇵', '850'),
    '+852': ('Hong Kong', '🇭🇰', '852'),
    '+853': ('Makau', '🇲🇴', '853'),
    '+855': ('Kamboja', '🇰🇭', '855'),
    '+856': ('Laos', '🇱🇦', '856'),
    '+880': ('Bangladesh', '🇧🇩', '880'),
    '+886': ('Taiwan', '🇹🇼', '886'),
    '+960': ('Maladewa', '🇲🇻', '960'),
    '+961': ('Lebanon', '🇱🇧', '961'),
    '+962': ('Yordania', '🇯🇴', '962'),
    '+963': ('Suriah', '🇸🇾', '963'),
    '+964': ('Irak', '🇮🇶', '964'),
    '+965': ('Kuwait', '🇰🇼', '965'),
    '+966': ('Arab Saudi', '🇸🇦', '966'),
    '+967': ('Yaman', '🇾🇪', '967'),
    '+968': ('Oman', '🇴🇲', '968'),
    '+970': ('Palestina', '🇵🇸', '970'),
    '+971': ('UEA', '🇦🇪', '971'),
    '+972': ('Israel', '🇮🇱', '972'),
    '+973': ('Bahrain', '🇧🇭', '973'),
    '+974': ('Qatar', '🇶🇦', '974'),
    '+975': ('Bhutan', '🇧🇹', '975'),
    '+976': ('Mongolia', '🇲🇳', '976'),
    '+977': ('Nepal', '🇳🇵', '977'),
    '+992': ('Tajikistan', '🇹🇯', '992'),
    '+993': ('Turkmenistan', '🇹🇲', '993'),
    '+994': ('Azerbaijan', '🇦🇿', '994'),
    '+995': ('Georgia', '🇬🇪', '995'),
    '+996': ('Kirgizstan', '🇰🇬', '996'),
    '+998': ('Uzbekistan', '🇺🇿', '998'),
    '+20': ('Mesir', '🇪🇬', '20'),
    '+27': ('Afrika Selatan', '🇿🇦', '27'),
    '+30': ('Yunani', '🇬🇷', '30'),
    '+31': ('Belanda', '🇳🇱', '31'),
    '+32': ('Belgia', '🇧🇪', '32'),
    '+33': ('Prancis', '🇫🇷', '33'),
    '+34': ('Spanyol', '🇪🇸', '34'),
    '+36': ('Hungaria', '🇭🇺', '36'),
    '+39': ('Italia', '🇮🇹', '39'),
    '+40': ('Rumania', '🇷🇴', '40'),
    '+41': ('Swiss', '🇨🇭', '41'),
    '+43': ('Austria', '🇦🇹', '43'),
    '+44': ('Inggris', '🇬🇧', '44'),
    '+45': ('Denmark', '🇩🇰', '45'),
    '+46': ('Swedia', '🇸🇪', '46'),
    '+47': ('Norwegia', '🇳🇴', '47'),
    '+48': ('Polandia', '🇵🇱', '48'),
    '+49': ('Jerman', '🇩🇪', '49'),
    '+51': ('Peru', '🇵🇪', '51'),
    '+52': ('Meksiko', '🇲🇽', '52'),
    '+53': ('Kuba', '🇨🇺', '53'),
    '+54': ('Argentina', '🇦🇷', '54'),
    '+55': ('Brasil', '🇧🇷', '55'),
    '+56': ('Chili', '🇨🇱', '56'),
    '+57': ('Kolombia', '🇨🇴', '57'),
    '+58': ('Venezuela', '🇻🇪', '58'),
    '+60': ('Malaysia', '🇲🇾', '60'),
    '+61': ('Australia', '🇦🇺', '61'),
    '+62': ('Indonesia', '🇮🇩', '62'),
    '+63': ('Filipina', '🇵🇭', '63'),
    '+64': ('Selandia Baru', '🇳🇿', '64'),
    '+65': ('Singapura', '🇸🇬', '65'),
    '+66': ('Thailand', '🇹🇭', '66'),
    '+81': ('Jepang', '🇯🇵', '81'),
    '+82': ('Korea Selatan', '🇰🇷', '82'),
    '+84': ('Vietnam', '🇻🇳', '84'),
    '+86': ('Tiongkok', '🇨🇳', '86'),
    '+90': ('Turki', '🇹🇷', '90'),
    '+91': ('India', '🇮🇳', '91'),
    '+92': ('Pakistan', '🇵🇰', '92'),
    '+93': ('Afganistan', '🇦🇫', '93'),
    '+94': ('Sri Lanka', '🇱🇰', '94'),
    '+95': ('Myanmar', '🇲🇲', '95'),
    '+98': ('Iran', '🇮🇷', '98'),
    '+1': ('Amerika Serikat', '🇺🇸', '1'),
    '+7': ('Rusia', '🇷🇺', '7'),
}
# Longest first, so +212 5 beats +21 and +1 876 beats +1.
_ORDERED = sorted(COUNTRIES.keys(), key=len, reverse=True)
_SPACE = re.compile(r"[\s\-().]+")


def _digits(phone):
    return "".join(ch for ch in str(phone or "") if ch.isdigit())


def detect(phone, default="+62"):
    """Longest-prefix country match for a phone number.

    Returns ``(calling_code, (name, flag, search_code))``. The default matches
    the bot's own behaviour: an unrecognised number falls back to Indonesia
    rather than failing, because the form still has to be filled in.
    """
    d = _digits(phone)
    if not d:
        return default, COUNTRIES[default]
    # Try with spaces first (the table has "+1 876" style keys), then plain.
    spaced = _SPACE.sub(" ", str(phone or "").strip())
    probe = _SPACE.sub(" ", "+" + d)
    for key in _ORDERED:
        norm = _SPACE.sub(" ", key)
        if probe.startswith(norm):
            return key, COUNTRIES[key]
    for key in _ORDERED:
        if d.startswith(key.lstrip("+").replace(" ", "")):
            return key, COUNTRIES[key]
    return default, COUNTRIES[default]


def local_number(phone, calling_code):
    """The part the form wants: the national number without the calling code."""
    d = _digits(phone)
    cc = _digits(calling_code)
    if cc and d.startswith(cc):
        return d[len(cc):]
    return d


def selector_terms(calling_code, table_entry):
    """What the form's country search box should be tried with, in order.

    The bot tries the display name first and then the bare code, and accepts
    the option only when the resulting widget shows the expected code - that
    check is what stops Sudan (+249) matching South Sudan (+211).
    """
    name, flag, search_code = table_entry
    terms = []
    for t in (name, search_code):
        if t and t not in terms:
            terms.append(t)
    return terms


def search_candidates(number):
    """Convenience: everything the form needs for one number.

    ``{"number", "calling_code", "country", "flag", "search_code",
       "local_number", "search_terms", "target_code"}}``
    """
    cc, entry = detect(number)
    name, flag, search_code = entry
    return {
        "number": _digits(number),
        "calling_code": cc,
        "country": name,
        "flag": flag,
        "search_code": search_code,
        "local_number": local_number(number, cc),
        "search_terms": selector_terms(cc, entry),
        "target_code": search_code,
        "matched_exact": cc in (str(number or "").strip()),
    }


def all_countries():
    """The whole table, sorted by calling code."""
    out = []
    for key in sorted(COUNTRIES, key=lambda k: (len(_digits(k)), _digits(k))):
        name, flag, code = COUNTRIES[key]
        out.append({"calling_code": key, "country": name, "flag": flag,
                    "search_code": code})
    return out
