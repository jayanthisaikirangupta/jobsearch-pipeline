"""Build the Elliptic Full Stack Engineer resume from the agreed content.

Hand-authored content (not LLM-tailored) - feeds the existing one-page
renderer in jobsearch.tailor.writer so the output uses the same Cambria
layout as Sai_Kiran_Avaloq_Angular_Resume.docx.
"""
from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace

import yaml

# Make src/ importable when run from repo root.
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from jobsearch.tailor import writer  # noqa: E402
from jobsearch.tailor.writer import render  # noqa: E402

# Hand-authored content runs longer than tailor JSON; widen the safety caps so
# the renderer doesn't truncate mid-sentence.
writer.ONE_PAGE["max_profile_chars"] = 700
writer.ONE_PAGE["max_bullet_chars"] = 280


def load_candidate() -> SimpleNamespace:
    profile_path = ROOT / "config" / "profile.yaml"
    data = yaml.safe_load(profile_path.read_text(encoding="utf-8"))["candidate"]
    return SimpleNamespace(
        full_name=data["full_name"],
        email=data["email"],
        phone=data["phone"],
        location=data["location"],
        linkedin=data.get("linkedin"),
        linkedin_url=data.get("linkedin_url"),
        github=data.get("github"),
        github_url=data.get("github_url"),
        tagline=data.get("tagline"),
    )


