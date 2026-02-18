"""JobFinder MVP — Flask Application."""

import os
import json
import logging
import threading
import tempfile
from datetime import datetime
from flask import Flask, request, jsonify, render_template, send_file

import database as db
from crawler.workday import parse_workday_url, crawl_company
from filters.keywords import is_relevant_job, DEFAULT_JOB_TITLES
from filters.posted_today import is_posted_today
from filters.usa import is_usa_job
from matcher.resume_parser import extract_resume_text, parse_sections, extract_skills
from matcher.scorer import score_job, score_jobs_batch
from utils.spreadsheet import import_companies, export_results

# ── App Setup ───────────────────────────────────────────────────────

app = Flask(__name__)
app.config["MAX_CONTENT_LENGTH"] = 16 * 1024 * 1024  # 16 MB max upload

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)

UPLOAD_DIR = os.path.join(os.path.dirname(__file__), "uploads")
EXPORT_DIR = os.path.join(os.path.dirname(__file__), "exports")
os.makedirs(UPLOAD_DIR, exist_ok=True)
os.makedirs(EXPORT_DIR, exist_ok=True)

# Track active runs for progress reporting
_active_runs = {}  # run_id -> progress dict


# ── Page Routes ─────────────────────────────────────────────────────

@app.route("/")
def index():
    return render_template("index.html")


# ── API: Upload Companies ──────────────────────────────────────────

@app.route("/api/upload-companies", methods=["POST"])
def upload_companies():
    if "file" not in request.files:
        return jsonify({"error": "No file provided"}), 400

    f = request.files["file"]
    if not f.filename or not f.filename.endswith((".xlsx", ".xls")):
        return jsonify({"error": "File must be .xlsx"}), 400

    filepath = os.path.join(UPLOAD_DIR, "companies.xlsx")
    f.save(filepath)

    try:
        companies = import_companies(filepath)
        db.clear_companies()
        count = db.upsert_companies(companies)
        return jsonify({
            "success": True,
            "count": count,
            "companies": companies,
        })
    except Exception as e:
        logger.error(f"Company import error: {e}")
        return jsonify({"error": str(e)}), 400


@app.route("/api/companies", methods=["GET"])
def get_companies():
    companies = db.get_all_companies()
    return jsonify({"companies": companies})


# ── API: Upload Resume ─────────────────────────────────────────────

@app.route("/api/upload-resume", methods=["POST"])
def upload_resume():
    if "file" not in request.files:
        return jsonify({"error": "No file provided"}), 400

    f = request.files["file"]
    if not f.filename or not f.filename.endswith(".pdf"):
        return jsonify({"error": "File must be .pdf"}), 400

    filepath = os.path.join(UPLOAD_DIR, "resume.pdf")
    f.save(filepath)

    try:
        text = extract_resume_text(filepath)
        sections = parse_sections(text)
        skills = extract_skills(text, sections)
        db.save_resume(text, sections, skills)

        return jsonify({
            "success": True,
            "text_length": len(text),
            "sections": list(sections.keys()),
            "skills": skills,
        })
    except Exception as e:
        logger.error(f"Resume parse error: {e}")
        return jsonify({"error": str(e)}), 400


@app.route("/api/resume", methods=["GET"])
def get_resume():
    resume = db.get_resume()
    if resume:
        return jsonify({"resume": resume})
    return jsonify({"resume": None})


# ── API: Job Title Configuration ───────────────────────────────────

JOB_TITLES_SETTING_KEY = "job_titles"


@app.route("/api/job-titles", methods=["GET"])
def get_job_titles():
    raw = db.get_setting(JOB_TITLES_SETTING_KEY)
    if raw:
        try:
            titles = json.loads(raw)
        except (json.JSONDecodeError, TypeError):
            titles = DEFAULT_JOB_TITLES
    else:
        titles = DEFAULT_JOB_TITLES
    return jsonify({"titles": titles})


@app.route("/api/job-titles", methods=["POST"])
def save_job_titles():
    data = request.get_json()
    if not data or "titles" not in data:
        return jsonify({"error": "Missing 'titles' field"}), 400

    titles = data["titles"]
    if not isinstance(titles, list):
        return jsonify({"error": "'titles' must be a list"}), 400

    # Filter out empty strings
    titles = [t.strip() for t in titles if t.strip()]

    db.save_setting(JOB_TITLES_SETTING_KEY, json.dumps(titles))
    return jsonify({"success": True, "count": len(titles), "titles": titles})


# ── API: Run Scanner ────────────────────────────────────────────────

