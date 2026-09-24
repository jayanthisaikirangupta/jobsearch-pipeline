"""Build the Graphcore 2026 Graduate Software Engineer (PyTorch) CV +
cover letter from hand-authored content agreed with the user.

One-page layout, custom section order:
    Header > Profile > Education > Skills > Projects > Experience

Hand-authored bullets feed a custom one-page renderer that reuses the
same Cambria/spacing helpers as jobsearch.tailor.writer one-page layout.
The standard renderer's section order is hardcoded and would not match
the agreed Graduate-CV layout, so we render directly here.

Conditional content: the Selected Projects "PyTorch re-implementation"
GitHub link and the Triton tutorial bullet are dropped in via flags below
once those repos actually exist.
"""
from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace

import yaml
from docx import Document
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.shared import Inches, Pt, RGBColor

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

# --- flip these once the repos exist -----------------------------------------
PYTORCH_REPO_LIVE = False  # tonight's PyTorch re-implementation push
TRITON_REPO_LIVE = False   # tomorrow's Triton tutorial push


# --- one-page Graphcore layout (Cambria, tight spacing) ----------------------
CFG = {
    "font": "Cambria",
    "name_pt": 14, "tagline_pt": 9.5, "contact_pt": 9.5,
    "header_pt": 10.5, "body_pt": 10, "bullet_pt": 10,
    "margins": (0.5, 0.5, 0.4, 0.4),
    "usable_width": 7.5,
    "line_spacing": 1.0,
    "max_profile_chars": 900,
    "max_bullet_chars": 600,
    "max_bullets_per_role": 5,
    "max_roles": 3,
    "max_projects": 2,
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
        tagline="Software Engineer  -  Python, ML & Systems",
    )


_PROFILE_FRAMEWORK_PHRASE = (
    "in PyTorch and TensorFlow"
    if PYTORCH_REPO_LIVE
    else "in TensorFlow / Keras"
)

PROFILE_TEXT = (
    "MSc Cloud Computing, Distinction (University of Leicester, 2024). "
    "Software engineer drawn to the layer where ML frameworks meet "
    "hardware: how PyTorch dispatches operations, how compilers lower "
    "them, how new accelerators get first-class framework support. "
    "MSc dissertation: 3-class chest X-ray classifier on ~10,400 images "
    f"{_PROFILE_FRAMEWORK_PHRASE} (custom CNN + fine-tuned VGG16, "
    "Grad-CAM localisation); the custom CNN outperformed VGG16 in "
    "evaluation and was selected for deployment. Now a software engineer "
    "at Kuehne+Nagel building production Python and Java backend "
    "services, with active study in C++, CUDA, LLVM and PyTorch "
    "internals to move into framework- and compiler-level work."
)


CORE_SKILLS = [
    {
        "category": "Languages",
        "items": (
            "Python (primary), C++, C, Java 17, SQL, Bash; reading "
            "TypeScript."
        ),
    },
    {
        "category": "ML Frameworks & Systems",
        "items": (
            "PyTorch (CNN training and fine-tuning, autograd, custom "
            "training loops, Grad-CAM); TensorFlow / Keras (dissertation "
            "implementation, comparison against PyTorch); studying "
            "PyTorch internals: dispatcher, ATen, autograd graph, "
            "torch.compile, custom ops."
        ),
    },
    {
        "category": "Accelerators & Performance",
        "items": (
            "Reading: CUDA programming model (kernels, threads, blocks, "
            "warps, shared memory), Triton DSL, GPU vs CPU vs IPU "
            "execution models, BSP, in-processor memory; LLVM and "
            "compiler basics; comfortable reading SIMD intrinsics "
            "(AVX, NEON) and reasoning about cache, memory, and "
            "branch behaviour."
        ),
    },
    {
        "category": "Relevant Coursework",
        "items": (
            "BSc Computer Science: Data Structures, Computer Networks, "
            "Software Engineering, Discrete Mathematics, Linear Algebra, "
            "Probability and Statistics, Operating Systems concepts. "
            "MSc: Big Data and Predictive Analytics, Service-Oriented "
            "Architecture, Software Quality Assurance."
        ),
    },
    {
        "category": "Software Engineering",
        "items": (
            "Production debugging on large codebases, root-cause "
            "analysis, numerical-precision defect remediation, "
            "performance profiling and refactoring, REST and async "
            "services, schema validation, retry and idempotency, code "
            "review, technical documentation."
        ),
    },
    {
        "category": "Tooling",
        "items": (
            "Linux (Ubuntu), Git, GitHub, Docker, CI/CD (Jenkins, GitHub "
            "Actions), gdb / valgrind basics, Jupyter, Microsoft Azure "
            "(AZ-900, DP-900)."
        ),
    },
]


