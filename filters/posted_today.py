"""Filter for 'Posted Today' jobs — strict calendar-date check."""

from datetime import datetime, date


def is_posted_today(job):
    """
    Check if a job was posted today. Strictly enforced.

    Primary rule: postedOn == "Posted Today" (exact match).
    Backup rule: if postedOn is missing, check startDate matches today's date.
    If neither is available, REJECT the job.
    """
    posted_label = job.get("posted_label", "") or job.get("postedOn", "")

    # Primary check: exact string match
    if posted_label == "Posted Today":
        return True

    # If label is present but not "Posted Today", it's not today
    if posted_label:
        return False

    # Backup: strict calendar-date check on startDate
    start_date = job.get("start_date") or job.get("startDate")
    if start_date:
        try:
            posted_dt = datetime.fromisoformat(start_date)
            today = date.today()
            return posted_dt.date() == today
        except (ValueError, TypeError):
            pass

    # No date info available — reject
    return False