def _scan_one_company(company, run_id, target_titles, resume_text, resume_skills):
    """Scan a single company: crawl, filter, batch-score, batch-write. Returns (found, returned)."""
    company_name = company["company_name"]
    url = company["workday_url"]

    _active_runs[run_id]["phase"] = f"Scanning {company_name}"

    try:
        parsed = parse_workday_url(url)
        if not parsed:
            error_msg = f"{company_name}: Invalid Workday URL: {url}"
            logger.warning(error_msg)
            _active_runs[run_id]["errors"].append(error_msg)
            db.update_company_run_status(company["company_id"], "invalid_url")
            return 0, 0

        host, tenant, site = parsed["host"], parsed["tenant"], parsed["site"]

        def progress_cb(done, total, phase="listings"):
            _active_runs[run_id]["phase"] = f"{company_name}: {phase} {done}/{total}"

        # Crawl company (parallel detail fetching inside)
        jobs = crawl_company(host, tenant, site, progress_callback=progress_cb)
        found = len(jobs)

        _active_runs[run_id]["jobs_found"] += found
        _active_runs[run_id]["phase"] = f"{company_name}: Filtering {found} jobs"

        # Apply filters (cheap, no model needed)
        filtered_jobs = []
        date_rejected = 0
        title_rejected = 0
        usa_rejected = 0
        for job in jobs:
            if not is_posted_today(job):
                date_rejected += 1
                continue
            if not is_relevant_job(job, target_titles=target_titles):
                title_rejected += 1
                continue
            usa, country_guess = is_usa_job(job)
            if not usa:
                usa_rejected += 1
                continue
            job["_country_guess"] = country_guess
            filtered_jobs.append(job)

        logger.info(
            f"{company_name}: {len(jobs)} crawled -> "
            f"{date_rejected} date-rejected, {title_rejected} title-rejected, "
            f"{usa_rejected} location-rejected, {len(filtered_jobs)} passed all filters"
        )

        if not filtered_jobs:
            db.update_company_run_status(company["company_id"], "success")
            return found, 0

        _active_runs[run_id]["phase"] = f"{company_name}: Scoring {len(filtered_jobs)} jobs"

        # Batch score all filtered jobs at once
        score_inputs = [{"title": j["title"], "jd_text": j.get("jd_text", "")} for j in filtered_jobs]
        score_results = score_jobs_batch(score_inputs, resume_text, resume_skills)

        # Build job records for batch DB write
        job_records = []
        for job, result in zip(filtered_jobs, score_results):
            req_id = job.get("job_req_id", "") or job.get("job_posting_id", "")
            job_key = f"{company['company_id']}_{req_id}"

            locs = [job.get("locations_text", "")]
            additional = job.get("additional_locations", [])
            if additional:
                locs.extend(additional)
            locations_str = ", ".join([l for l in locs if l])

            job_records.append({
                "job_key": job_key,
                "company_id": company["company_id"],
                "title": job["title"],
                "locations_text": locations_str,
                "country_guess": job["_country_guess"],
                "posted_label": job.get("posted_label", "Posted Today"),
                "job_url": job.get("job_url", ""),
                "jd_text": job.get("jd_text", ""),
                "match_score": result["score"],
                "matched_keywords": result["why"],
                "run_id": run_id,
            })

        # Batch write to DB
        db.upsert_jobs_batch(job_records)

        returned = len(job_records)
        _active_runs[run_id]["jobs_returned"] += returned

        db.update_company_run_status(company["company_id"], "success")
        return found, returned

    except Exception as e:
        error_msg = f"{company_name}: {str(e)}"
        logger.error(error_msg, exc_info=True)
        _active_runs[run_id]["errors"].append(error_msg)
        db.update_company_run_status(company["company_id"], f"error: {str(e)[:100]}")
        return 0, 0


