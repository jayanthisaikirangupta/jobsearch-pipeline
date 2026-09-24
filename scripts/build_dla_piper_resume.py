"""Build the DLA Piper AI Engineer resume (via McGregor Boyall / Nathan
Carolan).

Role focus: cutting-edge GenAI and Agentic AI in the document intelligence
and knowledge-retrieval space, inside a law firm. Stack: Python, Azure
Databricks, Azure ML, MLOps, LLMs, RAG, LangChain / LangGraph, agentic
workflows.

Retailored from the existing 12a7166df9a606e9_Capgemini GenAI CV (A / 86)
by swapping the financial-services framing for legal / document-intelligence
positioning and surfacing Azure Databricks, Azure ML, LangGraph, and MLOps
verbatim in Core Skills. Hand-authored (not LLM-tailored) - feeds the same
one-page renderer in jobsearch.tailor.writer.
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

writer.ONE_PAGE["max_profile_chars"] = 800
writer.ONE_PAGE["max_bullet_chars"] = 300
writer.ONE_PAGE["max_bullets_per_role"] = 5


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
        tagline="AI Engineer  -  GenAI, Agentic Workflows & Document Intelligence",
    )


TAILORED: dict = {
    "format_choice": "one_page",
    "headline": "AI Engineer  -  GenAI, Agentic Workflows & Document Intelligence",
    "profile": (
        "AI engineer with 6+ years across enterprise backend and, in the "
        "last year, shipping GenAI in production at Kuehne+Nagel. Built an "
        "async OCR + LLM document-extraction pipeline end to end with "
        "schema-gated outputs, retries, idempotency and observability - "
        "document intelligence is my day job. Also shipped agentic "
        "workflows (Propose / Discuss / Implement with human-in-the-loop "
        "gates, n8n orchestrations) and a citation-backed RAG pipeline "
        "with embeddings, chunking and re-ranking over internal docs. "
        "Comfortable with LangChain, LangGraph, Anthropic Claude and "
        "OpenAI, MCP integrations on locked-down enterprise networks, and "
        "MLOps patterns on Azure. MSc Cloud Computing (Leicester)."
    ),
    "core_skills": [
        {
            "category": "GenAI & LLMs",
            "items": (
                "Anthropic Claude API, OpenAI API, Hugging Face, prompt "
                "engineering, structured outputs, function calling / tool "
                "use, guardrails, evaluation-driven iteration against "
                "ground-truth sets."
            ),
        },
        {
            "category": "Agentic AI & Frameworks",
            "items": (
                "LangChain, LangGraph, LlamaIndex, n8n; multi-step "
                "reasoning, tool use, conditional routing, retries and "
                "persistence; Model Context Protocol (MCP) server "
                "integration for Claude assistants."
            ),
        },
        {
            "category": "RAG & Document Intelligence",
            "items": (
                "Retrieval-Augmented Generation with citation-backed "
                "responses, embeddings and semantic search, chunking and "
                "re-ranking, hybrid search; vector databases (Pinecone, "
                "FAISS, Chroma); OCR + LLM extraction pipelines with "
                "schema validation gates."
            ),
        },
        {
            "category": "ML & MLOps",
            "items": (
                "PyTorch, TensorFlow, Scikit-Learn, PySpark; model "
                "deployment and monitoring, retraining hooks, CI/CD, "
                "Docker, Kubernetes, observability, cost and latency "
                "tracking."
            ),
        },
        {
            "category": "Python & APIs",
            "items": (
                "Python (FastAPI, Flask, Pandas, NumPy), async batch "
                "processing, RESTful API design, Java 17 / Spring Boot / "
                "Quarkus on the backend side of my day job."
            ),
        },
        {
            "category": "Cloud & Data",
            "items": (
                "Microsoft Azure (AZ-900, DP-900); Azure ML and Azure "
                "Databricks / PySpark adjacent to production experience; "
                "AWS, GCP; MongoDB, Oracle, PostgreSQL, Snowflake."
            ),
        },
    ],
    "experience": [
        {
            "title": "AI Engineer",
            "company": "Kuehne+Nagel UK",
            "subtitle": "Travel & Expense Platform  -  GenAI & Backend",
            "location": "Milton Keynes, UK",
            "dates": "January 2025 - Present",
            "bullets": [
                (
                    "Took an OCR + LLM document-extraction pipeline from "
                    "PoC to production (Python + Java / Quarkus, FastAPI, "
                    "MongoDB): async batch, schema-gated outputs, retries, "
                    "idempotency and observability so partial LLM failures "
                    "stay recoverable rather than silently corrupting "
                    "downstream data."
                ),
                (
                    "Shipped an agentic Propose / Discuss / Implement "
                    "ticket-assist pipeline with human-in-the-loop gates, "
                    "and n8n workflow orchestrations doing multi-step "
                    "reasoning, tool use, conditional routing and "
                    "persistence - the same patterns that hold up for "
                    "production agentic AI."
                ),
                (
                    "Built a citation-backed RAG pipeline over internal "
                    "docs with embeddings, chunking and re-ranking. "
                    "Prompt changes go through an evaluation harness "
                    "against ground-truth sets before anything ships, so "
                    "iteration is measured rather than guessed."
                ),
                (
                    "Integrated multiple MCP servers (bug tracker, IDE, "
                    "MongoDB) into Claude on locked-down enterprise "
                    "machines behind a TLS-intercepting proxy - a real "
                    "lesson in making GenAI usable inside a regulated "
                    "corporate network."
                ),
                (
                    "Root-caused and fixed a silent-rounding defect on "
                    "thousands of financial records by switching the data "
                    "model to DECIMAL128; refactored core transaction "
                    "flows on Spring Boot / Hibernate / Oracle, cutting "
                    "latency around 30 percent."
                ),
            ],
        },
        {
            "title": "Innovation Project Assistant",
            "company": "University of Leicester",
            "subtitle": "AI Requirement-Gathering Web App",
            "location": "Leicester, UK",
            "dates": "May 2023 - September 2023",
            "bullets": [
                (
                    "Built a Python (Flask) + MySQL web app that turned "
                    "unstructured consultation transcripts into structured "
                    "requirements via the OpenAI API, with validation "
                    "prompts and NLP preprocessing. Self-initiated the LLM "
                    "and prompt-engineering direction for the project."
                ),
            ],
        },
        {
            "title": "System Engineer",
            "company": "Tata Consultancy Services  -  Lloyds Banking Group",
            "subtitle": "Regulated Banking Platform",
            "location": "India",
            "dates": "August 2019 - December 2022",
            "bullets": [
                (
                    "Three years on the Lloyds Banking Group account. "
                    "Owned Test Data Management on Oracle and mainframes, "
                    "processing 500-600 accounts per request with full "
                    "validation and compliance controls. Automated 30-40 "
                    "manual workflows via scripting, earning the Special "
                    "Initiator Award."
                ),
                (
                    "Built full-stack features on a self-service data-"
                    "provisioning portal (Java 8 / Spring Boot / Oracle), "
                    "accelerating feature rollout around 4x through "
                    "reusable components. Regulated-domain background "
                    "sits behind how I think about responsible AI now."
                ),
            ],
        },
    ],
    "projects": [
        {
            "name": "Document-Intelligence Pipeline (OCR + LLM)",
            "tech_stack": (
                "Python, Java / Quarkus, FastAPI, MongoDB, Anthropic "
                "Claude / OpenAI, async batch"
            ),
            "summary": (
                "Production pipeline: upload -> OCR -> LLM extraction -> "
                "schema validation -> persistence, with retry, "
                "idempotency, observability and audit trail. The pattern "
                "generalises directly to legal document intake and "
                "knowledge extraction."
            ),
        },
        {
            "name": "Agentic Job-Search Pipeline",
            "tech_stack": (
                "Python, Anthropic Claude API, LangChain-style tool use, "
                "n8n, public job APIs"
            ),
            "summary": (
                "Multi-step agent that ingests postings, scores them via "
                "Claude, drafts tailored applications and reviews itself "
                "against ground truth. Tool use, conditional routing, "
                "persistence, evaluation gates - the same shape as "
                "production agentic workflows."
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
    out_path = ROOT / "output" / "resumes" / "Sai_Jayanthi_DLA_Piper_AI_Engineer.docx"
    rendered = render(TAILORED, candidate, out_path)
    print(f"Wrote: {rendered}")


if __name__ == "__main__":
    main()
