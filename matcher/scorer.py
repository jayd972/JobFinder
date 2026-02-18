"""Job-resume matching scorer."""

import re
import logging
import numpy as np

import torch

logger = logging.getLogger(__name__)

# ── Lazy-load sentence-transformers to avoid startup cost ───────────

_model = None


def _get_model():
    global _model
    if _model is None:
        logger.info("Loading sentence-transformers model (first time may download ~80MB)...")
        from sentence_transformers import SentenceTransformer
        
        device = "cuda" if torch.cuda.is_available() else "cpu"
        logger.info(f"Using device: {device}")
        
        _model = SentenceTransformer("all-MiniLM-L6-v2", device=device)
        logger.info("Model loaded.")
    return _model


# ── Resume Embedding Cache ──────────────────────────────────────────

_resume_cache = {"text": None, "embedding": None}


def encode_resume(resume_text):
    """
    Encode the resume text once and cache it. Returns the embedding vector.
    Subsequent calls with the same text return the cached embedding instantly.
    """
    chunk = resume_text[:2000]
    if _resume_cache["text"] == chunk and _resume_cache["embedding"] is not None:
        return _resume_cache["embedding"]

    model = _get_model()
    embedding = model.encode([chunk])[0]
    _resume_cache["text"] = chunk
    _resume_cache["embedding"] = embedding
    logger.info("Resume embedding cached.")
    return embedding


# ── Title Match ─────────────────────────────────────────────────────

TITLE_KEYWORDS = [
    "machine learning", "ml ", "ml/", "deep learning", "ai ",
    "artificial intelligence", "data scientist", "data science",
    "researcher", "research scientist", "applied scientist",
    "nlp", "natural language", "computer vision", "cv engineer",
    "ml engineer", "mle", "neural", "llm",
]


def title_score(job_title):
    """Score 0-1 based on how many target keywords appear in the job title."""
    title_lower = job_title.lower()
    matches = [kw for kw in TITLE_KEYWORDS if kw in title_lower]
    if not matches:
        return 0.0, matches
    # More matches = higher score, but cap at 1.0
    return min(len(matches) / 3.0, 1.0), matches


# ── Skill Overlap ───────────────────────────────────────────────────

def skill_overlap_score(resume_skills, job_text):
    """Score 0-1 based on overlap between resume skills and job description."""
    if not resume_skills:
        return 0.0, []

    job_lower = job_text.lower()
    matched = [s for s in resume_skills if s in job_lower]

    if not matched:
        return 0.0, matched

    score = len(matched) / len(resume_skills)
    return min(score, 1.0), matched


# ── Semantic Similarity ────────────────────────────────────────────

def semantic_similarity(resume_text, job_text):
    """Cosine similarity between resume and job embeddings."""
    try:
        model = _get_model()
        # Truncate texts to avoid memory issues (model handles ~256 tokens)
        resume_chunk = resume_text[:2000]
        job_chunk = job_text[:2000]

        embeddings = model.encode([resume_chunk, job_chunk])
        cos_sim = np.dot(embeddings[0], embeddings[1]) / (
            np.linalg.norm(embeddings[0]) * np.linalg.norm(embeddings[1])
        )
        return float(max(0, cos_sim))  # Clamp to non-negative
    except Exception as e:
        logger.error(f"Semantic similarity error: {e}")
        return 0.0


# ── Combined Score ──────────────────────────────────────────────────

WEIGHTS = {
    "semantic": 0.4,
    "title": 0.3,
    "skills": 0.3,
}


def _build_result(t_score, t_matches, s_score, s_matches, sem_score):
    """Build a score result dict from individual component scores."""
    combined = (
        WEIGHTS["semantic"] * sem_score
        + WEIGHTS["title"] * t_score
        + WEIGHTS["skills"] * s_score
    )

    all_matched = list(set(t_matches + s_matches))
    why_parts = []
    if t_matches:
        why_parts.append(f"title: {', '.join(t_matches[:3])}")
    if s_matches:
        why_parts.append(f"skills: {', '.join(s_matches[:5])}")
    why = "; ".join(why_parts) if why_parts else "semantic similarity only"

    return {
        "score": round(combined, 4),
        "title_score": round(t_score, 4),
        "skill_score": round(s_score, 4),
        "semantic_score": round(sem_score, 4),
        "matched_keywords": all_matched,
        "title_matches": t_matches,
        "why": why,
    }


def score_job(job_title, job_description, resume_text, resume_skills):
    """
    Compute combined match score for a job against a resume.

    Returns: {
        "score": float (0-1),
        "title_score": float,
        "skill_score": float,
        "semantic_score": float,
        "matched_keywords": list[str],
        "title_matches": list[str],
        "why": str  # human-readable summary
    }
    """
    job_text = f"{job_title}\n{job_description}"

    t_score, t_matches = title_score(job_title)
    s_score, s_matches = skill_overlap_score(resume_skills, job_text)
    sem_score = semantic_similarity(resume_text, job_text)

    return _build_result(t_score, t_matches, s_score, s_matches, sem_score)


# ── Batch Scoring ───────────────────────────────────────────────────

BATCH_SIZE = 32  # encode this many job texts at once


def score_jobs_batch(jobs, resume_text, resume_skills):
    """
    Score multiple jobs against a resume in batch.
    Much faster than calling score_job() in a loop because:
    1. Resume embedding is encoded once and cached
    2. Job text embeddings are batch-encoded

    Args:
        jobs: list of dicts with "title" and "jd_text" keys
        resume_text: the resume plain text
        resume_skills: list of skill strings

    Returns: list of score result dicts (same format as score_job)
    """
    if not jobs:
        return []

    try:
        model = _get_model()
        resume_emb = encode_resume(resume_text)
        resume_norm = np.linalg.norm(resume_emb)
    except Exception as e:
        logger.error(f"Batch scoring model error: {e}")
        # Fallback: score individually without semantic
        results = []
        for job in jobs:
            job_text = f"{job['title']}\n{job.get('jd_text', '')}"
            t_score, t_matches = title_score(job["title"])
            s_score, s_matches = skill_overlap_score(resume_skills, job_text)
            results.append(_build_result(t_score, t_matches, s_score, s_matches, 0.0))
        return results

    # Pre-compute title and skill scores (cheap, no model needed)
    title_results = []
    skill_results = []
    job_texts = []
    for job in jobs:
        job_text = f"{job['title']}\n{job.get('jd_text', '')}"
        job_texts.append(job_text[:2000])
        title_results.append(title_score(job["title"]))
        skill_results.append(skill_overlap_score(resume_skills, job_text))

    # Batch encode all job texts
    all_sem_scores = []
    for i in range(0, len(job_texts), BATCH_SIZE):
        batch = job_texts[i : i + BATCH_SIZE]
        try:
            job_embeddings = model.encode(batch, show_progress_bar=False)
            for emb in job_embeddings:
                cos_sim = np.dot(resume_emb, emb) / (resume_norm * np.linalg.norm(emb))
                all_sem_scores.append(float(max(0, cos_sim)))
        except Exception as e:
            logger.error(f"Batch encode error at offset {i}: {e}")
            all_sem_scores.extend([0.0] * len(batch))

    # Assemble results
    results = []
    for idx in range(len(jobs)):
        t_score, t_matches = title_results[idx]
        s_score, s_matches = skill_results[idx]
        sem_score = all_sem_scores[idx] if idx < len(all_sem_scores) else 0.0
        results.append(_build_result(t_score, t_matches, s_score, s_matches, sem_score))

    return results
