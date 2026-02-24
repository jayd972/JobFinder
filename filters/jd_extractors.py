"""Extract experience requirements and visa sponsorship status from job descriptions."""

import re


def extract_experience_years(jd_text):
    """
    Extract the years of experience required from a job description.
    
    Returns a string like "3+", "5-7", "2" or "--" if not found.
    """
    if not jd_text:
        return "--"

    text = jd_text.lower()

    # Patterns ordered from most specific to least specific
    patterns = [
        # "3-5 years of experience"
        r'(\d{1,2})\s*[-–to]+\s*(\d{1,2})\+?\s*(?:years?|yrs?)[\s\w]*(?:experience|exp)',
        # "5+ years of experience"
        r'(\d{1,2})\+?\s*(?:years?|yrs?)[\s\w]*(?:experience|exp)',
        # "minimum 3 years" / "at least 3 years"
        r'(?:minimum|at\s+least|min\.?)\s*(?:of\s+)?(\d{1,2})\+?\s*(?:years?|yrs?)',
        # "3+ years in" / "3+ years of"
        r'(\d{1,2})\+?\s*(?:years?|yrs?)\s+(?:of|in|working)',
        # "experience: 5 years" / "experience of 5 years"
        r'experience[\s:of]*(\d{1,2})\+?\s*(?:years?|yrs?)',
    ]

    for pattern in patterns:
        match = re.search(pattern, text)
        if match:
            groups = match.groups()
            if len(groups) == 2:
                return f"{groups[0]}-{groups[1]}"
            else:
                return f"{groups[0]}+"
    
    return "--"


def extract_visa_sponsorship(jd_text):
    """
    Determine visa sponsorship availability from a job description.
    
    Returns:
        "Unlikely" - if JD explicitly says no sponsorship or requires US person
        "Likely"   - if JD mentions sponsorship in a positive context
        "Unknown"  - if nothing is mentioned
    """
    if not jd_text:
        return "Unknown"
    
    text = jd_text.lower()

    # Negative patterns (no sponsorship available)
    no_sponsorship_patterns = [
        r'(?:not|no|cannot|can\'t|won\'t|will\s+not|unable\s+to)\s+(?:\w+\s+)?sponsor',
        r'(?:not|no)\s+(?:\w+\s+)?(?:visa|work)\s+sponsor',
        r'sponsorship\s+(?:is\s+)?(?:not|unavailable|not available)',
        r'without\s+(?:\w+\s+)?sponsor',
        r'must\s+be\s+(?:a\s+)?(?:u\.?s\.?\s+(?:citizen|person|national)|united\s+states\s+(?:citizen|person))',
        r'u\.?s\.?\s+(?:citizen(?:ship)?|person)\s+(?:is\s+)?required',
        r'must\s+(?:have|possess|hold)\s+(?:a\s+)?(?:u\.?s\.?\s+)?(?:citizenship|permanent\s+residen)',
        r'authorized\s+to\s+work\s+in\s+the\s+(?:u\.?s\.?|united\s+states)\s+without\s+(?:\w+\s+)?sponsor',
        r'no\s+(?:immigration|visa)\s+(?:sponsorship|assistance)',
        r'must\s+(?:be\s+)?(?:legally\s+)?authorized\s+to\s+work.*without.*sponsor',
    ]

    for pattern in no_sponsorship_patterns:
        if re.search(pattern, text):
            return "Unlikely"

    # Positive patterns (sponsorship available)
    yes_sponsorship_patterns = [
        r'(?:will|can|may|do)\s+(?:\w+\s+)?sponsor',
        r'sponsorship\s+(?:is\s+)?(?:available|offered|provided)',
        r'visa\s+sponsorship\s+(?:is\s+)?(?:available|offered|provided)',
        r'open\s+to\s+sponsor',
    ]

    for pattern in yes_sponsorship_patterns:
        if re.search(pattern, text):
            return "Likely"

    return "Unknown"
