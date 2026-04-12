import json
import os
import re
import subprocess
import tempfile
import urllib.error
import urllib.request
from pathlib import Path

from rest_framework import status
from rest_framework.parsers import FormParser, JSONParser, MultiPartParser
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from .pdf_parser import parse_resume_pdf
from .models import JobRole, Resume, ResumeAnalysis, TailoredJobRun, ApplicationTracking, Company, Employee, Job
from .serializers import (
    JobRoleSerializer,
    ResumeAnalysisSerializer,
    ResumeSerializer,
    SignupSerializer,
    TailoredJobRunSerializer,
    ApplicationTrackingSerializer,
    CompanySerializer,
    EmployeeSerializer,
    JobSerializer,
)
from .tailor import (
    ALLOWED_AI_MODELS,
    builder_has_substance,
    build_quality_optimized_builder,
    build_tailored_builder,
    builder_data_to_text,
    extract_keywords_ai,
    find_best_resume_match,
    optimize_existing_resume_quality_ai,
    sanitize_builder_data,
    tailor_resume_with_ai,
)

def _plain_text_from_html(value: str) -> str:
    import re

    t = str(value or "")
    t = re.sub(r"<style[^>]*>[\s\S]*?</style>", " ", t, flags=re.I)
    t = re.sub(r"<script[^>]*>[\s\S]*?</script>", " ", t, flags=re.I)
    t = re.sub(r"<[^>]+>", " ", t)
    t = t.replace("&nbsp;", " ").replace("&amp;", "&").replace("&lt;", "<").replace("&gt;", ">")
    t = re.sub(r"\s+", " ", t).strip()
    return t


def _builder_data_to_text(builder_data: dict) -> str:
    data = builder_data or {}
    parts = []
    for key in ["fullName", "location", "phone", "email", "resumeTitle"]:
        v = str(data.get(key, "") or "").strip()
        if v:
            parts.append(v)

    summary = _plain_text_from_html(data.get("summary") or "")
    if summary:
        parts.append(summary)

    skills = _plain_text_from_html(data.get("skills") or "")
    if skills:
        parts.append(skills)

    for exp in data.get("experiences") or []:
        company = str(exp.get("company") or "").strip()
        title = str(exp.get("title") or "").strip()
        dates = " ".join([str(exp.get("startDate") or "").strip(), str(exp.get("endDate") or "").strip()]).strip()
        head = " | ".join([p for p in [company, title, dates] if p])
        if head:
            parts.append(head)
        parts.append(_plain_text_from_html(exp.get("highlights") or ""))

    for proj in data.get("projects") or []:
        name = str(proj.get("name") or "").strip()
        if name:
            parts.append(name)
        parts.append(_plain_text_from_html(proj.get("highlights") or ""))

    for edu in data.get("educations") or []:
        inst = str(edu.get("institution") or "").strip()
        program = str(edu.get("program") or "").strip()
        if inst or program:
            parts.append(" | ".join([p for p in [inst, program] if p]))

    return "\n".join([p for p in [p.strip() for p in parts] if p])


def _section_presence_from_builder(builder_data: dict) -> dict:
    data = sanitize_builder_data(builder_data or {})
    return {
        "summary": bool(_plain_text_from_html(data.get("summary") or "")),
        "skills": bool(_plain_text_from_html(data.get("skills") or "")),
        "experiences": bool(data.get("experiences") or []),
        "projects": bool(data.get("projects") or []),
        "educations": bool(data.get("educations") or []),
        "customSections": bool(data.get("customSections") or []),
        "role": bool(str(data.get("role") or "").strip()),
    }


def _restrict_to_reference_sections(reference_builder: dict, result_builder: dict) -> dict:
    reference = sanitize_builder_data(reference_builder or {})
    result = sanitize_builder_data(result_builder or {})
    present = _section_presence_from_builder(reference)

    # Keep exact section order from reference when available.
    if isinstance(reference.get("sectionOrder"), list):
        result["sectionOrder"] = list(reference.get("sectionOrder") or [])

    if not present["summary"]:
        result["summaryEnabled"] = False
        result["summary"] = ""
    if not present["skills"]:
        result["skills"] = ""
    if not present["experiences"]:
        result["experiences"] = []
    if not present["projects"]:
        result["projects"] = []
    if not present["educations"]:
        result["educations"] = []
    if not present["customSections"]:
        result["customSections"] = []
    if not present["role"]:
        result["role"] = ""

    return sanitize_builder_data(result)


def _sanitize_filename_stem(raw: str) -> str:
    value = re.sub(r"\s+", " ", str(raw or "").strip())
    value = re.sub(r"[^\w\s-]", "", value)
    value = value.replace(" ", "").strip("._-")
    return value or "resume"


def _default_pdf_filename(builder_data: dict) -> str:
    data = builder_data if isinstance(builder_data, dict) else {}
    full_name = str(data.get("fullName") or "").strip()
    parts = [re.sub(r"[^\w]", "", p).lower() for p in re.split(r"\s+", full_name) if p.strip()]
    if not parts:
        base = "resume"
    elif len(parts) == 1:
        base = parts[0]
    else:
        base = f"{parts[0]}{parts[-1]}"
    stem = _sanitize_filename_stem(f"{base}_3yoe").lower()
    return f"{stem}.pdf"


def _pick_local_pdf_path(file_name: str) -> Path:
    target_dir = Path.home() / "Desktop" / "Ats"
    target_dir.mkdir(parents=True, exist_ok=True)
    stem = _sanitize_filename_stem(Path(str(file_name or "")).stem).lower()
    if not stem:
        stem = "resume"
    # Always overwrite existing file as requested.
    return target_dir / f"{stem}.pdf"


def _available_browser_binaries():
    candidates = [
        "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
        "/Applications/Brave Browser.app/Contents/MacOS/Brave Browser",
    ]
    return [path for path in candidates if Path(path).exists()]


def _render_pdf_from_html(html_text: str, output_pdf: Path):
    browser_bins = _available_browser_binaries()
    if not browser_bins:
        return False, "Chrome/Brave not found on this machine."

    with tempfile.NamedTemporaryFile("w", suffix=".html", delete=False, encoding="utf-8") as tmp:
        tmp.write(str(html_text or ""))
        tmp_html_path = Path(tmp.name)

    html_url = tmp_html_path.as_uri()
    errors = []
    try:
        for browser_bin in browser_bins:
            cmd = [
                browser_bin,
                "--headless=new",
                "--disable-gpu",
                "--no-sandbox",
                "--no-pdf-header-footer",
                f"--print-to-pdf={str(output_pdf)}",
                html_url,
            ]
            try:
                run = subprocess.run(
                    cmd,
                    capture_output=True,
                    text=True,
                    timeout=45,
                    check=False,
                )
                if run.returncode == 0 and output_pdf.exists() and output_pdf.stat().st_size > 0:
                    return True, ""
                stderr = (run.stderr or "").strip()
                stdout = (run.stdout or "").strip()
                snippet = stderr or stdout or f"exit code {run.returncode}"
                errors.append(f"{Path(browser_bin).name}: {snippet[:220]}")
            except Exception as exc:  # noqa: BLE001
                errors.append(f"{Path(browser_bin).name}: {exc}")
        return False, "; ".join(errors) or "PDF generation failed."
    finally:
        try:
            tmp_html_path.unlink(missing_ok=True)
        except Exception:  # noqa: BLE001
            pass


def _resolve_openai_model() -> str:
    value = str(os.getenv("OPENAI_MODEL", "gpt-4o") or "").strip()
    return value or "gpt-4o"