EXPERIENCE = [
    {
        "title": "Software Engineer",
        "company": "Kuehne+Nagel UK",
        "subtitle": "Backend & Platform",
        "location": "Milton Keynes, UK",
        "dates": "January 2025 - Present",
        "bullets": [
            (
                "Diagnosed and fixed a production numerical-precision "
                "defect in financial calculations: traced silent rounding "
                "across thousands of records to IEEE 754 double-precision "
                "use for currency, switched the entire data model to "
                "DECIMAL128 fixed-precision representation. The kind of "
                "low-level numeric-type debugging that matters in compute "
                "kernels."
            ),
            (
                "Refactored core backend transaction flows on Spring "
                "Boot / Hibernate / Oracle, reducing transaction latency "
                "by approximately 30% through query restructuring and "
                "data-access optimisation."
            ),
            (
                "Resolved a front-end lazy-loading race condition firing "
                "132 redundant network requests per page; reduced to 9 "
                "through proper request sequencing."
            ),
            (
                "Built async batch services with retry, idempotency, and "
                "observability in Python and Java, debugging across the "
                "stack from Python to JVM internals on a large existing "
                "codebase."
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
                "from concept to handover. Self-initiated technical "
                "scoping, prototyping, and documentation for academic "
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
                "Built full-stack features on a self-service data-"
                "provisioning portal (Spring Boot, Java 8, Oracle), "
                "accelerating rollout approximately 4x via reusable "
                "components."
            ),
            (
                "Automated 30-40 recurring manual workflows via "
                "scripting; received the Special Initiator Award for "
                "delivery-time reduction."
            ),
            (
                "Mentored a 25-engineer team during a critical platform "
                "transition, coordinating Git, build, and deployment "
                "tooling."
            ),
        ],
    },
]


def build_projects() -> list[dict]:
    projects: list[dict] = []

    if PYTORCH_REPO_LIVE:
        projects.append({
            "name": (
                "Chest X-Ray Classifier (PyTorch re-implementation)  -  "
                "github.com/jayanthisaikirangupta/covid-xray-pytorch"
            ),
            "tech_stack": (
                "PyTorch, TensorFlow / Keras, VGG16, Grad-CAM, Python"
            ),
            "summary": (
                "MSc dissertation (Leicester, 2024). 3-class classifier "
                "(COVID / pneumonia / normal) on ~10,400 chest X-rays, "
                "with a custom CNN outperforming a fine-tuned VGG16 in "
                "evaluation. Re-implementing in PyTorch to compare the "
                "dispatcher and autograd behaviour against the original "
                "TensorFlow / Keras implementation. Grad-CAM for "
                "localisation."
            ),
        })
    else:
        projects.append({
            "name": "Chest X-Ray Classifier (MSc Dissertation)",
            "tech_stack": (
                "TensorFlow / Keras, VGG16, Grad-CAM, Python"
            ),
            "summary": (
                "MSc dissertation (Leicester, 2024). 3-class classifier "
                "(COVID / pneumonia / normal) on ~10,400 chest X-rays. "
                "Custom CNN outperformed a fine-tuned VGG16 in "
                "evaluation and was selected for deployment. Implemented "
                "Grad-CAM to produce localisation heatmaps showing the "
                "lung regions driving each prediction. Currently "
                "re-implementing the model in PyTorch to compare "
                "dispatcher and autograd behaviour."
            ),
        })

    projects.append({
        "name": "Self-Study: PyTorch Internals & Accelerator Compilers",
        "tech_stack": (
            "PyTorch (dispatcher, ATen, autograd), CUDA, Triton, LLVM"
        ),
        "summary": (
            "Working through PyTorch internals (dispatcher, ATen kernels, "
            "autograd graph, torch.compile), the CUDA programming model, "
            "and the Triton DSL to understand how high-level Python ops "
            "lower to accelerator code. Reading on LLVM IR and compiler "
            "lowering to bridge into framework- and compiler-level work "
            "on non-GPU accelerators."
        ),
    })

    return projects


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
    "Microsoft Azure Fundamentals (AZ-900, June 2023)  -  "
    "Microsoft Azure Data Fundamentals (DP-900, June 2023)"
)