def _run_scanner(run_id):
    """Background thread: scan all companies concurrently."""
    global _active_runs
    _active_runs[run_id] = {
        "status": "running",
        "current_company": "",
        "companies_done": 0,
        "total_companies": 0,
        "jobs_found": 0,
        "jobs_returned": 0,
        "errors": [],
        "phase": "starting",
    }

    try:
        companies = db.get_all_companies()
        resume = db.get_resume()

        if not companies:
            _active_runs[run_id]["status"] = "error"
            _active_runs[run_id]["phase"] = "No companies loaded"
            db.update_run(run_id, status="error", error_log="No companies loaded",
                         finished_at=datetime.utcnow().isoformat())
            return

        if not resume:
            _active_runs[run_id]["status"] = "error"
            _active_runs[run_id]["phase"] = "No resume uploaded"
            db.update_run(run_id, status="error", error_log="No resume uploaded",
                          finished_at=datetime.utcnow().isoformat())
            return

        # Load configurable job titles
        raw_titles = db.get_setting(JOB_TITLES_SETTING_KEY)
        if raw_titles:
            try:
                target_titles = json.loads(raw_titles)
            except (json.JSONDecodeError, TypeError):
                target_titles = DEFAULT_JOB_TITLES
        else:
            target_titles = DEFAULT_JOB_TITLES

        resume_text = resume["resume_text"]
        resume_skills = resume["skills_list"]
        total_companies = len(companies)
        _active_runs[run_id]["total_companies"] = total_companies

        total_found = 0
        total_returned = 0

        # Scan companies sequentially (crawl parallelism is within each company)
        for ci, company in enumerate(companies):
            _active_runs[run_id]["current_company"] = company["company_name"]
            found, returned = _scan_one_company(
                company, run_id, target_titles, resume_text, resume_skills
            )
            total_found += found
            total_returned += returned
            _active_runs[run_id]["companies_done"] = ci + 1

        # Finalize
        _active_runs[run_id]["status"] = "done"
        _active_runs[run_id]["phase"] = "Complete"
        db.update_run(
            run_id,
            status="done",
            finished_at=datetime.utcnow().isoformat(),
            total_companies=total_companies,
            total_jobs_found=total_found,
            total_jobs_returned=total_returned,
            error_log=json.dumps(_active_runs[run_id]["errors"]) if _active_runs[run_id]["errors"] else None,
        )
        logger.info(f"Run {run_id} complete: {total_returned} jobs matched from {total_found} found")

    except Exception as e:
        logger.error(f"Run {run_id} fatal error: {e}", exc_info=True)
        _active_runs[run_id]["status"] = "error"
        _active_runs[run_id]["phase"] = str(e)
        db.update_run(run_id, status="error", error_log=str(e),
                     finished_at=datetime.utcnow().isoformat())


@app.route("/api/run", methods=["POST"])
def start_run():
    # Check prerequisites
    companies = db.get_all_companies()
    if not companies:
        return jsonify({"error": "No companies loaded. Upload a spreadsheet first."}), 400

    resume = db.get_resume()
    if not resume:
        return jsonify({"error": "No resume uploaded. Upload your resume first."}), 400

    run_id = db.create_run()
    db.update_run(run_id, total_companies=len(companies))

    # Start background thread
    thread = threading.Thread(target=_run_scanner, args=(run_id,), daemon=True)
    thread.start()

    return jsonify({"run_id": run_id, "status": "started"})


@app.route("/api/run-status/<run_id>", methods=["GET"])
def run_status(run_id):
    # Try active run first for live progress
    if run_id in _active_runs:
        progress = _active_runs[run_id]
        return jsonify({"run_id": run_id, **progress})

    # Fall back to DB
    run = db.get_run(run_id)
    if run:
        return jsonify(run)

    return jsonify({"error": "Run not found"}), 404


@app.route("/api/latest-run", methods=["GET"])
def latest_run():
    run = db.get_latest_run()
    return jsonify({"run": run})


# ── API: Results ────────────────────────────────────────────────────

@app.route("/api/results", methods=["GET"])
def get_results():
    run_id = request.args.get("run_id")
    company = request.args.get("company")
    keyword = request.args.get("keyword")
    min_score = request.args.get("min_score")
    location = request.args.get("location")

    results = db.get_results(
        run_id=run_id,
        company=company,
        keyword=keyword,
        min_score=float(min_score) if min_score else None,
        location=location,
    )
    return jsonify({"results": results, "count": len(results)})


# ── API: Export ─────────────────────────────────────────────────────

@app.route("/api/export", methods=["GET"])
def export():
    run_id = request.args.get("run_id")
    company = request.args.get("company")
    keyword = request.args.get("keyword")
    min_score = request.args.get("min_score")
    location = request.args.get("location")

    results = db.get_results(
        run_id=run_id,
        company=company,
        keyword=keyword,
        min_score=float(min_score) if min_score else None,
        location=location,
    )

    filename = f"jobfinder_results_{datetime.now().strftime('%Y%m%d_%H%M%S')}.xlsx"
    filepath = os.path.join(EXPORT_DIR, filename)
    export_results(results, filepath)

    return send_file(filepath, as_attachment=True, download_name=filename)


# ── Main ────────────────────────────────────────────────────────────

if __name__ == "__main__":
    db.init_db()
    port = int(os.environ.get("PORT", 5000))
    app.run(debug=False, host="0.0.0.0", port=port)