def _openai_question_answers(questions, profile_context: str = ""):
    api_key = os.getenv("OPENAI_API_KEY", "").strip()
    if not api_key:
        return [], "OPENAI_API_KEY is not set"

    safe_questions = [str(q or "").strip() for q in (questions or []) if str(q or "").strip()]
    if not safe_questions:
        return [], ""

    system = (
        "You are a job-application form assistant. Return strict JSON only. "
        "Answer each question briefly, professionally, and specifically. "
        "If unsure, return a conservative generic answer and avoid hallucinations. "
        "Output format: {\"answers\":[{\"question\":\"...\",\"answer\":\"...\"}]}"
    )
    user = (
        "Profile context:\n"
        f"{str(profile_context or '').strip()[:5000]}\n\n"
        "Questions:\n"
        f"{json.dumps(safe_questions, ensure_ascii=False)}"
    )
    payload = {
        "model": _resolve_openai_model(),
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
        "response_format": {"type": "json_object"},
        "temperature": 0.2,
    }
    req = urllib.request.Request(
        "https://api.openai.com/v1/chat/completions",
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=60) as resp:
            data = json.loads(resp.read().decode("utf-8"))
        content = data.get("choices", [{}])[0].get("message", {}).get("content", "{}")
        parsed = json.loads(content) if isinstance(content, str) else content
        rows = parsed.get("answers") if isinstance(parsed, dict) else []
        if not isinstance(rows, list):
            return [], "AI response missing answers list"
        out = []
        for row in rows:
            if not isinstance(row, dict):
                continue
            q = str(row.get("question") or "").strip()
            a = str(row.get("answer") or "").strip()
            if q and a:
                out.append({"question": q, "answer": a})
        return out, ""
    except urllib.error.HTTPError as exc:
        try:
            body = exc.read().decode("utf-8")
        except Exception:  # noqa: BLE001
            body = ""
        return [], f"OpenAI request failed: {body or exc.reason}"
    except Exception as exc:  # noqa: BLE001
        return [], f"OpenAI request failed: {exc}"


PRESET_KEYWORDS = {
    "frontend": ["react", "javascript", "typescript", "redux", "html", "css", "vite", "api", "ui"],
    "backend": ["python", "django", "drf", "rest", "api", "postgres", "redis", "celery", "auth", "jwt"],
    "fullstack": ["react", "python", "django", "drf", "rest", "api", "postgres", "aws", "docker", "git"],
}

PROFILE_CONFIG_PATH = Path(__file__).resolve().parents[1] / "config" / "profile_data.json"


def _default_profile_config(username: str = "") -> dict:
    return {
        "personalInfo": {
            "firstName": "subrat",
            "lastName": "singh",
            "preferredName": "subrat",
            "suffixName": "singh",
            "emailAddress": "subratsingh010@gmail.com",
            "phoneNumber": "+918546075639",
            "birthday": "2000-12-30",
            "location": "Gurugram, HR, India",
        },
        "address": {
            "address1": "2121, Sukhrali Rd, near Sector 17 A, Sukhrali, Market, Gurugram, Haryana 122007",
            "address2": "-",
            "address3": "-",
            "postalCode": "122007",
        },
        "socialUrls": {
            "linkedinUrl": "https://www.linkedin.com/in/subrat-s-81720a22a",
            "githubUrl": "https://github.com/subrasinght010",
            "portfolioUrl": "-",
            "otherUrl": "https://leetcode.com/u/subrat010/",
        },
        "employmentInformation": {
            "ethnicity": "South Asian",
            "authorizedUs": "No",
            "authorizedCanada": "No",
            "authorizedUk": "No",
            "visaSponsorship": "No",
            "disability": "Yes",
            "lgbtq": "No",
            "gender": "Male",
        },
        "employmentQuestions": [
            {"question": "Current employer", "answer": "Inspektlabs"},
            {"question": "Notice period", "answer": "30 days"},
        ],
        "workExperiences": [
            {
                "company": "Inspektlabs",
                "role": "Software Developer",
                "employerName": "Inspektlabs",
                "location": "Remote",
                "startTime": "Mar 2025",
                "endTime": "Present",
                "currentWorking": "Yes",
                "employmentType": "Full-Time",
                "highlights": (
                    "- Migrated API from Flask to FastAPI with async queues, raising throughput 95% from 1200 to 3000 RPM and cutting latency 34% from 320 ms to 210 ms.\n"
                    "- Built support agent that cut query resolution 70% from 10 min to 3 min with WebSockets, TensorFlow VAD, and Whisper STT.\n"
                    "- Developed fixed-camera pipeline for 1-12 channel NVR feeds, processing about 100 files per min with Celery and AWS Lambda inference.\n"
                    "- Reduced results portal dashboard load time 40% from 5 s to 3 s by refining UI flows and trimming heavy client-side requests.\n"
                    "- Launched inspection portal for damage detection, RC lookup, reports, and claim prediction, supporting 4 workflows tied to revenue growth."
                ),
            },
            {
                "company": "Staqu Technologies Pvt. Ltd.",
                "role": "Software Developer",
                "employerName": "Staqu Technologies Pvt. Ltd.",
                "location": "Gurugram, HR, India",
                "startTime": "Mar 2023",
                "endTime": "Feb 2025",
                "currentWorking": "No",
                "employmentType": "Full-Time",
                "highlights": (
                    "- Designed CrimeGPT hybrid RAG pipeline across 2 data stores, adding text-to-SQL, NER, OCR, and Mistral services through FastAPI microservices.\n"
                    "- Implemented Jarvis UI and backend modules, shipping an events panel with 20+ metrics across charts and KPI dashboards for daily monitoring.\n"
                    "- Optimized PostgreSQL and TimescaleDB queries, cutting dashboard latency 79% from 7.5 s to 1.6 s.\n"
                    "- Engineered 10+ event pipelines for Jarvis, supporting real-time video at 60 FPS across about 6 streams in a microservices setup."
                ),
            },
            {
                "company": "Across The Globe (ATG)",
                "role": "Software Developer",
                "employerName": "Across The Globe (ATG)",
                "location": "Remote",
                "startTime": "Jan 2023",
                "endTime": "Apr 2023",
                "currentWorking": "No",
                "employmentType": "Full-Time",
                "highlights": (
                    "- Delivered the Raghav Tech full-stack Django project, from database design to template design, in 10 days.\n"
                    "- Integrated Paytm, UPI, and Stripe across 3 payment paths to support transactions and strengthen revenue collection.\n"
                    "- Automated CI/CD, reducing deploy time 67% from 30 min to 10 min and enabling 1 release per day."
                ),
            },
        ],
        "education": [
            {
                "school": "KIET Group of Institutions, Ghaziabad",
                "degree": "Bachelor's",
                "fieldOfStudy": "Computer Science",
                "startTime": "Apr 2019",
                "endTime": "Apr 2023",
                "grade": "",
            }
        ],
        "projects": [
            {
                "name": "Support Agent",
                "location": "",
                "link": "",
                "highlights": (
                    "Deployed support system that reduced query resolution 70% (10 min to 3 min) for document retrieval, reports, and scheduling.\n"
                    "Enabled real-time text and voice support using WebSockets, with VAD (TensorFlow), Whisper STT, and PCM capture with 44.1 kHz to 16 kHz downsampling for dual interaction modes.\n"
                    "Generated documents, meeting schedules, and Excel outputs via MCP, while using LangChain for 3 in-app tasks such as summarization."
                ),
            },
            {
                "name": "Video Analytics",
                "location": "Gurugram, HR, India",
                "link": "",
                "highlights": (
                    "Created video pipeline for RTSP live streams and recordings up to 1 hour, lowering processing cost 50% from 100 to 50 units versus real time.\n"
                    "Orchestrated frame processor, publisher, and ML services as 3+ FastAPI microservices with queue-based communication.\n"
                    "Assembled 10+ event pipelines like person tracking, face recognition, and gender detection, with a footfall insights panel for retail."
                ),
            },
        ],
        "skills": [
            {"category": "Languages", "values": "Python, JavaScript, SQL"},
            {"category": "Frameworks", "values": "FastAPI, Django, Flask, React"},
            {"category": "Cloud & DevOps", "values": "AWS, Docker, Git, Linux"},
            {"category": "Other", "values": "RAG, LLM, LangChain, LangGraph, MCP, Redis, MySQL, MongoDB, Prometheus, Grafana"},
        ],
        "extraQuestions": [
            {"question": "Years of experience", "answer": "3+"},
            {"question": "Current CTC", "answer": "Share when needed"},
        ],
        "referenceResumeId": "",
        "resumeMeta": {
            "resumeName": "subrat_singh_resume",
            "owner": username or "user",
        },
    }


