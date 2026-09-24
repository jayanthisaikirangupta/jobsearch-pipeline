"""Build a sample Senior Google SRE resume from the JD pasted by Sai.

Sample-mode (user explicitly asked for "just a random job for a sample kind"):
all JD skills are listed in Core Skills without "studying / building toward"
qualifiers, and the tagline matches the JD seniority ("Senior SRE / Platform
Engineer"). The Graphcore-style honest-framing helpers are deliberately not
used here.

Reuses the Graphcore one-page renderer (Cambria, tight spacing, custom
section order: Header > Profile > Skills > Experience > Education).
"""
from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace

import yaml
from docx.enum.text import WD_ALIGN_PARAGRAPH

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from jobsearch.tailor.writer import (  # noqa: E402
    BLUE,
    GRAY,
    NAVY,
    _add_right_tab,
    _bullet,
    _contact_line,
    _run,
    _section_header,
    _setup_doc,
    _spacing,
    _truncate,
)


CFG = {
    "font": "Cambria",
    "name_pt": 14, "tagline_pt": 9.5, "contact_pt": 9.5,
    "header_pt": 10.5, "body_pt": 10, "bullet_pt": 10,
    "margins": (0.5, 0.5, 0.4, 0.4),
    "usable_width": 7.5,
    "line_spacing": 1.0,
    "max_profile_chars": 900,
    "max_bullet_chars": 600,
    "max_bullets_per_role": 6,
    "max_roles": 3,
    "max_education": 2,
}


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
        tagline="Senior SRE  -  GCP, GKE, Istio, Terraform, Observability",
    )


PROFILE_TEXT = (
    "Senior Site Reliability Engineer with 6+ years building and operating "
    "large-scale production platforms across regulated and high-throughput "
    "environments. Hands-on Google SRE practitioner: defines SLIs / SLOs, "
    "drives MTTD and MTTR down through structured incident management, "
    "and builds the observability that lets engineers see their systems. "
    "Deep on GCP - GKE, Istio service mesh, Cloud Run serverless, and "
    "Google networking - with Terraform, Harness, Python and full GCP "
    "DevOps tooling delivering orchestration and efficiency wins. "
    "Builds Dynatrace, Prometheus and Grafana dashboards that turn raw "
    "telemetry into the signals on-call actually needs."
)


CORE_SKILLS = [
    {
        "category": "SRE Practice",
        "items": (
            "Google SRE mindset and framework; SLI / SLO / SLA definition "
            "and error-budget policy; MTTD and MTTR reduction; incident "
            "command, blameless postmortems, runbooks; production "
            "readiness reviews; on-call rotation design; toil reduction "
            "and capacity planning."
        ),
    },
    {
        "category": "Observability & Monitoring",
        "items": (
            "Dynatrace, Prometheus, Grafana, Google Cloud Operations "
            "(Stackdriver), OpenTelemetry; time-series modelling, RED / "
            "USE method dashboards, alerting on symptoms not causes, "
            "burn-rate alerts, distributed tracing, structured logging."
        ),
    },
    {
        "category": "GCP - Compute & Networking",
        "items": (
            "GKE (cluster design, node pools, autoscaling, workload "
            "identity, network policies); Istio service mesh (mTLS, "
            "traffic splitting, circuit breaking, observability "
            "telemetry); Cloud Run serverless; Google networking - VPC, "
            "Cloud Load Balancing, Cloud Armor, Cloud NAT, Private "
            "Service Connect, Shared VPC, hybrid connectivity."
        ),
    },
    {
        "category": "Infrastructure as Code & Delivery",
        "items": (
            "Terraform (modules, remote state, policy-as-code), Harness "
            "CI/CD and feature flags, GitHub Actions, Jenkins, Cloud "
            "Build, Argo CD / GitOps patterns; Helm; progressive "
            "delivery, canary and blue/green rollouts."
        ),
    },
    {
        "category": "Languages & Automation",
        "items": (
            "Python (primary - automation, operators, internal tooling), "
            "Bash, Go (reading), SQL; container fundamentals (Docker, "
            "containerd), Linux performance tuning, systemd, networking "
            "(tcpdump, iptables, eBPF basics)."
        ),
    },
    {
        "category": "Orchestration & Efficiency",
        "items": (
            "Kubernetes operators, HPA / VPA / KEDA, GKE Autopilot, "
            "rightsizing and cost-attribution dashboards, FinOps "
            "tagging, automated remediation runbooks, self-service "
            "developer platforms."
        ),
    },
]


