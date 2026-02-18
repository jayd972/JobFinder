"""Resume PDF parser — extracts text and splits into sections."""

import re
import logging
from pdfminer.high_level import extract_text

logger = logging.getLogger(__name__)

# Section headings commonly found in resumes
SECTION_PATTERNS = [
    r"(?i)^(technical\s+skills?|skills?|core\s+competenc)",
    r"(?i)^(experience|work\s+experience|professional\s+experience)",
    r"(?i)^(education|academic)",
    r"(?i)^(projects?|personal\s+projects?|key\s+projects?)",
    r"(?i)^(certifications?|certificates?)",
    r"(?i)^(publications?|papers?)",
    r"(?i)^(summary|objective|profile|about)",
]


def extract_resume_text(pdf_path):
    """Extract raw text from a PDF resume."""
    try:
        text = extract_text(pdf_path)
        return text.strip()
    except Exception as e:
        logger.error(f"Failed to extract PDF text: {e}")
        raise


def parse_sections(text):
    """
    Split resume text into sections based on common headings.

    Returns: dict like {"skills": "...", "experience": "...", ...}
    """
    lines = text.split("\n")
    sections = {}
    current_section = "header"
    current_lines = []

    section_names = {
        "skill": "skills",
        "technical skill": "skills",
        "core competen": "skills",
        "experience": "experience",
        "work experience": "experience",
        "professional experience": "experience",
        "education": "education",
        "academic": "education",
        "project": "projects",
        "personal project": "projects",
        "key project": "projects",
        "certification": "certifications",
        "certificate": "certifications",
        "publication": "publications",
        "paper": "publications",
        "summary": "summary",
        "objective": "summary",
        "profile": "summary",
        "about": "summary",
    }

    for line in lines:
        stripped = line.strip()
        if not stripped:
            current_lines.append("")
            continue

        # Check if this line is a section heading
        is_heading = False
        for pattern in SECTION_PATTERNS:
            if re.match(pattern, stripped):
                # Save previous section
                if current_lines:
                    content = "\n".join(current_lines).strip()
                    if content:
                        sections[current_section] = content

                # Determine normalized section name
                lower = stripped.lower()
                current_section = "other"
                for key, name in section_names.items():
                    if lower.startswith(key):
                        current_section = name
                        break
                current_lines = []
                is_heading = True
                break

        if not is_heading:
            current_lines.append(stripped)

    # Save last section
    if current_lines:
        content = "\n".join(current_lines).strip()
        if content:
            sections[current_section] = content

    return sections


def extract_skills(text, sections=None):
    """
    Extract skill keywords from resume text.
    Uses the skills section if available, otherwise scans the full text.

    Returns: list of skill strings
    """
    # Known skills to look for
    KNOWN_SKILLS = [
        "python", "java", "sql", "matlab", "r", "c++", "javascript",
        "machine learning", "deep learning", "nlp", "natural language processing",
        "computer vision", "reinforcement learning", "llm", "llms",
        "rag", "retrieval augmented generation",
        "pytorch", "tensorflow", "scikit-learn", "keras", "transformers",
        "docker", "kubernetes", "aws", "gcp", "azure",
        "flask", "django", "fastapi",
        "tableau", "power bi",
        "git", "github",
        "pandas", "numpy", "scipy",
        "signal processing", "time-series", "time series",
        "cnn", "lstm", "rnn", "bert", "gpt", "transformer",
        "xgboost", "random forest",
        "data science", "data engineering", "data analysis",
        "api", "rest", "microservices",
    ]

    search_text = ""
    if sections and "skills" in sections:
        search_text = sections["skills"].lower()
    else:
        search_text = text.lower()

    found = []
    for skill in KNOWN_SKILLS:
        if skill in search_text:
            found.append(skill)

    return sorted(set(found))