def _profile_store_defaults() -> dict:
    return {"profiles": {}}


def _load_profile_store() -> dict:
    if not PROFILE_CONFIG_PATH.exists():
        PROFILE_CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
        data = _profile_store_defaults()
        PROFILE_CONFIG_PATH.write_text(json.dumps(data, indent=2), encoding="utf-8")
        return data
    try:
        parsed = json.loads(PROFILE_CONFIG_PATH.read_text(encoding="utf-8"))
        return parsed if isinstance(parsed, dict) else _profile_store_defaults()
    except Exception:  # noqa: BLE001
        return _profile_store_defaults()


def _save_profile_store(store: dict) -> None:
    PROFILE_CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
    PROFILE_CONFIG_PATH.write_text(json.dumps(store, indent=2, ensure_ascii=False), encoding="utf-8")


def _merge_profile_config(defaults: dict, incoming: dict) -> dict:
    merged = dict(defaults)
    for key, default_value in defaults.items():
        value = incoming.get(key) if isinstance(incoming, dict) else None
        if isinstance(default_value, dict):
            merged[key] = dict(default_value)
            if isinstance(value, dict):
                for inner_key in default_value.keys():
                    merged[key][inner_key] = str(value.get(inner_key, default_value[inner_key]) or "")
        elif isinstance(default_value, list):
            if isinstance(value, list):
                clean_items = []
                for item in value:
                    if isinstance(item, dict):
                        clean_items.append({k: str(v or "") for k, v in item.items()})
                merged[key] = clean_items
            else:
                merged[key] = default_value
        else:
            merged[key] = str(value if value is not None else default_value)
    return merged


def _get_user_profile_config(user) -> dict:
    store = _load_profile_store()
    username = str(getattr(user, "username", "") or f"user_{getattr(user, 'id', 'unknown')}")
    profiles = store.get("profiles")
    if not isinstance(profiles, dict):
        profiles = {}
        store["profiles"] = profiles
    existing = profiles.get(username) if isinstance(profiles.get(username), dict) else {}
    merged = _merge_profile_config(_default_profile_config(username), existing)
    if merged != existing:
        profiles[username] = merged
        _save_profile_store(store)
    return merged


def _set_user_profile_config(user, payload: dict) -> dict:
    store = _load_profile_store()
    username = str(getattr(user, "username", "") or f"user_{getattr(user, 'id', 'unknown')}")
    profiles = store.get("profiles")
    if not isinstance(profiles, dict):
        profiles = {}
        store["profiles"] = profiles
    merged = _merge_profile_config(_default_profile_config(username), payload if isinstance(payload, dict) else {})
    profiles[username] = merged
    _save_profile_store(store)
    return merged

def _extract_bullets_from_html(value: str):
    """
    Try to extract bullet lines from saved rich HTML (ul/li or plain text).
    Returns list[str] bullets with tags stripped.
    """
    import re

    raw = str(value or "")
    if not raw.strip():
        return []

    # Convert list items into line breaks
    raw = re.sub(r"</li>\s*<li[^>]*>", "\n", raw, flags=re.I)
    raw = raw.replace("</li>", "\n")
    raw = re.sub(r"<li[^>]*>", "", raw, flags=re.I)

    text = _plain_text_from_html(raw)
    lines = [ln.strip() for ln in re.split(r"[\n\r]+", text) if ln.strip()]

    bullets = []
    for ln in lines:
        # Handle "- " / "•" bullets or already-separated lines
        cleaned = ln.lstrip("-• ").strip()
        if cleaned:
            bullets.append(cleaned)
    return bullets


def _bullet_length_score(length: int) -> int:
    """
    Ideal bullet: 50-100 chars.
    Penalize shorter than 50 and longer than 100.
    """
    l = int(length or 0)
    if l <= 0:
        return 0
    if 50 <= l <= 100:
        return 100
    if l < 50:
        # 0..49 => 10..90 (gentle ramp)
        return max(10, min(90, round((l / 50) * 90)))
    # l > 100
    if l <= 160:
        # 101..160 => 98..50
        return max(50, round(100 - ((l - 100) / 60) * 50))
    return 40


def _score_bullets(bullets):
    """
    Returns (score_0_100, notes_dict)
    Requirements:
    - At least 3 bullets per item (experience/project)
    - Bullet length ideal: 50-100
    - Prefer quantified bullets (numbers) for experience/projects
    """
    import re

    b = [str(x).strip() for x in (bullets or []) if str(x).strip()]
    if not b:
        return 0, {
            "count": 0,
            "count_score": 0,
            "length_score": 0,
            "numbers_score": 0,
        }

    count = len(b)
    if count >= 3:
        count_score = 100
    else:
        count_score = round((count / 3) * 70)  # 1->23, 2->47, 3->70 then boosted below
        count_score = max(10, min(70, count_score))

    # Average length score
    length_scores = [_bullet_length_score(len(x)) for x in b]
    length_score = round(sum(length_scores) / len(length_scores)) if length_scores else 0

    # Quantification: % bullets containing any digit
    with_numbers = [x for x in b if re.search(r"\d", x)]
    numbers_score = round((len(with_numbers) / len(b)) * 100) if b else 0

    # Weighted
    total = round(count_score * 0.4 + length_score * 0.4 + numbers_score * 0.2)
    # If 3+ bullets, allow count_score to be perfect.
    if count >= 3:
        total = round(100 * 0.1 + total * 0.9)
    return total, {
        "count": count,
        "count_score": count_score,
        "length_score": length_score,
        "numbers_score": numbers_score,
    }

def _has_rich_content(html: str) -> bool:
    text = _plain_text_from_html(html or "")
    return bool(text.strip())


def _mandatory_sections_multiplier(resume: Resume):
    """
    Mandatory sections for ATS scoring:
    - Skills
    - Education
    - Experience
    - Projects

    Returns (multiplier_0_to_1, notes)
    """
    import re

    builder = resume.builder_data or {}
    text = str(resume.original_text or "")

    def has_heading(name: str) -> bool:
        if not text.strip():
            return False
        return bool(re.search(rf"^\s*{re.escape(name)}\b", text, flags=re.I | re.M))

    skills_ok = False
    if builder:
        skills_ok = _has_rich_content(builder.get("skills") or "")
    if not skills_ok:
        skills_ok = has_heading("skills")

    edu_ok = False
    if builder:
        edus = builder.get("educations") or []
        edu_ok = any(str(e.get("institution") or "").strip() for e in edus)
    if not edu_ok:
        edu_ok = has_heading("education")

    exp_ok = False
    if builder:
        exps = builder.get("experiences") or []
        exp_ok = any(str(e.get("company") or "").strip() for e in exps) or any(_has_rich_content(e.get("highlights") or "") for e in exps)
    if not exp_ok:
        exp_ok = has_heading("experience")

    proj_ok = False
    if builder:
        projs = builder.get("projects") or []
        proj_ok = any(str(p.get("name") or "").strip() for p in projs) or any(_has_rich_content(p.get("highlights") or "") for p in projs)
    if not proj_ok:
        proj_ok = has_heading("projects") or has_heading("project")

    missing = []
    if not skills_ok:
        missing.append("Skills")
    if not edu_ok:
        missing.append("Education")
    if not exp_ok:
        missing.append("Experience")
    if not proj_ok:
        missing.append("Projects")

    # Penalties: skills/education heavier, experience/projects slightly lighter.
    score = 100
    if not skills_ok:
        score -= 30
    if not edu_ok:
        score -= 30
    if not exp_ok:
        score -= 20
    if not proj_ok:
        score -= 20
    score = max(0, min(100, score))

    notes = ""
    if missing:
        notes = f"Missing mandatory sections: {', '.join(missing)}."
    return score / 100.0, notes

