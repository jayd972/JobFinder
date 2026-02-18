"""Filter for relevant job titles based on configurable target titles."""

# ── Default Target Titles ───────────────────────────────────────────

# These are used as defaults when no custom titles are configured.
DEFAULT_JOB_TITLES = [
    "Machine Learning Engineer",
    "AI Engineer",
    "Applied Machine Learning Engineer",
    "Data Scientist",
    "Applied Data Scientist",
    "Research Scientist in Machine Learning",
    "AI Research Scientist",
    "Machine Learning Researcher",
    "Computer Vision Engineer",
    "NLP Engineer",
    "Generative AI Engineer",
    "LLM Engineer",
    "Deep Learning Engineer",
    "AI Research Engineer",
    "MLOps Engineer",
]


# ── Filter Logic ────────────────────────────────────────────────────

# Words to ignore during matching (too common / not meaningful)
_STOP_WORDS = {
    "in", "of", "and", "the", "a", "an", "or", "for", "to", "at", "by",
    "with", "from", "on", "is", "as", "sr", "jr", "senior", "junior",
    "staff", "principal", "lead", "manager", "director", "head", "vp",
    "i", "ii", "iii", "iv", "v", "1", "2", "3", "4", "5",
}


def _extract_keywords(title):
    """Extract meaningful lowercase keywords from a title string."""
    words = title.lower().split()
    return {w for w in words if w not in _STOP_WORDS and len(w) > 1}


def is_relevant_job(job, target_titles=None):
    """
    Check if a job title matches any of the target job titles.

    Matching logic: A job matches a target title if the job title contains
    ALL of the significant keywords from the target title.

    For example:
        target = "Machine Learning Engineer"
        keywords = {"machine", "learning", "engineer"}

        "Senior Machine Learning Engineer"   → MATCH (contains all keywords)
        "Machine Learning Engineer II"       → MATCH
        "Store Manager in Training"          → NO MATCH
        "Software Engineer"                  → NO MATCH (missing "machine", "learning")

    Args:
        job: dict with at least a "title" key
        target_titles: list of target title strings to match against.
                       If None, uses DEFAULT_JOB_TITLES.
    """
    if target_titles is None:
        target_titles = DEFAULT_JOB_TITLES

    job_title = job.get("title", "")
    if not job_title:
        return False

    job_keywords = _extract_keywords(job_title)

    for target in target_titles:
        target_keywords = _extract_keywords(target)
        if not target_keywords:
            continue
        # Job matches if it contains ALL significant keywords from the target
        if target_keywords.issubset(job_keywords):
            return True

    return False
