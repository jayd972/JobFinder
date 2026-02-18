"""Workday career site crawler — uses the public wday/cxs JSON API."""

import re
import time
import logging
import requests
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, date
from urllib.parse import urlparse
from bs4 import BeautifulSoup

logger = logging.getLogger(__name__)

# ── URL Parsing ─────────────────────────────────────────────────────


def parse_workday_url(url):
    """
    Extract host, tenant, and site from a Workday careers URL.

    Examples:
        https://adobe.wd5.myworkdayjobs.com/external_experienced
        https://adobe.wd5.myworkdayjobs.com/external_experienced?q=foo
        https://adobe.wd5.myworkdayjobs.com/en-US/external_experienced

    Returns: {"host": ..., "tenant": ..., "site": ...} or None
    """
    parsed = urlparse(url.strip())
    host = parsed.hostname
    if not host or "myworkdayjobs.com" not in host:
        return None

    # Tenant is the subdomain prefix before .wd
    tenant_match = re.match(r"^([^.]+)\.wd\d+\.myworkdayjobs\.com$", host)
    if not tenant_match:
        return None
    tenant = tenant_match.group(1)

    # Site is the last path segment (skip language prefixes like /en-US/)
    path_parts = [p for p in parsed.path.strip("/").split("/") if p]
    # Filter out locale segments like en-US
    path_parts = [p for p in path_parts if not re.match(r"^[a-z]{2}-[A-Z]{2}$", p)]
    if not path_parts:
        return None
    site = path_parts[0]

    return {"host": host, "tenant": tenant, "site": site}


# ── API Calls ───────────────────────────────────────────────────────

DEFAULT_HEADERS = {
    "Content-Type": "application/json",
    "Accept": "application/json",
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36",
}

REQUEST_TIMEOUT = 30
RATE_LIMIT_DELAY = 0.3  # seconds between requests (reduced from 1.0 for speed)
MAX_RETRIES = 3
DETAIL_WORKERS = 5      # concurrent detail-fetch threads per company


def _request_with_retry(method, url, **kwargs):
    """Make an HTTP request with retries and exponential backoff."""
    kwargs.setdefault("timeout", REQUEST_TIMEOUT)
    kwargs.setdefault("headers", DEFAULT_HEADERS)

    for attempt in range(MAX_RETRIES):
        try:
            resp = requests.request(method, url, **kwargs)
            resp.raise_for_status()
            return resp.json()
        except requests.exceptions.HTTPError as e:
            if resp.status_code == 429 or resp.status_code >= 500:
                wait = (2 ** attempt) * 2
                logger.warning(f"Retry {attempt+1}/{MAX_RETRIES} for {url} (HTTP {resp.status_code}), waiting {wait}s")
                time.sleep(wait)
                continue
            logger.error(f"HTTP error for {url}: {e}")
            raise
        except requests.exceptions.RequestException as e:
            wait = (2 ** attempt) * 2
            logger.warning(f"Retry {attempt+1}/{MAX_RETRIES} for {url}: {e}, waiting {wait}s")
            time.sleep(wait)
            if attempt == MAX_RETRIES - 1:
                raise
    return None


def fetch_listings(host, tenant, site, search_text="", limit=20, offset=0):
    """
    Fetch job listings from the Workday listing endpoint.

    Returns: {"total": int, "jobPostings": [...]}
    """
    url = f"https://{host}/wday/cxs/{tenant}/{site}/jobs"
    payload = {
        "appliedFacets": {},
        "limit": limit,
        "offset": offset,
        "searchText": search_text,
    }
    return _request_with_retry("POST", url, json=payload)