def _link_adjustment(resume: Resume):
    """
    Small ATS adjustment based on presence of parsable links.
    - 2+ links: +5
    - 1 link: +2
    - 0 links: -5
    Returns (adjustment_int, note)
    """
    import re

    builder = resume.builder_data or {}
    links = builder.get("links") or []

    def is_link_like(value: str) -> bool:
        v = str(value or "").strip()
        if not v:
            return False
        # Accept full URLs and common domain-style strings (github.com/user)
        if re.search(r"^https?://", v, flags=re.I):
            return True
        if re.search(r"\b([a-z0-9-]+\.)+[a-z]{2,}(/|$)", v, flags=re.I):
            return True
        return False

    count = 0
    for item in links:
        if isinstance(item, dict) and is_link_like(item.get("url")):
            count += 1

    # Fallback: scan original_text for URLs if builder links not present.
    if count == 0:
        text = str(resume.original_text or "")
        urls = re.findall(r"https?://[^\s)]+", text, flags=re.I)
        count = len(urls)

    if count >= 2:
        return 5, "Links: 2+ detected (+5)."
    if count == 1:
        return 2, "Links: 1 detected (+2)."
    return -5, "Links: none detected (-5)."


class HomeView(APIView):
    def get(self, request):
        return Response(
            {
                'message': 'Resume ATS Analyzer API',
                'health': '/api/health/',
            }
        )


class HealthView(APIView):
    def get(self, request):
        return Response({'status': 'ok'})


class SignupView(APIView):
    def post(self, request):
        serializer = SignupSerializer(data=request.data)
        if serializer.is_valid():
            serializer.save()
            return Response({'message': 'User created'}, status=status.HTTP_201_CREATED)
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)


class ResumeParseView(APIView):
    parser_classes = [MultiPartParser, FormParser]

    def post(self, request):
        uploaded_file = (
            request.FILES.get('file')
            or request.FILES.get('pdf')
            or request.FILES.get('resume')
        )
        if not uploaded_file:
            return Response({'detail': 'Please upload a PDF file.'}, status=status.HTTP_400_BAD_REQUEST)

        name = str(getattr(uploaded_file, 'name', '') or '').lower()
        content_type = str(getattr(uploaded_file, 'content_type', '') or '').lower()
        if not name.endswith('.pdf') and content_type not in {'application/pdf', 'application/x-pdf'}:
            return Response({'detail': 'Only PDF files are supported.'}, status=status.HTTP_400_BAD_REQUEST)

        try:
            parsed = parse_resume_pdf(uploaded_file)
        except Exception as exc:
            return Response(
                {'detail': f'Could not parse PDF: {exc}'},
                status=status.HTTP_400_BAD_REQUEST,
            )

        return Response(parsed, status=status.HTTP_200_OK)


class ProfileView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        return Response(
            {
                'id': request.user.id,
                'username': request.user.username,
                'email': request.user.email,
            }
        )


class ProfileConfigView(APIView):
    permission_classes = [IsAuthenticated]
    parser_classes = [JSONParser]

    def get(self, request):
        return Response(_get_user_profile_config(request.user))

    def put(self, request):
        saved = _set_user_profile_config(request.user, request.data if isinstance(request.data, dict) else {})
        return Response(saved)


class JobRoleListCreateView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        roles = JobRole.objects.filter(user=request.user)
        serializer = JobRoleSerializer(roles, many=True)
        return Response(serializer.data)

    def post(self, request):
        serializer = JobRoleSerializer(data=request.data)
        if serializer.is_valid():
            serializer.save(user=request.user)
            return Response(serializer.data, status=status.HTTP_201_CREATED)
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)


class ResumeListCreateView(APIView):
    permission_classes = [IsAuthenticated]

    def _apply_default_resume(self, user, resume):
        if not getattr(resume, 'is_default', False):
            return
        Resume.objects.filter(user=user).exclude(id=resume.id).update(is_default=False)

    def get(self, request):
        # Always return the latest 6 resumes (do not de-dupe by title).
        qs = Resume.objects.filter(user=request.user).order_by('-updated_at', '-created_at')[:6]
        serializer = ResumeSerializer(qs, many=True)
        return Response(serializer.data)

    def post(self, request):
        serializer = ResumeSerializer(data=request.data)
        if serializer.is_valid():
            title = (serializer.validated_data.get('title') or '').strip()
            if not title:
                return Response({'title': ['This field may not be blank.']}, status=status.HTTP_400_BAD_REQUEST)

            incoming_builder = serializer.validated_data.get("builder_data") or {}
            incoming_text = (serializer.validated_data.get("original_text") or "").strip()
            if not incoming_text and incoming_builder:
                incoming_text = _builder_data_to_text(incoming_builder)

            created = serializer.save(user=request.user, original_text=incoming_text or serializer.validated_data.get("original_text") or "")
            self._apply_default_resume(request.user, created)

            # Enforce max 6 resumes by deleting older ones (by updated_at/created_at).
            keep_ids = list(
                Resume.objects.filter(user=request.user)
                .order_by('-updated_at', '-created_at')
                .values_list('id', flat=True)[:6]
            )
            default_id = (
                Resume.objects.filter(user=request.user, is_default=True)
                .order_by('-updated_at', '-created_at')
                .values_list('id', flat=True)
                .first()
            )
            if default_id and default_id not in keep_ids and keep_ids:
                keep_ids = keep_ids[:-1] + [default_id]
            Resume.objects.filter(user=request.user).exclude(id__in=keep_ids).delete()

            return Response(ResumeSerializer(created).data, status=status.HTTP_201_CREATED)
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)


class ResumeDetailView(APIView):
    permission_classes = [IsAuthenticated]

    def _apply_default_resume(self, user, resume):
        if not getattr(resume, 'is_default', False):
            return
        Resume.objects.filter(user=user).exclude(id=resume.id).update(is_default=False)

    def get_object(self, request, resume_id):
        return Resume.objects.get(id=resume_id, user=request.user)

    def get(self, request, resume_id):
        try:
            resume = self.get_object(request, resume_id)
        except Resume.DoesNotExist:
            return Response({'detail': 'Resume not found.'}, status=status.HTTP_404_NOT_FOUND)
        serializer = ResumeSerializer(resume)
        return Response(serializer.data)

    def put(self, request, resume_id):
        try:
            resume = self.get_object(request, resume_id)
        except Resume.DoesNotExist:
            return Response({'detail': 'Resume not found.'}, status=status.HTTP_404_NOT_FOUND)

        serializer = ResumeSerializer(resume, data=request.data, partial=True)
        if serializer.is_valid():
            updated = serializer.save()
            self._apply_default_resume(request.user, updated)
            return Response(serializer.data)
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

    def delete(self, request, resume_id):
        try:
            resume = self.get_object(request, resume_id)
        except Resume.DoesNotExist:
            return Response({'detail': 'Resume not found.'}, status=status.HTTP_404_NOT_FOUND)
        resume.delete()
        return Response(status=status.HTTP_204_NO_CONTENT)


class ResumeAnalysisListView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        analyses = ResumeAnalysis.objects.filter(user=request.user)
        resume_id = request.query_params.get('resume_id')
        if resume_id:
            analyses = analyses.filter(resume_id=resume_id)
        serializer = ResumeAnalysisSerializer(analyses, many=True)
        return Response(serializer.data)