EXPERIENCE = [
    {
        "title": "Senior Site Reliability Engineer",
        "company": "Kuehne+Nagel UK",
        "subtitle": "Platform & Reliability",
        "location": "Milton Keynes, UK",
        "dates": "January 2025 - Present",
        "bullets": [
            (
                "Define and own SLIs and SLOs for tier-1 platform services "
                "running on GKE; drove MTTD from ~15 minutes to under 2 "
                "minutes through burn-rate alerting in Prometheus and "
                "Grafana, and MTTR by ~40% through structured incident "
                "response and pre-built runbooks."
            ),
            (
                "Designed and built the platform's Grafana and Dynatrace "
                "observability layer: RED / USE method dashboards per "
                "service, distributed tracing across the Istio service "
                "mesh, and a single \"on-call view\" used by every "
                "engineer in the rotation."
            ),
            (
                "Lead incident command for tier-1 production incidents: "
                "drive triage, comms, mitigation, and run blameless "
                "postmortems with concrete action-item follow-through; "
                "rolled out a production readiness review template now "
                "used by every new service onboarding to the platform."
            ),
            (
                "Diagnosed and remediated a production numerical-"
                "precision defect across financial calculations - traced "
                "silent rounding to IEEE 754 double-precision use for "
                "currency and switched the entire data model to "
                "DECIMAL128 fixed-precision representation."
            ),
            (
                "Refactored core backend transaction flows, reducing p95 "
                "latency by ~30% through query restructuring and "
                "data-access optimisation; instrumented the path with "
                "Prometheus histograms and SLO-aligned Grafana panels."
            ),
            (
                "Built Terraform modules and a Harness pipeline that let "
                "service teams self-provision GKE namespaces, Istio "
                "virtual services, and Cloud Run jobs in minutes rather "
                "than days - measurable orchestration and efficiency "
                "win for the platform."
            ),
        ],
    },
    {
        "title": "Innovation Project Assistant",
        "company": "University of Leicester",
        "subtitle": "Software Engineering",
        "location": "Leicester, UK",
        "dates": "May 2023 - September 2023",
        "bullets": [
            (
                "Built and shipped an end-to-end Python web application "
                "from concept to handover, including CI/CD, "
                "containerisation, and basic observability for academic "
                "stakeholders."
            ),
        ],
    },
    {
        "title": "System Engineer / Developer",
        "company": "Tata Consultancy Services - Lloyds Banking Group",
        "subtitle": "Banking & Financial Services",
        "location": "India",
        "dates": "August 2019 - December 2022",
        "bullets": [
            (
                "Built and operated self-service data-provisioning "
                "platform features on Spring Boot, Java, and Oracle; "
                "introduced reusable components that accelerated "
                "delivery roughly 4x."
            ),
            (
                "Automated 30-40 recurring manual workflows via Python "
                "and Bash scripting, eliminating toil and earning the "
                "Special Initiator Award for delivery-time reduction."
            ),
            (
                "Mentored a 25-engineer team through a critical "
                "platform transition, coordinating Git, build, and "
                "deployment tooling, and ran the on-call handover "
                "playbook for the new platform."
            ),
        ],
    },
]


EDUCATION = [
    {
        "degree": "MSc Cloud Computing  -  Distinction",
        "institution": "University of Leicester, UK",
        "dates": "January 2023 - July 2024",
    },
    {
        "degree": "BSc Computer Science",
        "institution": "Annamacharya Institute of Technology",
        "dates": "April 2015 - June 2019",
    },
]


CERTIFICATIONS = (
    "Microsoft Azure Fundamentals (AZ-900)  -  "
    "Microsoft Azure Data Fundamentals (DP-900)"
)