def fetch_all_listings(host, tenant, site, search_text="", page_size=20, progress_callback=None):
    """
    Fetch ALL job listings with pagination.
    Only returns listings where postedOn == "Posted Today".

    Returns: list of job card dicts that are posted today.
    """
    today_jobs = []
    offset = 0
    total = None
    seen_non_today = 0

    while True:
        data = fetch_listings(host, tenant, site, search_text, limit=page_size, offset=offset)
        if not data or "jobPostings" not in data:
            break

        if total is None:
            total = data["total"]
            logger.info(f"Total jobs on {tenant}/{site}: {total}")

        postings = data["jobPostings"]
        if not postings:
            break

        for job in postings:
            posted = job.get("postedOn", "")
            if posted == "Posted Today":
                today_jobs.append(job)
            else:
                seen_non_today += 1

        if progress_callback:
            progress_callback(offset + len(postings), total)

        offset += page_size

        # Workday returns jobs newest-first by default.
        # Once we see a full page with zero "Posted Today" jobs, we can stop early.
        page_today_count = sum(1 for j in postings if j.get("postedOn") == "Posted Today")
        if page_today_count == 0 and offset > page_size:
            # We've moved past today's jobs
            logger.info(f"No 'Posted Today' on this page (offset={offset}), stopping pagination early.")
            break

        if offset >= total:
            break

        time.sleep(RATE_LIMIT_DELAY)

    logger.info(f"Found {len(today_jobs)} 'Posted Today' jobs for {tenant}/{site}")
    return today_jobs


def fetch_job_detail(host, tenant, site, external_path):
    """
    Fetch full job detail from the Workday detail endpoint.

    Returns: the jobPostingInfo dict with parsed description.
    """
    # external_path looks like: /job/San-Jose/Some-Title_R164668
    path = external_path.lstrip("/")
    url = f"https://{host}/wday/cxs/{tenant}/{site}/{path}"
    data = _request_with_retry("GET", url)
    if not data or "jobPostingInfo" not in data:
        return None

    info = data["jobPostingInfo"]

    # Parse HTML description to plain text
    raw_desc = info.get("jobDescription", "")
    if raw_desc:
        soup = BeautifulSoup(raw_desc, "html.parser")
        info["jd_plain_text"] = soup.get_text(separator="\n", strip=True)
    else:
        info["jd_plain_text"] = ""

    return info


# ── Convenience ─────────────────────────────────────────────────────

def _fetch_one_detail(host, tenant, site, listing, today):
    """Fetch detail for a single listing. Returns enriched dict or None."""
    time.sleep(RATE_LIMIT_DELAY)
    try:
        detail = fetch_job_detail(host, tenant, site, listing["externalPath"])
        if not detail:
            logger.warning(f"Could not fetch detail for {listing['externalPath']}")
            return None

        # Secondary date validation: verify startDate matches today
        start_date_str = detail.get("startDate")
        if start_date_str:
            try:
                start_dt = datetime.fromisoformat(start_date_str)
                if start_dt.date() != today:
                    logger.info(
                        f"Skipping {detail.get('title', '?')} — startDate {start_dt.date()} is not today ({today})"
                    )
                    return None
            except (ValueError, TypeError):
                pass  # If we can't parse, rely on postedOn label

        return {
            "title": detail.get("title", listing.get("title", "")),
            "external_path": listing["externalPath"],
            "locations_text": detail.get("location", listing.get("locationsText", "")),
            "additional_locations": detail.get("additionalLocations", []),
            "posted_label": detail.get("postedOn", listing.get("postedOn", "")),
            "start_date": start_date_str,
            "country": detail.get("country", {}),
            "job_requisition_location": detail.get("jobRequisitionLocation", {}),
            "job_req_id": detail.get("jobReqId", ""),
            "job_posting_id": detail.get("jobPostingId", ""),
            "jd_text": detail.get("jd_plain_text", ""),
            "job_url": detail.get("externalUrl", ""),
            "time_type": detail.get("timeType", ""),
        }
    except Exception as e:
        logger.error(f"Error fetching detail for {listing['externalPath']}: {e}")
        return None


def crawl_company(host, tenant, site, progress_callback=None):
    """
    Full crawl pipeline for one company:
    1. Fetch all "Posted Today" listings
    2. Fetch detail for each (in parallel)
    3. Verify startDate is truly today
    4. Return enriched job dicts

    Returns: list of enriched job dicts
    """
    listings = fetch_all_listings(host, tenant, site, progress_callback=progress_callback)
    enriched = []
    today = date.today()
    total = len(listings)
    done_count = 0

    with ThreadPoolExecutor(max_workers=DETAIL_WORKERS) as executor:
        future_to_idx = {
            executor.submit(_fetch_one_detail, host, tenant, site, listing, today): i
            for i, listing in enumerate(listings)
        }

        for future in as_completed(future_to_idx):
            result = future.result()
            if result is not None:
                enriched.append(result)

            done_count += 1
            if progress_callback:
                progress_callback(done_count, total, phase="details")

    return enriched