class TailorResumeView(APIView):
    permission_classes = [AllowAny]
    parser_classes = [MultiPartParser, FormParser]

    def _to_bool(self, value, default=False):
        if isinstance(value, bool):
            return value
        if value is None:
            return default
        return str(value).strip().lower() in {'1', 'true', 'yes', 'on'}

    def _enforce_resume_limit(self, user):
        keep_ids = list(
            Resume.objects.filter(user=user)
            .order_by('-updated_at', '-created_at')
            .values_list('id', flat=True)[:6]
        )
        default_id = (
            Resume.objects.filter(user=user, is_default=True)
            .order_by('-updated_at', '-created_at')
            .values_list('id', flat=True)
            .first()
        )
        if default_id and default_id not in keep_ids and keep_ids:
            keep_ids = keep_ids[:-1] + [default_id]
        Resume.objects.filter(user=user).exclude(id__in=keep_ids).delete()

    def _pick_base_builder(self, request_builder, forced_resume, matched_resume, latest_resume):
        if forced_resume and isinstance(forced_resume.builder_data, dict):
            cleaned_forced = sanitize_builder_data(forced_resume.builder_data)
            if builder_has_substance(cleaned_forced):
                return cleaned_forced

        if isinstance(request_builder, dict):
            cleaned_request = sanitize_builder_data(request_builder)
            if builder_has_substance(cleaned_request):
                return cleaned_request

        if matched_resume and isinstance(matched_resume.builder_data, dict):
            cleaned_matched = sanitize_builder_data(matched_resume.builder_data)
            if builder_has_substance(cleaned_matched):
                return cleaned_matched

        if latest_resume and isinstance(latest_resume.builder_data, dict):
            cleaned_latest = sanitize_builder_data(latest_resume.builder_data)
            if builder_has_substance(cleaned_latest):
                return cleaned_latest

        return sanitize_builder_data(request_builder or {})

    def _tailored_title(self, jd_text, fallback_title="Tailored Resume"):
        first_line = str(jd_text or "").strip().splitlines()[0:1]
        if first_line:
            line = str(first_line[0]).strip()
            if len(line) > 80:
                line = line[:80].rsplit(" ", 1)[0].strip() or line[:80]
            if line:
                return f"Tailored - {line}"
        return fallback_title

    def _apply_tailor_mode(self, base_builder, tailored_builder, tailor_mode: str):
        base = sanitize_builder_data(base_builder or {})
        tailored = sanitize_builder_data(tailored_builder or {})
        mode = str(tailor_mode or 'partial').strip().lower()

        if mode == 'complete':
            return tailored

        merged = dict(base)
        merged['skills'] = tailored.get('skills') or base.get('skills', '')

        if mode in {'summary_experience', 'almost_complete'}:
            merged['summaryEnabled'] = bool(tailored.get('summaryEnabled', base.get('summaryEnabled')))
            merged['summaryHeading'] = tailored.get('summaryHeading') or base.get('summaryHeading', 'Summary')
            merged['summary'] = tailored.get('summary') or base.get('summary', '')
            merged['experiences'] = tailored.get('experiences') or base.get('experiences', [])
            merged['role'] = tailored.get('role') or base.get('role', '')

        return sanitize_builder_data(merged)

    def post(self, request):
        is_authenticated = bool(getattr(request.user, "is_authenticated", False))
        jd_text = str(request.data.get('job_description') or '').strip()
        if len(jd_text) < 40:
            return Response({'detail': 'Please paste a fuller job description.'}, status=status.HTTP_400_BAD_REQUEST)
        job_role = str(request.data.get('job_role') or '').strip()
        company_name = str(request.data.get('company_name') or '').strip()
        job_title = str(request.data.get('job_title') or '').strip()
        job_id = str(request.data.get('job_id') or '').strip()
        job_url = str(request.data.get('job_url') or '').strip()
        force_rewrite = self._to_bool(request.data.get('force_rewrite'), default=False)
        tailor_mode = str(request.data.get('tailor_mode') or 'partial').strip().lower()
        if tailor_mode not in {'partial', 'summary_experience', 'almost_complete', 'complete'}:
            tailor_mode = 'partial'
        ai_model = str(request.data.get('ai_model') or '').strip()
        if ai_model and ai_model not in ALLOWED_AI_MODELS:
            return Response({'detail': 'Invalid AI model selected.'}, status=status.HTTP_400_BAD_REQUEST)

        # Strict requirement: do not proceed without AI API configured.
        if not os.getenv('OPENAI_API_KEY', '').strip():
            return Response(
                {'detail': 'AI tailoring is required. Configure OPENAI_API_KEY on backend to continue.'},
                status=status.HTTP_400_BAD_REQUEST,
            )

        incoming_critical = request.data.get('critical_keywords')
        critical_keywords = []
        if isinstance(incoming_critical, str):
            raw = incoming_critical.strip()
            if raw.startswith('['):
                try:
                    parsed = json.loads(raw)
                    if isinstance(parsed, list):
                        critical_keywords = [str(x).strip().lower() for x in parsed if str(x).strip()]
                except json.JSONDecodeError:
                    critical_keywords = [x.strip().lower() for x in re.split(r"[,\n;]", incoming_critical) if x.strip()]
            else:
                critical_keywords = [x.strip().lower() for x in re.split(r"[,\n;]", incoming_critical) if x.strip()]
        elif isinstance(incoming_critical, list):
            critical_keywords = [str(x).strip().lower() for x in incoming_critical if str(x).strip()]

        min_match = request.data.get('min_match', 0.70)
        max_match = request.data.get('max_match', 0.80)
        preview_only = self._to_bool(request.data.get('preview_only'), default=True)
        try:
            min_match = float(min_match)
            max_match = float(max_match)
        except Exception:  # noqa: BLE001
            min_match, max_match = 0.70, 0.80

        min_match = max(0.0, min(1.0, min_match))
        max_match = max(min_match, min(1.0, max_match))

        request_builder = request.data.get('builder_data')
        if isinstance(request_builder, str):
            try:
                request_builder = json.loads(request_builder)
            except json.JSONDecodeError:
                request_builder = {}
        if not isinstance(request_builder, dict):
            request_builder = {}
        request_builder = sanitize_builder_data(request_builder)
        reference_resume = None
        reference_resume_id = str(request.data.get('reference_resume_id') or '').strip()
        if is_authenticated and reference_resume_id:
            try:
                reference_resume = Resume.objects.get(id=int(reference_resume_id), user=request.user)
            except Exception:  # noqa: BLE001
                reference_resume = None

        keywords, keyword_ai_used, keyword_note = extract_keywords_ai(jd_text, model_override=ai_model or None)
        # Continue with heuristic fallback keywords when AI is temporarily unavailable.
        if critical_keywords:
            merged = []
            seen = set()
            for kw in [*critical_keywords, *keywords]:
                key = str(kw or '').strip().lower()
                if not key or key in seen:
                    continue
                seen.add(key)
                merged.append(key)
            keywords = merged[:80]
        if not keywords:
            return Response({'detail': 'Could not extract JD keywords.'}, status=status.HTTP_400_BAD_REQUEST)

        resumes = list(Resume.objects.filter(user=request.user).order_by('-updated_at', '-created_at')) if is_authenticated else []
        best = find_best_resume_match(keywords, resumes)
        latest_resume = resumes[0] if resumes else None

        if is_authenticated and (not force_rewrite) and (reference_resume is None) and best.resume and min_match <= best.score <= max_match:
            payload = ResumeSerializer(best.resume).data
            return Response(
                {
                    'mode': 'matched_existing',
                    'resume': payload,
                    'keywords': keywords,
                    'matched_keywords': best.matched_keywords,
                    'match_score': round(best.score, 4),
                    'used_ai_keywords': bool(keyword_ai_used),
                    'keyword_note': keyword_note,
                    'preview_only': bool(preview_only),
                },
                status=status.HTTP_200_OK,
            )

        if not is_authenticated:
            preview_only = True

        base_builder = self._pick_base_builder(request_builder, reference_resume, best.resume, latest_resume)
        ai_payload, ai_used, ai_note = tailor_resume_with_ai(
            base_builder,
            jd_text,
            keywords,
            job_role=job_role,
            model_override=ai_model or None,
        )
        if not ai_used:
            return Response(
                {'detail': f'AI rewrite failed. {ai_note or "Please try again."}'},
                status=status.HTTP_502_BAD_GATEWAY,
            )
        tailored_builder = build_tailored_builder(
            base_builder,
            ai_payload,
            keywords,
            jd_text=jd_text,
            model_override=ai_model or None,
        )
        tailored_builder = self._apply_tailor_mode(base_builder, tailored_builder, tailor_mode)
        tailored_builder = _restrict_to_reference_sections(base_builder, tailored_builder)
        plain_text = builder_data_to_text(tailored_builder)
        title = self._tailored_title(jd_text, fallback_title=(base_builder.get('resumeTitle') or 'Tailored Resume'))

        if preview_only:
            preview_resume = {
                'id': None,
                'title': title,
                'original_text': plain_text,
                'optimized_text': '',
                'builder_data': tailored_builder,
                'is_default': False,
                'status': 'optimized',
                'created_at': None,
                'updated_at': None,
            }
            return Response(
                {
                    'mode': 'preview_new',
                    'resume': preview_resume,
                    'keywords': keywords,
                    'matched_keywords': best.matched_keywords,
                    'match_score': round(best.score, 4),
                    'used_ai_keywords': bool(keyword_ai_used),
                    'used_ai_rewrite': bool(ai_used),
                    'keyword_note': keyword_note,
                    'rewrite_note': ai_note,
                    'tailor_mode': tailor_mode,
                    'preview_only': True,
                    'anonymous_mode': not is_authenticated,
                },
                status=status.HTTP_200_OK,
            )

        if not is_authenticated:
            return Response(
                {'detail': 'Saving tailored resumes requires authentication. Use preview mode only.'},
                status=status.HTTP_401_UNAUTHORIZED,
            )

        created = Resume.objects.create(
            user=request.user,
            title=title,
            original_text=plain_text,
            builder_data=tailored_builder,
            status='optimized',
        )
        TailoredJobRun.objects.create(
            user=request.user,
            resume=created,
            company_name=company_name,
            job_title=job_title or job_role,
            job_id=job_id,
            job_url=job_url,
            jd_text=jd_text,
            match_score=float(round(best.score, 4)),
            keywords=keywords,
        )
        self._enforce_resume_limit(request.user)

        return Response(
            {
                'mode': 'created_new',
                'resume': ResumeSerializer(created).data,
                'keywords': keywords,
                'matched_keywords': best.matched_keywords,
                'match_score': round(best.score, 4),
                'used_ai_keywords': bool(keyword_ai_used),
                'used_ai_rewrite': bool(ai_used),
                'keyword_note': keyword_note,
                'rewrite_note': ai_note,
                'tailor_mode': tailor_mode,
                'preview_only': False,
            },
            status=status.HTTP_201_CREATED,
        )