# --- custom one-page renderer with agreed section order ---------------------

def render_cv(out_path: Path, candidate: SimpleNamespace) -> Path:
    cfg = CFG
    font = cfg["font"]
    body = cfg["body_pt"]
    doc = _setup_doc(font, body, cfg["margins"], cfg["line_spacing"])

    # Header: name
    p = doc.add_paragraph(); p.alignment = WD_ALIGN_PARAGRAPH.CENTER
    _spacing(p, before=0, after=1)
    _run(p, candidate.full_name, font=font, bold=True,
         size=cfg["name_pt"], color=NAVY)

    # Tagline
    p = doc.add_paragraph(); p.alignment = WD_ALIGN_PARAGRAPH.CENTER
    _spacing(p, before=0, after=1)
    _run(p, candidate.tagline, font=font, bold=True,
         size=cfg["tagline_pt"], color=BLUE)

    # Contact
    p = doc.add_paragraph(); p.alignment = WD_ALIGN_PARAGRAPH.CENTER
    _spacing(p, before=0, after=3)
    _contact_line(p, candidate, font=font, size=cfg["contact_pt"])

    # Profile
    _section_header(doc, "Profile", font=font, size=cfg["header_pt"])
    p = doc.add_paragraph(); _spacing(p, before=0, after=0.5)
    p.alignment = WD_ALIGN_PARAGRAPH.JUSTIFY
    _run(p, _truncate(PROFILE_TEXT, cfg["max_profile_chars"]),
         font=font, size=body)

    # Education (above Skills, above Experience — agreed grad framing)
    _section_header(doc, "Education", font=font, size=cfg["header_pt"])
    for ed in EDUCATION[:cfg["max_education"]]:
        p = doc.add_paragraph(); _spacing(p, before=1, after=0.5)
        _add_right_tab(p, cfg["usable_width"])
        _run(p, ed["degree"], font=font, bold=True, size=body, color=NAVY)
        if inst := ed.get("institution"):
            _run(p, f"  ·  {inst}", font=font, size=body)
        if dates := ed.get("dates"):
            _run(p, f"\t{dates}", font=font, size=body, color=GRAY)

    # Certifications (sit under Education)
    p = doc.add_paragraph(); _spacing(p, before=2, after=0.5)
    _run(p, "Certifications: ", font=font, bold=True, size=body, color=NAVY)
    _run(p, CERTIFICATIONS, font=font, size=body)

    # Skills
    _section_header(doc, "Core Skills", font=font, size=cfg["header_pt"])
    for row in CORE_SKILLS:
        p = doc.add_paragraph(); _spacing(p, before=0, after=0.5)
        p.alignment = WD_ALIGN_PARAGRAPH.JUSTIFY
        _run(p, f"{row['category']}: ", font=font, bold=True,
             size=body, color=NAVY)
        _run(p, row["items"], font=font, size=body)

    # Projects (only if any repo is live)
    projects = build_projects()
    if projects:
        _section_header(doc, "Selected Projects", font=font,
                        size=cfg["header_pt"])
        for proj in projects[:cfg["max_projects"]]:
            p = doc.add_paragraph(); _spacing(p, before=1, after=0)
            _run(p, proj["name"], font=font, bold=True,
                 size=body, color=NAVY)
            if stack := proj.get("tech_stack"):
                _run(p, f"  ·  {stack}", font=font, italic=True,
                     size=body - 1, color=GRAY)
            if summary := proj.get("summary"):
                _bullet(doc, _truncate(summary, cfg["max_bullet_chars"]),
                        font=font, size=cfg["bullet_pt"])

    # Experience
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

    out_path.parent.mkdir(parents=True, exist_ok=True)
    doc.save(out_path)
    return out_path


# --- cover letter ------------------------------------------------------------

