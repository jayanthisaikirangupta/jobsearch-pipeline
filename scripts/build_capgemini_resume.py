"""Build the Capgemini Full Stack (React + Java) resume.

Capgemini is hiring through their Financial Services SBU in Glasgow. The
emphasis is React front-end + Java back-end, with banking / FS domain a real
plus. Lean into the Lloyds Banking Group history at TCS and the day-to-day
React + Java + MongoDB / Oracle work at K+N.

Hand-authored content (not LLM-tailored) - feeds the existing one-page
renderer in jobsearch.tailor.writer.
"""
from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace

import yaml

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from jobsearch.tailor import writer  # noqa: E402
from jobsearch.tailor.writer import render  # noqa: E402

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
    "headline": "Full Stack Engineer  -  ReactJS + Java / Spring Boot",
    "profile": (
        "Full stack engineer with 6+ years building scalable, secure web "
        "applications end to end. Day-to-day stack at Kuehne+Nagel is "
        "ReactJS / TypeScript on the front end and Java 17 / Spring Boot on "
        "the back end, against Oracle and MongoDB - the same shape as this "
        "role. Three years on the Lloyds Banking Group account through TCS "
        "gave me direct UK financial-services experience: auditable code, "
        "regulated change control, and the constraints banking clients "
        "actually impose."
    ),
    "core_skills": [
        {
            "category": "Frontend",
            "items": (
                "ReactJS (Hooks, Components, Context API, Redux), JavaScript "
                "ES6+, TypeScript, HTML5, CSS3, responsive design, cross-"
                "browser compatibility, Next.js."
            ),
        },
        {
            "category": "Backend",
            "items": (
                "Java 17, Spring Boot, Spring MVC, Hibernate, Quarkus; "
                "RESTful API design, asynchronous processing, backend design "
                "patterns; Node.js / NestJS."
            ),
        },
        {
            "category": "Build, test & version control",
            "items": (
                "Webpack, Babel, Vite, npm; Jest, React Testing Library, "
                "JUnit, Mockito; Git, GitLab, JIRA, IntelliJ IDEA."
            ),
        },
        {
            "category": "Data & integration",
            "items": (
                "Oracle, PostgreSQL, MongoDB; SQL query design and tuning; "
                "Kafka pub/sub; integrating with third-party APIs and "
                "enterprise systems."
            ),
        },
        {
            "category": "Cloud & DevOps",
            "items": (
                "AWS (Lambda, Step Functions, IAM, ECS, RDS, API Gateway, "
                "CloudWatch, Bedrock); Docker, Kubernetes, CI/CD pipelines."
            ),
        },
        {
            "category": "Financial services",
            "items": (
                "3 years on Lloyds Banking Group via TCS - regulated change, "
                "test data management across Oracle and mainframes, "
                "auditable code, banking workflows."
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
                    "expense platform: ReactJS + TypeScript front end "
                    "(Hooks, Redux, Context API), Java 17 / Spring Boot "
                    "REST APIs, Oracle and MongoDB behind them. Move across "
                    "the stack rather than staying on one side."
                ),
                (
                    "Front end: built reusable React components and tuned "
                    "data flow; fixed a lazy-loading race firing 132 "
                    "redundant network requests per page, brought it to 9. "
                    "Webpack and Vite-based build tooling, Jest + React "
                    "Testing Library on changed components, cross-browser "
                    "and responsive across desktop and mobile."
                ),
                (
                    "Back end: refactored core transaction flows in Spring "
                    "Boot / Hibernate against Oracle, cutting latency around "
                    "30 percent. Added retries, idempotency, and structured "
                    "logging; designed REST endpoints with clear contracts "
                    "and async processing where it mattered."
                ),
                (
                    "Built an async OCR + LLM extraction pipeline for "
                    "receipts and expenses, from PoC to production: schema-"
                    "gated outputs, retries, observability, and ground-truth "
                    "accuracy checks before any prompt change ships."
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
                    "regulated UK financial services. Owned Test Data "
                    "Management across Oracle and mainframes, processing "
                    "500-600 accounts per request with full validation. "
                    "Automated 30-40 manual workflows via scripting, "
                    "earning the Special Initiator Award."
                ),
                (
                    "Built full-stack features on a self-service data-"
                    "provisioning portal: Java / Spring Boot REST APIs "
                    "against Oracle, JavaScript front end, Git-based "
                    "workflows. Reusable components sped up feature rollout "
                    "around 4x. Mentored a 25-engineer team through a "
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
                "admin panel."
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
    out_path = ROOT / "output" / "resumes" / "Sai_Jayanthi_Capgemini_Full_Stack.docx"
    rendered = render(TAILORED, candidate, out_path)
    print(f"Wrote: {rendered}")


if __name__ == "__main__":
    main()