class OptimizeResumeQualityView(APIView):
    permission_classes = [IsAuthenticated]
    parser_classes = [JSONParser, MultiPartParser, FormParser]

    def _to_bool(self, value, default=False):
        if isinstance(value, bool):
            return value
        if value is None:
            return default
        return str(value).strip().lower() in {'1', 'true', 'yes', 'on'}

    def post(self, request):
        if not os.getenv('OPENAI_API_KEY', '').strip():
            return Response(
                {'detail': 'AI optimization is required. Configure OPENAI_API_KEY on backend to continue.'},
                status=status.HTTP_400_BAD_REQUEST,
            )

        ai_model = str(request.data.get('ai_model') or '').strip()
        if ai_model and ai_model not in ALLOWED_AI_MODELS:
            return Response({'detail': 'Invalid AI model selected.'}, status=status.HTTP_400_BAD_REQUEST)

        request_builder = request.data.get('builder_data')
        if isinstance(request_builder, str):
            try:
                request_builder = json.loads(request_builder)
            except json.JSONDecodeError:
                request_builder = {}
        if not isinstance(request_builder, dict):
            request_builder = {}
        request_builder = sanitize_builder_data(request_builder)
        if not builder_has_substance(request_builder):
            return Response({'detail': 'Upload or import a resume first.'}, status=status.HTTP_400_BAD_REQUEST)

        ai_payload, ai_used, ai_note = optimize_existing_resume_quality_ai(
            request_builder,
            model_override=ai_model or None,
        )
        if not ai_used:
            return Response(
                {'detail': f'AI quality optimization failed. {ai_note or "Please try again."}'},
                status=status.HTTP_502_BAD_GATEWAY,
            )
        optimized_builder = build_quality_optimized_builder(
            request_builder,
            ai_payload,
            model_override=ai_model or None,
        )
        optimized_builder = _restrict_to_reference_sections(request_builder, optimized_builder)
        plain_text = builder_data_to_text(optimized_builder)
        title = str(optimized_builder.get('resumeTitle') or 'Optimized Resume').strip() or 'Optimized Resume'
        preview_only = self._to_bool(request.data.get('preview_only'), default=True)

        preview_resume = {
            'id': None,
            'title': title,
            'original_text': plain_text,
            'optimized_text': '',
            'builder_data': optimized_builder,
            'is_default': False,
            'status': 'optimized',
            'created_at': None,
            'updated_at': None,
        }
        return Response(
            {
                'mode': 'optimized_quality_preview',
                'resume': preview_resume,
                'preview_only': bool(preview_only),
            },
            status=status.HTTP_200_OK,
        )


class ExportAtsPdfLocalView(APIView):
    permission_classes = [IsAuthenticated]
    parser_classes = [JSONParser]

    def post(self, request):
        builder_data = request.data.get("builder_data")
        if isinstance(builder_data, str):
            try:
                builder_data = json.loads(builder_data)
            except Exception:  # noqa: BLE001
                builder_data = {}
        if not isinstance(builder_data, dict):
            builder_data = {}
        builder_data = sanitize_builder_data(builder_data)

        html_text = str(request.data.get("html") or "").strip()
        if len(html_text) < 40:
            return Response({"detail": "Missing ATS HTML payload for PDF export."}, status=status.HTTP_400_BAD_REQUEST)

        file_name = _default_pdf_filename(builder_data)
        output_path = _pick_local_pdf_path(file_name)

        ok, note = _render_pdf_from_html(html_text, output_path)
        if not ok:
            return Response(
                {"detail": f"Could not generate local PDF. {note}"},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )

        return Response(
            {
                "saved_path": str(output_path),
                "file_name": output_path.name,
            },
            status=status.HTTP_200_OK,
        )


class AutofillAnswersView(APIView):
    permission_classes = [AllowAny]
    parser_classes = [JSONParser]

    def post(self, request):
        questions = request.data.get("questions")
        if not isinstance(questions, list):
            return Response({"detail": "questions must be a list."}, status=status.HTTP_400_BAD_REQUEST)
        safe_questions = [str(q or "").strip() for q in questions if str(q or "").strip()]
        if not safe_questions:
            return Response({"answers": []}, status=status.HTTP_200_OK)

        profile_context = str(request.data.get("profile_context") or "").strip()
        answers, error = _openai_question_answers(safe_questions[:80], profile_context=profile_context)
        if error:
            return Response({"detail": error}, status=status.HTTP_502_BAD_GATEWAY)
        return Response({"answers": answers}, status=status.HTTP_200_OK)


class TailoredJobRunListView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        runs = TailoredJobRun.objects.filter(user=request.user).order_by('-created_at')[:50]
        return Response(TailoredJobRunSerializer(runs, many=True).data, status=status.HTTP_200_OK)


