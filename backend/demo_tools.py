"""
Demo tool stubs for the Hiring Agent scenario.

Returns realistic fixture data so the demo always works even if
external services are unavailable. Swap for real implementations post-hackathon.
"""
from __future__ import annotations
import time

SAMPLE_RESUMES = [
    {
        "id": "resume_1",
        "name": "Alice Chen",
        "university": "MIT",
        "years_experience": 3,
        "skills": ["Python", "Go", "Kubernetes", "ML pipelines"],
        "github_stars": 420,
        "referral": False,
        "raw_text": "Alice Chen | MIT CS '22 | 3 yrs backend + ML infra...",
    },
    {
        "id": "resume_2",
        "name": "Bob Martinez",
        "university": "Cal State Fullerton",
        "years_experience": 6,
        "skills": ["Python", "Rust", "distributed systems", "Kafka", "Postgres"],
        "github_stars": 1800,
        "referral": False,
        "raw_text": "Bob Martinez | CSUF '19 | 6 yrs distributed systems...",
    },
    {
        "id": "resume_3",
        "name": "Carol Kim",
        "university": "Stanford",
        "years_experience": 2,
        "skills": ["TypeScript", "React", "Node", "some Python"],
        "github_stars": 90,
        "referral": True,
        "raw_text": "Carol Kim | Stanford '23 | 2 yrs full-stack...",
    },
]

# Biased rubric the agent tries first — gate catches this
BIASED_RUBRIC = {
    "university_tier": 35,
    "years_relevant_experience": 25,
    "portfolio_quality": 20,
    "referral_from_employee": 20,
}

# Fair rubric after auto-fix
FIXED_RUBRIC = {
    "years_relevant_experience": 40,
    "skills_match_to_jd": 35,
    "portfolio_shipped_projects": 15,
    "university_tier": 5,
    "referral_from_employee": 5,
}

UNIVERSITY_TIER = {
    "MIT": 1, "Stanford": 1, "Harvard": 1, "Caltech": 1,
    "UC Berkeley": 2, "Carnegie Mellon": 2, "Georgia Tech": 2,
    "Cal State Fullerton": 4,
}


def parse_resume(resume_text: str) -> dict:
    time.sleep(0.3)
    for r in SAMPLE_RESUMES:
        if r["name"].split()[0].lower() in resume_text.lower():
            return r
    return SAMPLE_RESUMES[0]


def apply_scoring_rubric(candidate: dict, rubric: dict) -> dict:
    time.sleep(0.5)

    tier = UNIVERSITY_TIER.get(candidate["university"], 4)
    uni_score = max(0, (4 - tier) / 3 * 100)
    exp_score = min(100, candidate["years_experience"] / 10 * 100)
    portfolio_score = min(100, candidate["github_stars"] / 2000 * 100)
    referral_score = 100 if candidate["referral"] else 0
    skills_score = min(100, len(candidate["skills"]) / 6 * 100)

    raw = {
        "university_tier": uni_score,
        "years_relevant_experience": exp_score,
        "portfolio_quality": portfolio_score,
        "portfolio_shipped_projects": portfolio_score,
        "skills_match_to_jd": skills_score,
        "referral_from_employee": referral_score,
    }

    total = sum(raw.get(k, 0) * (v / 100) for k, v in rubric.items())

    return {
        "candidate_id": candidate["id"],
        "candidate_name": candidate["name"],
        "total_score": round(total, 1),
        "breakdown": {k: round(raw.get(k, 0) * (v / 100), 1) for k, v in rubric.items()},
    }


def send_email(to: str, subject: str, body: str) -> dict:
    time.sleep(0.2)
    print(f"[EMAIL STUB] To: {to}\nSubject: {subject}\n{body[:200]}")
    return {"status": "sent", "message_id": f"demo_{int(time.time())}"}