TAILORED: dict = {
    "format_choice": "one_page",
    "headline": "Full Stack Engineer  -  TypeScript, React, Node.js",
    "profile": (
        "Full stack engineer with 5+ years building and shipping production "
        "features end to end. At Kuehne+Nagel I work across a React / "
        "TypeScript front end and a Java back end on a regulated travel and "
        "expense platform, owning features from query to UI. Use AI coding "
        "assistants (Claude Code, Cursor) every day and have built "
        "agent-driven tools on top of them. Three years on the Lloyds "
        "Banking Group account through TCS taught me what auditable, "
        "regulated-finance software has to look like in practice."
    ),
    "core_skills": [
        {
            "category": "Frontend",
            "items": (
                "TypeScript, React, Redux, Next.js, RxJS, HTML / CSS, "
                "responsive UI, performance tuning, component-driven "
                "design."
            ),
        },
        {
            "category": "Backend",
            "items": (
                "Node.js, NestJS, Prisma; Java 17, Spring Boot, Hibernate, "
                "Quarkus; Python (FastAPI, Flask); REST APIs, microservices, "
                "Kafka."
            ),
        },
        {
            "category": "Data",
            "items": (
                "PostgreSQL, MongoDB, Oracle, SQL query design and "
                "optimisation; integration with data-engineering pipelines."
            ),
        },
        {
            "category": "Cloud & DevOps",
            "items": (
                "AWS (ECS, RDS, Lambda, API Gateway, CloudWatch, IAM, "
                "Bedrock); Docker, Kubernetes, Terraform basics, CI/CD; "
                "Datadog-style observability."
            ),
        },
        {
            "category": "AI-assisted dev",
            "items": (
                "Daily use of Claude Code and Cursor; Anthropic Claude API, "
                "Model Context Protocol (MCP) servers, agentic workflows "
                "with human-in-the-loop checkpoints."
            ),
        },
        {
            "category": "Ways of working",
            "items": (
                "Code review, testing, regulated-finance background, "
                "comfortable shaping work from a vague problem to a "
                "shipped feature."
            ),
        },
    ],
    "experience": [
        {
            "title": "Analyst Programmer",
            "company": "Kuehne+Nagel UK",
            "subtitle": "Travel & Expense Platform",
            "location": "Milton Keynes, UK",
            "dates": "January 2025 - Present",
            "bullets": [
                (
                    "Ship full-stack features on a regulated travel and "
                    "expense platform: React + TypeScript front end, Java / "
                    "Spring Boot APIs, MongoDB and Oracle behind them. Pick "
                    "up tickets across the stack rather than staying on one "
                    "side."
                ),
                (
                    "Front end: fixed a lazy-loading race that was firing "
                    "132 redundant network requests per page, brought it "
                    "down to 9. Tightened component data flow and SQL on "
                    "the slow paths users complained about."
                ),
                (
                    "Back end: refactored core transaction flows in Spring "
                    "Boot / Hibernate and brought latency down around 30 "
                    "percent. Added retries, idempotency, and structured "
                    "logging on the hot paths."
                ),
                (
                    "Built an async OCR + LLM extraction pipeline for "
                    "receipts and expenses, from PoC to production: schema-"
                    "gated outputs, retries, observability, and ground-"
                    "truth accuracy checks before any prompt change ships. "
                    "Integrated MCP servers into the team's Claude "
                    "assistants so they reason over real bug-tracker, IDE, "
                    "and MongoDB context."
                ),
            ],
        },
        {
            "title": "Innovation Project Assistant",
            "company": "University of Leicester",
            "subtitle": "Requirement-Gathering Web App",
            "location": "Leicester, UK",
            "dates": "May 2023 - September 2023",
            "bullets": [
                (
                    "Built a Python (Flask) + MySQL web app that turned "
                    "consultation transcripts into structured requirements "
                    "via the OpenAI API, with validation prompts so the "
                    "output stayed reviewable by a human."
                ),
            ],
        },
        {
            "title": "System Engineer",
            "company": "Tata Consultancy Services - Lloyds Banking Group",
            "location": "India",
            "dates": "August 2019 - December 2022",
            "bullets": [
                (
                    "Three years on the Lloyds Banking Group account, in "
                    "regulated financial services. Owned Test Data "
                    "Management across Oracle and mainframes, processing "
                    "500-600 accounts per request with full validation. "
                    "Automated 30-40 manual workflows via scripting, "
                    "earning the Special Initiator Award."
                ),
                (
                    "Built full-stack features on a self-service data-"
                    "provisioning portal in Spring Boot, Java, and Oracle, "
                    "speeding up feature rollout around 4x through reusable "
                    "components. Mentored a 25-engineer team through a "
                    "critical platform transition."
                ),
            ],
        },
    ],
    "projects": [
        {
            "name": "PetGearHub  -  petgearhub.co.uk",
            "tech_stack": (
                "Next.js, React, TypeScript, NestJS, Prisma, PostgreSQL, "
                "Vercel, AWS ECS, AWS RDS"
            ),
            "summary": (
                "Side project I built and host under my own domain. "
                "React / Next.js front end on Vercel, NestJS API on AWS "
                "ECS with Prisma against PostgreSQL on RDS, JWT-gated "
                "admin panel. Built alongside Claude Code."
            ),
        },
        {
            "name": "Agentic Job-Search Pipeline",
            "tech_stack": (
                "Python, Anthropic Claude API, n8n, public job APIs, "
                "personal build"
            ),
            "summary": (
                "Multi-step agent that ingests job postings, scores them "
                "against my profile via Claude, drafts tailored "
                "applications, and logs decisions. Tool use, conditional "
                "routing, persistence."
            ),
        },
    ],
    "education": [
        {
            "degree": "MSc Cloud Computing",
            "institution": "University of Leicester, UK",
            "dates": "January 2023 - July 2024",
        },
        {
            "degree": "BSc Computer Science",
            "institution": "Annamacharya Institute of Technology",
            "dates": "April 2015 - June 2019",
        },
    ],
    "certifications": (
        "Microsoft Azure Fundamentals (AZ-900)  -  Microsoft Azure Data "
        "Fundamentals (DP-900)"
    ),
}


def main() -> None:
    candidate = load_candidate()
    out_path = ROOT / "output" / "resumes" / "Sai_Jayanthi_Elliptic_Full_Stack.docx"
    rendered = render(TAILORED, candidate, out_path)
    print(f"Wrote: {rendered}")


if __name__ == "__main__":
    main()