class ApplicationTrackingListCreateView(APIView):
    permission_classes = [IsAuthenticated]
    parser_classes = [JSONParser]

    def get(self, request):
        rows = ApplicationTracking.objects.filter(user=request.user).order_by('-applied_date', '-created_at')[:300]
        return Response(ApplicationTrackingSerializer(rows, many=True).data, status=status.HTTP_200_OK)

    def post(self, request):
        serializer = ApplicationTrackingSerializer(data=request.data)
        if serializer.is_valid():
            created = serializer.save(user=request.user)
            return Response(ApplicationTrackingSerializer(created).data, status=status.HTTP_201_CREATED)
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)


class ApplicationTrackingDetailView(APIView):
    permission_classes = [IsAuthenticated]
    parser_classes = [JSONParser]

    def _get_object(self, request, tracking_id):
        return ApplicationTracking.objects.get(id=tracking_id, user=request.user)

    def put(self, request, tracking_id):
        try:
            row = self._get_object(request, tracking_id)
        except ApplicationTracking.DoesNotExist:
            return Response({'detail': 'Tracking row not found.'}, status=status.HTTP_404_NOT_FOUND)
        serializer = ApplicationTrackingSerializer(row, data=request.data, partial=True)
        if serializer.is_valid():
            updated = serializer.save()
            return Response(ApplicationTrackingSerializer(updated).data, status=status.HTTP_200_OK)
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

    def delete(self, request, tracking_id):
        try:
            row = self._get_object(request, tracking_id)
        except ApplicationTracking.DoesNotExist:
            return Response({'detail': 'Tracking row not found.'}, status=status.HTTP_404_NOT_FOUND)
        row.delete()
        return Response(status=status.HTTP_204_NO_CONTENT)


class CompanyListCreateView(APIView):
    permission_classes = [IsAuthenticated]
    parser_classes = [JSONParser]

    def get(self, request):
        rows = Company.objects.filter(user=request.user).order_by('name')
        return Response(CompanySerializer(rows, many=True).data, status=status.HTTP_200_OK)

    def post(self, request):
        serializer = CompanySerializer(data=request.data)
        if serializer.is_valid():
            created = serializer.save(user=request.user)
            return Response(CompanySerializer(created).data, status=status.HTTP_201_CREATED)
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)


class CompanyDetailView(APIView):
    permission_classes = [IsAuthenticated]
    parser_classes = [JSONParser]

    def _get_object(self, request, company_id):
        return Company.objects.get(id=company_id, user=request.user)

    def put(self, request, company_id):
        try:
            row = self._get_object(request, company_id)
        except Company.DoesNotExist:
            return Response({'detail': 'Company not found.'}, status=status.HTTP_404_NOT_FOUND)
        serializer = CompanySerializer(row, data=request.data, partial=True)
        if serializer.is_valid():
            updated = serializer.save()
            return Response(CompanySerializer(updated).data, status=status.HTTP_200_OK)
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

    def delete(self, request, company_id):
        try:
            row = self._get_object(request, company_id)
        except Company.DoesNotExist:
            return Response({'detail': 'Company not found.'}, status=status.HTTP_404_NOT_FOUND)
        row.delete()
        return Response(status=status.HTTP_204_NO_CONTENT)


class EmployeeListCreateView(APIView):
    permission_classes = [IsAuthenticated]
    parser_classes = [JSONParser]

    def get(self, request):
        company_id = request.query_params.get('company_id')
        rows = Employee.objects.filter(user=request.user)
        if company_id:
            rows = rows.filter(company_id=company_id)
        rows = rows.order_by('name')
        return Response(EmployeeSerializer(rows, many=True).data, status=status.HTTP_200_OK)

    def post(self, request):
        payload = dict(request.data or {})
        company_id = payload.get('company')
        if not company_id:
            return Response({'company': ['This field is required.']}, status=status.HTTP_400_BAD_REQUEST)
        try:
            company = Company.objects.get(id=company_id, user=request.user)
        except Company.DoesNotExist:
            return Response({'company': ['Company not found.']}, status=status.HTTP_400_BAD_REQUEST)
        serializer = EmployeeSerializer(data=payload)
        if serializer.is_valid():
            created = serializer.save(user=request.user, company=company)
            return Response(EmployeeSerializer(created).data, status=status.HTTP_201_CREATED)
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)


class EmployeeDetailView(APIView):
    permission_classes = [IsAuthenticated]
    parser_classes = [JSONParser]

    def _get_object(self, request, employee_id):
        return Employee.objects.get(id=employee_id, user=request.user)

    def put(self, request, employee_id):
        try:
            row = self._get_object(request, employee_id)
        except Employee.DoesNotExist:
            return Response({'detail': 'Employee not found.'}, status=status.HTTP_404_NOT_FOUND)

        payload = dict(request.data or {})
        company_id = payload.get('company')
        if company_id:
            try:
                company = Company.objects.get(id=company_id, user=request.user)
            except Company.DoesNotExist:
                return Response({'company': ['Company not found.']}, status=status.HTTP_400_BAD_REQUEST)
            payload['company'] = company.id

        serializer = EmployeeSerializer(row, data=payload, partial=True)
        if serializer.is_valid():
            updated = serializer.save()
            return Response(EmployeeSerializer(updated).data, status=status.HTTP_200_OK)
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

    def delete(self, request, employee_id):
        try:
            row = self._get_object(request, employee_id)
        except Employee.DoesNotExist:
            return Response({'detail': 'Employee not found.'}, status=status.HTTP_404_NOT_FOUND)
        row.delete()
        return Response(status=status.HTTP_204_NO_CONTENT)


class JobListCreateView(APIView):
    permission_classes = [IsAuthenticated]
    parser_classes = [JSONParser]

    def get(self, request):
        company_id = request.query_params.get('company_id')
        rows = Job.objects.filter(user=request.user)
        if company_id:
            rows = rows.filter(company_id=company_id)
        rows = rows.order_by('-date_of_posting', '-created_at')
        return Response(JobSerializer(rows, many=True).data, status=status.HTTP_200_OK)

    def post(self, request):
        payload = dict(request.data or {})
        company_id = payload.get('company')
        if not company_id:
            return Response({'company': ['This field is required.']}, status=status.HTTP_400_BAD_REQUEST)
        try:
            company = Company.objects.get(id=company_id, user=request.user)
        except Company.DoesNotExist:
            return Response({'company': ['Company not found.']}, status=status.HTTP_400_BAD_REQUEST)
        serializer = JobSerializer(data=payload)
        if serializer.is_valid():
            created = serializer.save(user=request.user, company=company)
            return Response(JobSerializer(created).data, status=status.HTTP_201_CREATED)
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)


class JobDetailView(APIView):
    permission_classes = [IsAuthenticated]
    parser_classes = [JSONParser]

    def _get_object(self, request, job_id):
        return Job.objects.get(id=job_id, user=request.user)

    def put(self, request, job_id):
        try:
            row = self._get_object(request, job_id)
        except Job.DoesNotExist:
            return Response({'detail': 'Job not found.'}, status=status.HTTP_404_NOT_FOUND)
        serializer = JobSerializer(row, data=request.data, partial=True)
        if serializer.is_valid():
            updated = serializer.save()
            return Response(JobSerializer(updated).data, status=status.HTTP_200_OK)
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

    def delete(self, request, job_id):
        try:
            row = self._get_object(request, job_id)
        except Job.DoesNotExist:
            return Response({'detail': 'Job not found.'}, status=status.HTTP_404_NOT_FOUND)
        row.delete()
        return Response(status=status.HTTP_204_NO_CONTENT)