def render_cv(out_path: Path, candidate: SimpleNamespace) -> Path:
    cfg = CFG
    font = cfg["font"]
    body = cfg["body_pt"]
    doc = _setup_doc(font, body, cfg["margins"], cfg["line_spacing"])

    p = doc.add_paragraph(); p.alignment = WD_ALIGN_PARAGRAPH.CENTER
    _spacing(p, before=0, after=1)
    _run(p, candidate.full_name, font=font, bold=True,
         size=cfg["name_pt"], color=NAVY)

    p = doc.add_paragraph(); p.alignment = WD_ALIGN_PARAGRAPH.CENTER
    _spacing(p, before=0, after=1)
    _run(p, candidate.tagline, font=font, bold=True,
         size=cfg["tagline_pt"], color=BLUE)

    p = doc.add_paragraph(); p.alignment = WD_ALIGN_PARAGRAPH.CENTER
    _spacing(p, before=0, after=3)
    _contact_line(p, candidate, font=font, size=cfg["contact_pt"])

    _section_header(doc, "Profile", font=font, size=cfg["header_pt"])
    p = doc.add_paragraph(); _spacing(p, before=0, after=0.5)
    p.alignment = WD_ALIGN_PARAGRAPH.JUSTIFY
    _run(p, _truncate(PROFILE_TEXT, cfg["max_profile_chars"]),
         font=font, size=body)

    _section_header(doc, "Core Skills", font=font, size=cfg["header_pt"])
    for row in CORE_SKILLS:
        p = doc.add_paragraph(); _spacing(p, before=0, after=0.5)
        p.alignment = WD_ALIGN_PARAGRAPH.JUSTIFY
        _run(p, f"{row['category']}: ", font=font, bold=True,
             size=body, color=NAVY)
        _run(p, row["items"], font=font, size=body)

    _section_header(doc, "Professional Experience", font=font,
                    size=cfg["header_pt"])
    for role in EXPERIENCE[:cfg["max_roles"]]:
        p = doc.add_paragraph(); _spacing(p, before=3, after=0.5)
        _add_right_tab(p, cfg["usable_width"])
        title = role["title"].upper()
        company = role["company"]
        _run(p, f"{title} - {company}", font=font, bold=True,
             size=body, color=NAVY)
        if dates := role.get("dates"):
            _run(p, f"\t{dates}", font=font, size=body, color=GRAY)

        sub_parts = [v for k in ("subtitle", "location") if (v := role.get(k))]
        if sub_parts:
            p = doc.add_paragraph(); _spacing(p, before=0, after=0.5)
            _run(p, "  ·  ".join(sub_parts), font=font, italic=True,
                 size=body - 1, color=GRAY)

        for b in role["bullets"][:cfg["max_bullets_per_role"]]:
            _bullet(doc, _truncate(b, cfg["max_bullet_chars"]),
                    font=font, size=cfg["bullet_pt"])

    _section_header(doc, "Education", font=font, size=cfg["header_pt"])
    for ed in EDUCATION[:cfg["max_education"]]:
        p = doc.add_paragraph(); _spacing(p, before=1, after=0.5)
        _add_right_tab(p, cfg["usable_width"])
        _run(p, ed["degree"], font=font, bold=True, size=body, color=NAVY)
        if inst := ed.get("institution"):
            _run(p, f"  ·  {inst}", font=font, size=body)
        if dates := ed.get("dates"):
            _run(p, f"\t{dates}", font=font, size=body, color=GRAY)

    p = doc.add_paragraph(); _spacing(p, before=2, after=0.5)
    _run(p, "Certifications: ", font=font, bold=True, size=body, color=NAVY)
    _run(p, CERTIFICATIONS, font=font, size=body)

    out_path.parent.mkdir(parents=True, exist_ok=True)
    doc.save(out_path)
    return out_path


def main() -> None:
    candidate = load_candidate()
    cv_path = ROOT / "output" / "resumes" / "Sai_Jayanthi_Senior_Google_SRE.docx"
    rendered_cv = render_cv(cv_path, candidate)
    print(f"Wrote CV: {rendered_cv}")


if __name__ == "__main__":
    main()
