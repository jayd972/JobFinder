"""Filter for USA-based jobs."""

import re

# All 50 US state names and their abbreviations
US_STATES = {
    "Alabama": "AL", "Alaska": "AK", "Arizona": "AZ", "Arkansas": "AR",
    "California": "CA", "Colorado": "CO", "Connecticut": "CT", "Delaware": "DE",
    "Florida": "FL", "Georgia": "GA", "Hawaii": "HI", "Idaho": "ID",
    "Illinois": "IL", "Indiana": "IN", "Iowa": "IA", "Kansas": "KS",
    "Kentucky": "KY", "Louisiana": "LA", "Maine": "ME", "Maryland": "MD",
    "Massachusetts": "MA", "Michigan": "MI", "Minnesota": "MN", "Mississippi": "MS",
    "Missouri": "MO", "Montana": "MT", "Nebraska": "NE", "Nevada": "NV",
    "New Hampshire": "NH", "New Jersey": "NJ", "New Mexico": "NM", "New York": "NY",
    "North Carolina": "NC", "North Dakota": "ND", "Ohio": "OH", "Oklahoma": "OK",
    "Oregon": "OR", "Pennsylvania": "PA", "Rhode Island": "RI", "South Carolina": "SC",
    "South Dakota": "SD", "Tennessee": "TN", "Texas": "TX", "Utah": "UT",
    "Vermont": "VT", "Virginia": "VA", "Washington": "WA", "West Virginia": "WV",
    "Wisconsin": "WI", "Wyoming": "WY", "District of Columbia": "DC",
}

US_STATE_CODES = set(US_STATES.values())
US_STATE_NAMES = set(US_STATES.keys())
US_STATE_NAMES_LOWER = {s.lower() for s in US_STATE_NAMES}

US_COUNTRY_KEYWORDS = {
    "united states", "united states of america", "usa", "u.s.", "u.s.a.",
}

# Common US city names (for heuristic location matching)
MAJOR_US_CITIES = {
    "new york", "los angeles", "chicago", "houston", "phoenix", "philadelphia",
    "san antonio", "san diego", "dallas", "san jose", "austin", "jacksonville",
    "san francisco", "seattle", "denver", "boston", "nashville", "atlanta",
    "portland", "las vegas", "miami", "minneapolis", "raleigh", "charlotte",
    "salt lake city", "pittsburgh", "detroit", "st. louis", "tampa",
    "waltham", "redmond", "sunnyvale", "mountain view", "palo alto",
    "cupertino", "menlo park", "santa clara", "irvine", "boulder",
    "arlington", "bellevue", "cambridge", "herndon", "mclean",
}


def is_usa_job(job):
    """
    Determine if a job is located in the USA.

    Checks in order of reliability:
    1. country.alpha2Code == "US"
    2. country.descriptor contains US keywords
    3. jobRequisitionLocation.country.alpha2Code == "US"
    4. Location text matches US state or major city
    5. Remote handling: "Remote - USA" counts, bare "Remote" does not

    Returns: (is_usa: bool, country_guess: str)
    """
    # 1. Check structured country field
    country = job.get("country", {})
    if isinstance(country, dict):
        alpha = country.get("alpha2Code", "") or ""
        if alpha.upper() == "US":
            return True, "US"

        descriptor = (country.get("descriptor", "") or "").lower()
        if descriptor in US_COUNTRY_KEYWORDS:
            return True, "US"

    # 2. Check jobRequisitionLocation
    jrl = job.get("job_requisition_location", {}) or job.get("jobRequisitionLocation", {})
    if isinstance(jrl, dict):
        jrl_country = jrl.get("country", {})
        if isinstance(jrl_country, dict):
            if (jrl_country.get("alpha2Code", "") or "").upper() == "US":
                return True, "US"
            desc = (jrl_country.get("descriptor", "") or "").lower()
            if desc in US_COUNTRY_KEYWORDS:
                return True, "US"

    # 3. Check location text heuristics
    location_text = (job.get("locations_text", "") or job.get("location", "") or "").strip()
    additional = job.get("additional_locations", []) or job.get("additionalLocations", [])

    all_locations = [location_text] + (additional if isinstance(additional, list) else [])
    all_text = " ".join(all_locations).lower()

    # Check for US country keywords in location text
    for kw in US_COUNTRY_KEYWORDS:
        if kw in all_text:
            return True, "US"

    # Check for state codes (2-letter, exact word boundary)
    words = re.findall(r'\b[A-Z]{2}\b', " ".join(all_locations))
    for w in words:
        if w in US_STATE_CODES:
            return True, "US"

    # Check for state names
    for state in US_STATE_NAMES_LOWER:
        if state in all_text:
            return True, "US"

    # Check for major US cities
    for city in MAJOR_US_CITIES:
        if city in all_text:
            return True, "US"

    # 4. Remote handling
    if "remote" in all_text:
        # "Remote - USA", "Remote USA", "Remote - United States" count
        if any(kw in all_text for kw in US_COUNTRY_KEYWORDS):
            return True, "US (Remote)"
        # Bare "Remote" with no country indicator does NOT count
        return False, "Remote (unknown country)"

    return False, "Non-US"