class RunAnalysisView(APIView):
    permission_classes = [IsAuthenticated]

    def _structure_score(self, resume: Resume):
        """
        Checks experience/projects structure:
        - Every experience/project should have bullet points.
        - At least 3 bullets per experience/project.
        - Bullet length ideally 50-100 chars (penalize <50 and >100).
        - Prefer quantified bullets (numbers).
        Returns (structure_score_0_100, feedback_notes)
        """
        builder = resume.builder_data or {}
        experiences = builder.get("experiences") or []
        projects = builder.get("projects") or []

        exp_scores = []
        exp_notes = []
        for exp in experiences:
            company = str(exp.get("company") or "").strip() or "Experience"
            bullets = _extract_bullets_from_html(exp.get("highlights") or "")
            score, meta = _score_bullets(bullets)
            exp_scores.append(score)
            if meta["count"] < 3:
                exp_notes.append(f"{company}: only {meta['count']} bullets (need 3+).")
            if meta["length_score"] < 70:
                exp_notes.append(f"{company}: bullets are too short/long (aim 50-100 chars).")
            if meta["numbers_score"] < 40:
                exp_notes.append(f"{company}: add more numbers (%, time, users, revenue, latency).")

        proj_scores = []
        proj_notes = []
        for proj in projects:
            name = str(proj.get("name") or "").strip() or "Project"
            bullets = _extract_bullets_from_html(proj.get("highlights") or "")
            score, meta = _score_bullets(bullets)
            proj_scores.append(score)
            if meta["count"] < 3:
                proj_notes.append(f"{name}: only {meta['count']} bullets (need 3+).")
            if meta["length_score"] < 70:
                proj_notes.append(f"{name}: bullets are too short/long (aim 50-100 chars).")

        exp_score = round(sum(exp_scores) / len(exp_scores)) if exp_scores else 0
        proj_score = round(sum(proj_scores) / len(proj_scores)) if proj_scores else 0
        structure = round(exp_score * 0.7 + proj_score * 0.3)

        notes = []
        if not experiences:
            notes.append("No experiences found. Add experience entries with 3+ bullets each.")
        if experiences and exp_score < 70:
            notes.append("Experience bullets need improvement (3+ bullets each, 50-100 chars, add numbers).")
        if projects and proj_score < 70:
            notes.append("Project bullets need improvement (3+ bullets each, 50-100 chars).")
        if exp_notes:
            notes.extend(exp_notes[:6])
        if proj_notes:
            notes.extend(proj_notes[:6])
        return structure, " ".join(notes).strip()

    def _length_score(self, resume: Resume) -> int:
        text = str(resume.original_text or "").strip()
        length = len(text)
        if length >= 800:
            return 100
        if length >= 600:
            return 85
        if length >= 450:
            return 70
        if length >= 300:
            return 55
        return 35

    def post(self, request):
        resume_id = request.data.get('resume_id')
        job_role_id = request.data.get('job_role_id')
        extra_keywords = request.data.get('keywords')
        profiles = request.data.get('profiles') or request.data.get('keyword_profiles') or []
        profile_keywords = request.data.get('profile_keywords') or request.data.get('profileKeywords') or None

        if not resume_id:
            return Response(
                {'detail': 'resume_id is required.'},
                status=status.HTTP_400_BAD_REQUEST,
            )

        try:
            resume = Resume.objects.get(id=resume_id, user=request.user)
        except Resume.DoesNotExist:
            return Response({'detail': 'Resume not found.'}, status=status.HTTP_404_NOT_FOUND)

        job_role = None
        if job_role_id:
            try:
                job_role = JobRole.objects.get(id=job_role_id, user=request.user)
            except JobRole.DoesNotExist:
                return Response({'detail': 'Job role not found.'}, status=status.HTTP_404_NOT_FOUND)

        resume_text = (resume.original_text or '').lower()

        # Normalize profiles to list[str]
        if isinstance(profiles, str):
            profiles = [p.strip().lower() for p in profiles.split(",") if p.strip()]
        elif isinstance(profiles, list):
            profiles = [str(p).strip().lower() for p in profiles if str(p).strip()]
        else:
            profiles = []

        # Optional per-request overrides from UI.
        overrides = {}
        if isinstance(profile_keywords, dict):
            for key, val in profile_keywords.items():
                k = str(key).strip().lower()
                if k not in PRESET_KEYWORDS:
                    continue
                if isinstance(val, str):
                    overrides[k] = [x.strip().lower() for x in val.split(",") if x.strip()]
                elif isinstance(val, list):
                    overrides[k] = [str(x).strip().lower() for x in val if str(x).strip()]

        selected_any = bool(profiles) or bool(extra_keywords) or bool(job_role)

        # Keyword mode (user selected presets/custom keywords/job role)
        keywords = []
        if job_role:
            keywords.extend([str(k).strip().lower() for k in (job_role.required_keywords or []) if str(k).strip()])

        for p in profiles:
            if p in PRESET_KEYWORDS:
                keywords.extend(overrides.get(p) or PRESET_KEYWORDS[p])

        # Only include custom keywords if explicitly requested via "custom" profile,
        # or if no profiles are provided but keywords are.
        allow_custom = (not profiles and bool(extra_keywords)) or ("custom" in profiles)
        if allow_custom and extra_keywords:
            if isinstance(extra_keywords, str):
                extra = [k.strip().lower() for k in extra_keywords.split(",") if k.strip()]
            elif isinstance(extra_keywords, list):
                extra = [str(k).strip().lower() for k in extra_keywords if str(k).strip()]
            else:
                extra = []
            keywords.extend(extra)

        # De-dup while preserving order
        seen = set()
        deduped = []
        for kw in keywords:
            if kw in seen:
                continue
            seen.add(kw)
            deduped.append(kw)
        keywords = deduped

        structure_score, structure_note = self._structure_score(resume)
        mandatory_mult, mandatory_note = _mandatory_sections_multiplier(resume)
        link_adj, link_note = _link_adjustment(resume)

        if not selected_any or not keywords:
            # Basic mode: no keyword profiles selected
            length_score = self._length_score(resume)
            ats_score = round(length_score * 0.3 + structure_score * 0.7)
            matched_keywords, missing_keywords, keyword_score = [], [], 0
            feedback = (
                f"Basic checks used. Length score: {length_score}. Structure score: {structure_score}. "
                f"{structure_note} Aim for ~800+ characters and 3+ bullets per experience/project with 50-100 chars each."
            ).strip()
        else:
            matched_keywords = [kw for kw in keywords if kw in resume_text]
            missing_keywords = [kw for kw in keywords if kw not in matched_keywords]
            keyword_score = round((len(matched_keywords) / len(keywords)) * 100) if keywords else 0
            ats_score = round(keyword_score * 0.6 + structure_score * 0.4)
            feedback = (
                f"Keyword score: {keyword_score}%. Structure score: {structure_score}. "
                f"Matched {len(matched_keywords)} of {len(keywords)} keywords. "
                f"{structure_note} Add missing keywords with measurable achievements."
            ).strip()

        # Apply link adjustment before mandatory section penalty.
        ats_score = max(0, min(100, int(ats_score) + int(link_adj)))
        feedback = f"{feedback} {link_note}".strip()

        if mandatory_mult < 1:
            ats_score = round(ats_score * mandatory_mult)
            if mandatory_note:
                feedback = f"{feedback} {mandatory_note} ATS reduced due to missing sections."

        analysis = ResumeAnalysis.objects.create(
            user=request.user,
            resume=resume,
            resume_title=(resume.title or ''),
            job_role=job_role,
            ats_score=ats_score,
            keyword_score=keyword_score,
            matched_keywords=matched_keywords,
            missing_keywords=missing_keywords,
            ai_feedback=feedback,
        )

        if ats_score >= 75:
            resume.status = 'optimized'
            resume.optimized_text = resume.original_text
            resume.save(update_fields=['status', 'optimized_text', 'updated_at'])

        serializer = ResumeAnalysisSerializer(analysis)
        return Response(serializer.data, status=status.HTTP_201_CREATED)