COVER_LETTER_PARAGRAPHS = [
    "Dear Hiring Team,",
    (
        "I'd like to be part of the team that keeps PyTorch running "
        "well on the IPU. I'm applying for the 2026 Graduate Software "
        "Engineer - PyTorch role on the Frameworks team."
    ),
    (
        "The interest started during my MSc at Leicester. My "
        "dissertation was a 3-class chest X-ray classifier on ~10,400 "
        "images, comparing a custom CNN against a fine-tuned VGG16 in "
        "TensorFlow / Keras, with Grad-CAM for localisation. I am "
        "currently re-implementing the same model in PyTorch. The "
        "differences I have seen so far come down to how the two "
        "frameworks treat the computation graph: TensorFlow / Keras "
        "compiles the graph once and runs it, which made the training "
        "loop fast but rigid; PyTorch builds the graph on each forward "
        "pass through its dispatcher and autograd engine, which is "
        "slower per step but lets me see and step through what the "
        "model is actually doing. Working through that pulled me into "
        "the layer below: how the dispatcher selects a kernel, how "
        "ATen lowers to backend code, why the same architecture trains "
        "differently on different hardware. That layer is the work I "
        "want to be doing."
    ),
    (
        "Graphcore is one of the few places where supporting PyTorch "
        "on an accelerator that is not a GPU is the whole job, not a "
        "side concern. The IPU is a different execution model from a "
        "GPU - MIMD with on-chip memory rather than SIMT with off-chip "
        "DRAM - which means making PyTorch feel native on it is real "
        "compiler and framework work, not a thin wrapper. That is the "
        "problem I want to spend my graduate years on."
    ),
    (
        "I work at Kuehne+Nagel now as a software engineer on a "
        "Python and Java backend platform. The most relevant piece of "
        "work for this role is a numerical-precision defect I traced "
        "and fixed: the system was using IEEE 754 doubles for "
        "currency, which introduced silent rounding across thousands "
        "of records on aggregation. I switched the data model to "
        "DECIMAL128 fixed-precision end-to-end. That kind of careful, "
        "low-level numeric-type debugging is what carries into compute "
        "kernels - the same care for representation, the same need to "
        "see what the machine is actually doing with your numbers."
    ),
    (
        "Outside work I am studying C++, the CUDA programming model, "
        "and the Triton DSL to bridge into accelerator and compiler "
        "work, alongside reading PyTorch internals. I know the "
        "Frameworks role will need real C++ from day one - I am "
        "building toward that, and would value the structure of a "
        "graduate role to do it under."
    ),
    "I would welcome the chance to talk.",
    "Best regards,",
    "Sai Kiran Gupta Jayanthi",
]


def render_cover_letter(out_path: Path, candidate: SimpleNamespace) -> Path:
    doc = Document()
    section = doc.sections[0]
    section.top_margin = Inches(0.7)
    section.bottom_margin = Inches(0.7)
    section.left_margin = Inches(0.9)
    section.right_margin = Inches(0.9)

    name_p = doc.add_paragraph()
    name_p.alignment = WD_ALIGN_PARAGRAPH.LEFT
    nr = name_p.add_run(candidate.full_name)
    nr.font.name = "Calibri"
    nr.font.size = Pt(14)
    nr.bold = True
    nr.font.color.rgb = RGBColor(0x1F, 0x3A, 0x5F)

    contact_p = doc.add_paragraph()
    contact_p.alignment = WD_ALIGN_PARAGRAPH.LEFT
    contact_text = (
        f"{candidate.location}  |  {candidate.phone}  |  {candidate.email}"
    )
    cr = contact_p.add_run(contact_text)
    cr.font.name = "Calibri"
    cr.font.size = Pt(10)
    cr.font.color.rgb = RGBColor(0x59, 0x59, 0x59)

    doc.add_paragraph()

    for text in COVER_LETTER_PARAGRAPHS:
        p = doc.add_paragraph()
        p.alignment = WD_ALIGN_PARAGRAPH.LEFT
        run = p.add_run(text)
        run.font.name = "Calibri"
        run.font.size = Pt(11)
        p.paragraph_format.space_after = Pt(8)
        p.paragraph_format.line_spacing = 1.15

    out_path.parent.mkdir(parents=True, exist_ok=True)
    doc.save(out_path)
    return out_path


def main() -> None:
    candidate = load_candidate()

    cv_path = ROOT / "output" / "resumes" / "Sai_Jayanthi_Graphcore_Graduate_PyTorch.docx"
    rendered_cv = render_cv(cv_path, candidate)
    print(f"Wrote CV: {rendered_cv}")

    cl_path = ROOT / "output" / "CV" / "Sai_Jayanthi_Graphcore_CoverLetter.docx"
    rendered_cl = render_cover_letter(cl_path, candidate)
    print(f"Wrote cover letter: {rendered_cl}")


if __name__ == "__main__":
    main()
