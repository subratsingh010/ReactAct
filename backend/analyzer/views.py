import json
import os
import re
import subprocess
import tempfile
import urllib.error
import urllib.request
from datetime import datetime
from pathlib import Path

from django.db.models import Q
from rest_framework import status
from rest_framework.parsers import FormParser, JSONParser, MultiPartParser
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView
from django.utils import timezone

from .pdf_parser import parse_resume_pdf
from .company_utils import normalize_company_name, resolve_company_for_job
from .models import Resume, TailoredResume, MailTracking, MailTrackingEvent, Company, Employee, Job, Tracking, TrackingAction, UserProfile, Achievement, Interview, Location
from .serializers import (
    ResumeSerializer,
    TailoredResumeSerializer,
    SignupSerializer,
    MailTrackingSerializer,
    CompanySerializer,
    EmployeeSerializer,
    JobSerializer,
    UserProfileSerializer,
    AchievementSerializer,
    InterviewSerializer,
    LocationSerializer,
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


def _paginate_queryset(queryset, request, default_page_size=10, max_page_size=100):
    page_raw = request.query_params.get('page', '1')
    page_size_raw = request.query_params.get('page_size', str(default_page_size))
    try:
        page = max(1, int(page_raw))
    except Exception:
        page = 1
    try:
        page_size = int(page_size_raw)
    except Exception:
        page_size = default_page_size
    page_size = max(1, min(page_size, max_page_size))

    total = queryset.count()
    total_pages = max(1, (total + page_size - 1) // page_size)
    if page > total_pages:
        page = total_pages
    start = (page - 1) * page_size
    end = start + page_size

    return queryset[start:end], {
        'count': total,
        'page': page,
        'page_size': page_size,
        'total_pages': total_pages,
    }

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
        profile, _ = UserProfile.objects.get_or_create(
            user=request.user,
            defaults={
                'full_name': request.user.username,
                'email': request.user.email or '',
            },
        )
        return Response(
            {
                'id': request.user.id,
                'username': request.user.username,
                'email': request.user.email,
                'profile': UserProfileSerializer(profile).data,
            }
        )


class ProfileInfoView(APIView):
    permission_classes = [IsAuthenticated]
    parser_classes = [JSONParser]

    def _get_or_create(self, request):
        profile, _ = UserProfile.objects.get_or_create(
            user=request.user,
            defaults={
                'full_name': request.user.username,
                'email': request.user.email or '',
            },
        )
        if not profile.full_name:
            profile.full_name = request.user.username
        if not profile.email:
            profile.email = request.user.email or ''
        profile.save(update_fields=['full_name', 'email', 'updated_at'])
        return profile

    def get(self, request):
        profile = self._get_or_create(request)
        return Response(UserProfileSerializer(profile).data, status=status.HTTP_200_OK)

    def put(self, request):
        profile = self._get_or_create(request)
        payload = dict(request.data or {})
        location_ref_raw = str(payload.get('location_ref') or '').strip()
        if location_ref_raw:
            try:
                location = Location.objects.get(id=location_ref_raw)
                payload['location_ref'] = location.id
                payload['location'] = location.name
            except Location.DoesNotExist:
                return Response({'detail': 'Location not found.'}, status=status.HTTP_400_BAD_REQUEST)
        serializer = UserProfileSerializer(profile, data=payload, partial=True)
        if serializer.is_valid():
            updated = serializer.save()
            return Response(UserProfileSerializer(updated).data, status=status.HTTP_200_OK)
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)


class AchievementListCreateView(APIView):
    permission_classes = [IsAuthenticated]
    parser_classes = [JSONParser]

    def get(self, request):
        rows = Achievement.objects.filter(user=request.user).order_by('-created_at')
        return Response(AchievementSerializer(rows, many=True).data, status=status.HTTP_200_OK)

    def post(self, request):
        serializer = AchievementSerializer(data=request.data)
        if serializer.is_valid():
            created = serializer.save(user=request.user)
            return Response(AchievementSerializer(created).data, status=status.HTTP_201_CREATED)
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)


class AchievementDetailView(APIView):
    permission_classes = [IsAuthenticated]
    parser_classes = [JSONParser]

    def _get_object(self, request, achievement_id):
        return Achievement.objects.get(id=achievement_id, user=request.user)

    def put(self, request, achievement_id):
        try:
            row = self._get_object(request, achievement_id)
        except Achievement.DoesNotExist:
            return Response({'detail': 'Achievement not found.'}, status=status.HTTP_404_NOT_FOUND)
        serializer = AchievementSerializer(row, data=request.data, partial=True)
        if serializer.is_valid():
            updated = serializer.save()
            return Response(AchievementSerializer(updated).data, status=status.HTTP_200_OK)
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

    def delete(self, request, achievement_id):
        try:
            row = self._get_object(request, achievement_id)
        except Achievement.DoesNotExist:
            return Response({'detail': 'Achievement not found.'}, status=status.HTTP_404_NOT_FOUND)
        row.hard_delete()
        return Response(status=status.HTTP_204_NO_CONTENT)


class InterviewListCreateView(APIView):
    permission_classes = [IsAuthenticated]
    parser_classes = [JSONParser]
    STAGE_LABELS = {
        'received_call': 'Received Call',
        'assignment': 'Assignment',
        'round_1': 'Round 1',
        'round_2': 'Round 2',
        'round_3': 'Round 3',
        'round_4': 'Round 4',
        'round_5': 'Round 5',
        'round_6': 'Round 6',
        'round_7': 'Round 7',
        'round_8': 'Round 8',
        'landed_job': 'Landed Job',
    }
    ACTION_LABELS = {
        'active': 'Active',
        'landed_job': 'Landed Job',
        'rejected': 'Rejected',
        'hold': 'Hold',
        'no_response': 'No Response',
        'no_feedback': 'No Feedback',
        'ghosted': 'Ghosted',
        'skipped': 'Skipped',
    }

    def _has_duplicate(self, request, company_name, job_role, exclude_id=None):
        company_key = str(company_name or '').strip().lower()
        job_key = str(job_role or '').strip().lower()
        if not company_key or not job_key:
            return False
        rows = Interview.objects.filter(user=request.user, company_key=company_key, job_role_key=job_key)
        if exclude_id:
            rows = rows.exclude(id=exclude_id)
        return rows.exists()

    def _round_value(self, stage):
        raw = str(stage or '').strip().lower()
        if raw.startswith('round_'):
            suffix = raw.replace('round_', '', 1)
            if suffix.isdigit():
                value = int(suffix)
                if 1 <= value <= 8:
                    return value
        return 0

    def _append_milestone_event(self, row, stage, action):
        events = row.milestone_events if isinstance(row.milestone_events, list) else []
        stage_key = str(stage or row.stage or 'received_call').strip().lower() or 'received_call'
        action_key = str(action or row.action or 'active').strip().lower() or 'active'
        stage_label = self.STAGE_LABELS.get(stage_key, stage_key.replace('_', ' ').title())
        action_label = self.ACTION_LABELS.get(action_key, action_key.replace('_', ' ').title())
        events.append({
            'stage': stage_key,
            'action': action_key,
            'label': f'{stage_label} | {action_label}',
            'at': timezone.now().isoformat(),
        })
        row.milestone_events = events[-10:]
        row.save(update_fields=['milestone_events', 'updated_at'])

    def _update_last_milestone_action(self, row, action):
        events = row.milestone_events if isinstance(row.milestone_events, list) else []
        if not events:
            self._append_milestone_event(row, row.stage, action)
            return
        action_key = str(action or row.action or 'active').strip().lower() or 'active'
        action_label = self.ACTION_LABELS.get(action_key, action_key.replace('_', ' ').title())
        last = dict(events[-1] or {})
        stage_key = str(last.get('stage') or row.stage or 'received_call').strip().lower() or 'received_call'
        stage_label = self.STAGE_LABELS.get(stage_key, stage_key.replace('_', ' ').title())
        last['action'] = action_key
        last['label'] = f'{stage_label} | {action_label}'
        events[-1] = last
        row.milestone_events = events[-10:]
        row.save(update_fields=['milestone_events', 'updated_at'])

    def get(self, request):
        rows = Interview.objects.filter(user=request.user).order_by('-updated_at', '-created_at')
        return Response(InterviewSerializer(rows, many=True).data, status=status.HTTP_200_OK)

    def post(self, request):
        payload = dict(request.data or {})
        payload['action'] = str(payload.get('action') or payload.get('section') or 'active').strip().lower() or 'active'
        raw_job_id = str(payload.get('job') or '').strip()
        selected_job = None
        if raw_job_id:
            try:
                selected_job = Job.objects.get(id=raw_job_id, user=request.user, is_removed=False)
            except Job.DoesNotExist:
                return Response({'detail': 'Selected job not found.'}, status=status.HTTP_400_BAD_REQUEST)
        company_name = str(payload.get('company_name') or '').strip()
        job_role = str(payload.get('job_role') or '').strip()
        job_code = str(payload.get('job_code') or '').strip()
        location_ref_raw = str(payload.get('location_ref') or '').strip()
        selected_location = None
        if location_ref_raw:
            try:
                selected_location = Location.objects.get(id=location_ref_raw)
            except Location.DoesNotExist:
                return Response({'detail': 'Location not found.'}, status=status.HTTP_400_BAD_REQUEST)
        if selected_job:
            if not company_name and selected_job.company_id:
                company_name = str(selected_job.company.name or '').strip()
            if not job_role:
                job_role = str(selected_job.role or '').strip() or job_role
            if not job_code:
                job_code = str(selected_job.job_id or '').strip() or job_code
        if self._has_duplicate(request, company_name, job_role):
            return Response({'detail': 'Interview with same company and job already exists.'}, status=status.HTTP_400_BAD_REQUEST)
        stage = str(payload.get('stage') or 'received_call').strip()
        requested_round = self._round_value(stage)
        if requested_round > 1:
            return Response({'detail': 'You must complete previous rounds in order before selecting this round.'}, status=status.HTTP_400_BAD_REQUEST)
        payload['company_name'] = company_name
        payload['job_role'] = job_role
        payload['job_code'] = job_code
        if selected_location:
            payload['location_ref'] = selected_location.id
        if selected_job:
            payload['job'] = selected_job.id
        serializer = InterviewSerializer(data=payload)
        if serializer.is_valid():
            created = serializer.save(user=request.user, max_round_reached=requested_round if requested_round else 0)
            self._append_milestone_event(created, created.stage, created.action)
            return Response(InterviewSerializer(created).data, status=status.HTTP_201_CREATED)
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)


class InterviewDetailView(APIView):
    permission_classes = [IsAuthenticated]
    parser_classes = [JSONParser]
    STAGE_LABELS = InterviewListCreateView.STAGE_LABELS
    ACTION_LABELS = InterviewListCreateView.ACTION_LABELS

    def _get_object(self, request, interview_id):
        return Interview.objects.get(id=interview_id, user=request.user)

    def _round_value(self, stage):
        raw = str(stage or '').strip().lower()
        if raw.startswith('round_'):
            suffix = raw.replace('round_', '', 1)
            if suffix.isdigit():
                value = int(suffix)
                if 1 <= value <= 8:
                    return value
        return 0

    def _append_milestone_event(self, row, stage, action):
        events = row.milestone_events if isinstance(row.milestone_events, list) else []
        stage_key = str(stage or row.stage or 'received_call').strip().lower() or 'received_call'
        action_key = str(action or row.action or 'active').strip().lower() or 'active'
        stage_label = self.STAGE_LABELS.get(stage_key, stage_key.replace('_', ' ').title())
        action_label = self.ACTION_LABELS.get(action_key, action_key.replace('_', ' ').title())
        events.append({
            'stage': stage_key,
            'action': action_key,
            'label': f'{stage_label} | {action_label}',
            'at': timezone.now().isoformat(),
        })
        row.milestone_events = events[-10:]
        row.save(update_fields=['milestone_events', 'updated_at'])

    def _update_last_milestone_action(self, row, action):
        events = row.milestone_events if isinstance(row.milestone_events, list) else []
        if not events:
            self._append_milestone_event(row, row.stage, action)
            return
        action_key = str(action or row.action or 'active').strip().lower() or 'active'
        action_label = self.ACTION_LABELS.get(action_key, action_key.replace('_', ' ').title())
        last = dict(events[-1] or {})
        stage_key = str(last.get('stage') or row.stage or 'received_call').strip().lower() or 'received_call'
        stage_label = self.STAGE_LABELS.get(stage_key, stage_key.replace('_', ' ').title())
        last['action'] = action_key
        last['label'] = f'{stage_label} | {action_label}'
        events[-1] = last
        row.milestone_events = events[-10:]
        row.save(update_fields=['milestone_events', 'updated_at'])

    def put(self, request, interview_id):
        try:
            row = self._get_object(request, interview_id)
        except Interview.DoesNotExist:
            return Response({'detail': 'Interview not found.'}, status=status.HTTP_404_NOT_FOUND)
        prev_stage = row.stage
        prev_action = row.action
        payload = dict(request.data or {})
        stage_explicitly_sent = 'stage' in payload
        payload['action'] = str(payload.get('action') or payload.get('section') or row.action or 'active').strip().lower() or 'active'
        raw_job_id = str(payload.get('job') or '').strip()
        selected_job = row.job if row.job_id else None
        if raw_job_id:
            try:
                selected_job = Job.objects.get(id=raw_job_id, user=request.user, is_removed=False)
            except Job.DoesNotExist:
                return Response({'detail': 'Selected job not found.'}, status=status.HTTP_400_BAD_REQUEST)
        company_name = payload.get('company_name', row.company_name)
        job_role = payload.get('job_role', row.job_role)
        job_code = payload.get('job_code', row.job_code)
        location_ref_raw = str(payload.get('location_ref') or '').strip()
        selected_location = row.location_ref if getattr(row, 'location_ref_id', None) else None
        if location_ref_raw:
            try:
                selected_location = Location.objects.get(id=location_ref_raw)
            except Location.DoesNotExist:
                return Response({'detail': 'Location not found.'}, status=status.HTTP_400_BAD_REQUEST)
        if selected_job:
            if not str(company_name or '').strip() and selected_job.company_id:
                company_name = selected_job.company.name
            if not str(job_role or '').strip():
                job_role = selected_job.role or job_role
            if not str(job_code or '').strip():
                job_code = selected_job.job_id or job_code
        company_key = str(company_name or '').strip().lower()
        job_key = str(job_role or '').strip().lower()
        duplicate = Interview.objects.filter(user=request.user, company_key=company_key, job_role_key=job_key).exclude(id=row.id).exists()
        if duplicate:
            return Response({'detail': 'Interview with same company and job already exists.'}, status=status.HTTP_400_BAD_REQUEST)
        next_stage = payload.get('stage', row.stage)
        stage_changed = str(next_stage or '').strip().lower() != str(row.stage or '').strip().lower()
        requested_round = self._round_value(next_stage)
        current_round = self._round_value(row.stage)
        base_max_round = max(int(row.max_round_reached or 0), current_round)
        if stage_changed and requested_round and requested_round <= base_max_round:
            return Response({'detail': 'Round stage must move forward. You cannot select same or lower round again.'}, status=status.HTTP_400_BAD_REQUEST)
        if requested_round and requested_round > (base_max_round + 1):
            return Response({'detail': 'You must complete previous rounds in order before selecting this round.'}, status=status.HTTP_400_BAD_REQUEST)
        next_max_round = max(base_max_round, requested_round)
        payload['company_name'] = str(company_name or '').strip()
        payload['job_role'] = str(job_role or '').strip()
        payload['job_code'] = str(job_code or '').strip()
        payload['job'] = selected_job.id if selected_job else None
        payload['location_ref'] = selected_location.id if selected_location else None
        serializer = InterviewSerializer(row, data=payload, partial=True)
        if serializer.is_valid():
            updated = serializer.save(max_round_reached=next_max_round)
            stage_changed = str(updated.stage or '').strip().lower() != str(prev_stage or '').strip().lower()
            action_changed = str(updated.action or '').strip().lower() != str(prev_action or '').strip().lower()
            requested_non_round_repeat = (
                stage_explicitly_sent
                and not requested_round
                and not stage_changed
            )
            if stage_changed or requested_non_round_repeat:
                self._append_milestone_event(updated, updated.stage, updated.action)
            elif action_changed:
                self._update_last_milestone_action(updated, updated.action)
            return Response(InterviewSerializer(updated).data, status=status.HTTP_200_OK)
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

    def delete(self, request, interview_id):
        try:
            row = self._get_object(request, interview_id)
        except Interview.DoesNotExist:
            return Response({'detail': 'Interview not found.'}, status=status.HTTP_404_NOT_FOUND)
        row.hard_delete()
        return Response(status=status.HTTP_204_NO_CONTENT)


class ProfileConfigView(APIView):
    permission_classes = [IsAuthenticated]
    parser_classes = [JSONParser]

    def get(self, request):
        return Response(_get_user_profile_config(request.user))

    def put(self, request):
        saved = _set_user_profile_config(request.user, request.data if isinstance(request.data, dict) else {})
        return Response(saved)


class LocationListView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        rows = Location.objects.all().order_by('name')
        return Response(LocationSerializer(rows, many=True).data, status=status.HTTP_200_OK)


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


class TailoredResumeListCreateView(APIView):
    permission_classes = [IsAuthenticated]
    parser_classes = [JSONParser]

    def get(self, request):
        rows = (
            TailoredResume.objects
            .filter(Q(job__user=request.user) | Q(resume__user=request.user))
            .select_related('job', 'resume')
            .order_by('-updated_at', '-created_at')
        )
        job_id = str(request.query_params.get('job_id') or '').strip()
        if job_id:
            rows = rows.filter(job_id=job_id)
        q = str(request.query_params.get('q') or '').strip()
        if q:
            rows = rows.filter(Q(name__icontains=q) | Q(job__job_id__icontains=q) | Q(job__role__icontains=q))
        return Response(TailoredResumeSerializer(rows, many=True).data, status=status.HTTP_200_OK)

    def post(self, request):
        payload = dict(request.data or {})
        name = str(payload.get('name') or '').strip() or 'Tailored Resume'
        builder_data = payload.get('builder_data') or {}
        if isinstance(builder_data, str):
            try:
                builder_data = json.loads(builder_data)
            except Exception:
                builder_data = {}
        if not isinstance(builder_data, dict):
            return Response({'builder_data': ['Invalid payload.']}, status=status.HTTP_400_BAD_REQUEST)

        job = None
        resume = None
        raw_job = str(payload.get('job') or '').strip()
        raw_resume = str(payload.get('resume') or '').strip()
        if raw_job:
            try:
                job = Job.objects.get(id=raw_job, user=request.user)
            except Job.DoesNotExist:
                return Response({'job': ['Job not found.']}, status=status.HTTP_400_BAD_REQUEST)
        if raw_resume:
            try:
                resume = Resume.objects.get(id=raw_resume, user=request.user)
            except Resume.DoesNotExist:
                return Response({'resume': ['Resume not found.']}, status=status.HTTP_400_BAD_REQUEST)

        created = TailoredResume.objects.create(
            job=job,
            resume=resume,
            name=name,
            builder_data=sanitize_builder_data(builder_data),
        )
        return Response(TailoredResumeSerializer(created).data, status=status.HTTP_201_CREATED)


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


class ApplicationTrackingListCreateView(APIView):
    permission_classes = [IsAuthenticated]
    parser_classes = [JSONParser, MultiPartParser, FormParser]

    def _to_bool(self, value, default=False):
        if value is None:
            return default
        if isinstance(value, bool):
            return value
        if isinstance(value, (int, float)):
            return bool(value)
        text = str(value).strip().lower()
        if text in {'true', '1', 'yes', 'y', 'on'}:
            return True
        if text in {'false', '0', 'no', 'n', 'off'}:
            return False
        return default

    def _to_date(self, value):
        raw = str(value or '').strip()
        if not raw:
            return None
        try:
            return datetime.fromisoformat(raw[:10]).date()
        except Exception:
            return None

    def _to_datetime(self, value):
        raw = str(value or '').strip()
        if not raw:
            return None
        try:
            dt = datetime.fromisoformat(raw)
            if timezone.is_naive(dt):
                dt = timezone.make_aware(dt, timezone.get_current_timezone())
            return dt
        except Exception:
            return None

    def _extract_template_fields(self, payload):
        allowed = {'cold_applied', 'referral', 'job_inquire', 'custom'}
        choice = str(payload.get('template_choice') or '').strip().lower()
        subject = str(payload.get('template_subject') or payload.get('custom_subject') or '').strip()
        message = str(payload.get('template_message') or '').strip()
        legacy = str(payload.get('template_name') or '').strip()

        if choice and choice not in allowed:
            choice = ''
        if not choice:
            if legacy in allowed:
                choice = legacy
            elif legacy:
                choice = 'custom'
                message = message or legacy
        if choice == 'custom' and not message and legacy and legacy not in allowed:
            message = legacy
        if not choice:
            choice = 'cold_applied'
        if choice != 'custom':
            subject = ''
            message = ''
        return choice, subject, message

    def _resolve_company(self, request, payload):
        company_id = payload.get('company')
        if company_id:
            try:
                return Company.objects.get(id=company_id, user=request.user)
            except Company.DoesNotExist:
                return None

        company_name = str(payload.get('company_name') or '').strip()
        if not company_name:
            company_name = 'New Company'
        company, _ = Company.objects.get_or_create(user=request.user, name=company_name)
        return company

    def _resolve_job(self, request, company, payload):
        explicit_job_id = payload.get('job')
        if explicit_job_id:
            try:
                return Job.objects.get(id=explicit_job_id, user=request.user, is_removed=False)
            except Job.DoesNotExist:
                return None

        job_code = str(payload.get('job_id') or '').strip()
        if job_code:
            job = Job.objects.filter(
                user=request.user,
                company=company,
                job_id__iexact=job_code,
                is_removed=False,
            ).first()
            if not job:
                job = Job.objects.create(
                    user=request.user,
                    company=company,
                    job_id=job_code,
                    role=str(payload.get('role') or 'Software Developer').strip() or 'Software Developer',
                    job_link=str(payload.get('job_url') or '').strip(),
                )
        else:
            job = Job.objects.create(
                user=request.user,
                company=company,
                job_id=f"JOB-{int(timezone.now().timestamp())}",
                role=str(payload.get('role') or 'Software Developer').strip() or 'Software Developer',
                job_link=str(payload.get('job_url') or '').strip(),
            )

        applied = self._to_date(payload.get('applied_date'))
        posting = self._to_date(payload.get('posting_date'))
        is_open = self._to_bool(payload.get('is_open'), default=not bool(job.is_closed))
        explicit_is_closed = payload.get('is_closed')
        explicit_is_removed = payload.get('is_removed')
        updates = []
        if applied and job.applied_at != applied:
            job.applied_at = applied
            updates.append('applied_at')
        if posting and job.date_of_posting != posting:
            job.date_of_posting = posting
            updates.append('date_of_posting')
        next_closed = self._to_bool(explicit_is_closed, default=not is_open) if explicit_is_closed is not None else (not is_open)
        if job.is_closed != next_closed:
            job.is_closed = next_closed
            updates.append('is_closed')
        if explicit_is_removed is not None:
            next_removed = self._to_bool(explicit_is_removed, default=job.is_removed)
            if job.is_removed != next_removed:
                job.is_removed = next_removed
                updates.append('is_removed')
        if updates:
            updates.append('updated_at')
            job.save(update_fields=updates)
        return job

    def _resolve_resume(self, request, payload):
        resume_id = payload.get('resume')
        raw = str(resume_id or '').strip()
        if not raw:
            return None
        try:
            return Resume.objects.get(id=raw, user=request.user)
        except Resume.DoesNotExist:
            return None

    def _sync_selected_hrs(self, request, tracking, payload):
        selected_ids = payload.get('selected_hr_ids')
        selected_names = payload.get('selected_hrs')
        if hasattr(request.data, 'getlist'):
            id_list = [str(v or '').strip() for v in request.data.getlist('selected_hr_ids') if str(v or '').strip()]
            name_list = [str(v or '').strip() for v in request.data.getlist('selected_hrs') if str(v or '').strip()]
            if id_list:
                selected_ids = id_list
            if name_list:
                selected_names = name_list
        targets = Employee.objects.none()

        if isinstance(selected_ids, str):
            selected_ids = [x.strip() for x in selected_ids.split(',') if x.strip()]
        if isinstance(selected_names, str):
            selected_names = [x.strip() for x in selected_names.split(',') if x.strip()]

        if isinstance(selected_ids, list) and selected_ids:
            targets = Employee.objects.filter(user=request.user, id__in=selected_ids)
        elif isinstance(selected_names, list) and selected_names and tracking.job_id and tracking.job and tracking.job.company_id:
            targets = Employee.objects.filter(
                user=request.user,
                company_id=tracking.job.company_id,
                name__in=[str(name or '').strip() for name in selected_names if str(name or '').strip()],
            )
        if selected_ids is not None or selected_names is not None:
            tracking.selected_hrs.set(targets)

    def _append_action(self, tracking, payload):
        action = payload.get('append_action')
        if not isinstance(action, dict):
            return None

        action_type = str(action.get('type') or '').strip().lower()
        if action_type not in {'fresh', 'followup'}:
            return 'Invalid action type.'
        if action_type == 'followup' and not tracking.actions.filter(action_type='fresh').exists():
            return 'Fresh mail must be done first before follow up.'

        send_mode = str(action.get('send_mode') or 'now').strip().lower()
        mapped_send_mode = 'sent' if send_mode == 'now' else 'scheduled'
        action_at = self._to_datetime(action.get('action_at')) or timezone.now()

        TrackingAction.objects.create(
            tracking=tracking,
            action_type=action_type,
            send_mode=mapped_send_mode,
            action_at=action_at,
        )
        tracking.mail_type = 'followed_up' if action_type == 'followup' else 'fresh'
        if action_type == 'fresh':
            tracking.mailed = True
        tracking.save(update_fields=['mail_type', 'mailed', 'updated_at'])
        return None

    def _serialize_tracking_row(self, tracking, available_hr_map):
        job = tracking.job
        resume = tracking.resume
        tailored_resume = tracking.tailored_resume
        company = job.company if job and job.company_id else None
        mail_tracking = tracking.mail_tracking if tracking.mail_tracking_id else None
        available = available_hr_map.get(company.id if company else None, [])
        selected = list(tracking.selected_hrs.all())
        tailored_rows = []
        oldest_tailored = None
        if job:
            related_tailored = list(job.tailored_resumes.all().order_by('created_at', 'id'))
            tailored_rows = [
                {
                    'id': item.id,
                    'name': str(item.name or '').strip() or f'Tailored Resume #{item.id}',
                    'created_at': item.created_at.isoformat() if item.created_at else None,
                }
                for item in related_tailored
            ]
            if related_tailored:
                oldest = related_tailored[0]
                oldest_tailored = {
                    'id': oldest.id,
                    'name': str(oldest.name or '').strip() or f'Tailored Resume #{oldest.id}',
                    'created_at': oldest.created_at.isoformat() if oldest.created_at else None,
                    'builder_data': oldest.builder_data or {},
                }
        resume_preview = None
        if resume:
            resume_builder = resume.builder_data or {}
            resume_file_url = ''
            if getattr(resume, 'file', None):
                try:
                    resume_file_url = resume.file.url
                except Exception:
                    resume_file_url = ''
            if builder_has_substance(resume_builder) or resume_file_url:
                resume_preview = {
                    'id': resume.id,
                    'title': str(resume.title or '').strip() or f'Resume #{resume.id}',
                    'builder_data': resume_builder,
                    'file_url': resume_file_url,
                }
        tailored_resume_preview = None
        if tailored_resume:
            tailored_builder = tailored_resume.builder_data or {}
            if builder_has_substance(tailored_builder):
                tailored_resume_preview = {
                    'id': tailored_resume.id,
                    'title': str(tailored_resume.name or '').strip() or f'Tailored Resume #{tailored_resume.id}',
                    'builder_data': tailored_builder,
                }
        milestones = [
            {
                'type': item.action_type,
                'mode': item.send_mode,
                'at': item.action_at.isoformat() if item.action_at else '',
            }
            for item in tracking.actions.all().order_by('created_at')[:10]
        ]
        template_choice = str(tracking.template_choice or 'cold_applied').strip() or 'cold_applied'
        template_subject = str(tracking.template_subject or '')
        template_message = str(tracking.template_message or '')
        return {
            'id': tracking.id,
            'company': company.id if company else None,
            'company_name': company.name if company else '',
            'job': job.id if job else None,
            'job_id': job.job_id if job else '',
            'role': job.role if job else '',
            'job_url': job.job_link if job else '',
            'tailored_resumes': tailored_rows,
            'oldest_tailored_resume': oldest_tailored,
            'resume_preview': resume_preview,
            'tailored_resume_preview': tailored_resume_preview,
            'tailored_resume': tailored_resume.id if tailored_resume else None,
            'tailored_resume_name': str(tailored_resume.name or '').strip() if tailored_resume else '',
            'is_closed': bool(job.is_closed) if job else False,
            'is_removed': bool(job.is_removed) if job else False,
            'mailed': bool(tracking.mailed),
            'applied_date': job.applied_at.isoformat() if job and job.applied_at else None,
            'posting_date': job.date_of_posting.isoformat() if job and job.date_of_posting else None,
            'is_open': bool(not bool(job.is_closed) if job else True),
            'available_hrs': [emp.name for emp in available],
            'available_hr_ids': [emp.id for emp in available],
            'selected_hrs': [emp.name for emp in selected],
            'selected_hr_ids': [emp.id for emp in selected],
            'template_choice': template_choice,
            'template_subject': template_subject,
            'template_message': template_message,
            'template_name': (template_message if template_choice == 'custom' else template_choice),
            'mail_type': str(tracking.mail_type or 'fresh'),
            'action': str(tracking.mail_type or 'fresh'),
            'got_replied': bool(mail_tracking.got_replied) if mail_tracking else False,
            'needs_tailored': False,
            'tailoring_scope': '',
            'is_freezed': bool(tracking.is_freezed),
            'freezed_at': tracking.freezed_at.isoformat() if tracking.freezed_at else None,
            'mail_tracking_id': mail_tracking.id if mail_tracking else None,
            'maild_at': mail_tracking.mailed_at.isoformat() if mail_tracking and mail_tracking.mailed_at else None,
            'mailed_at': mail_tracking.mailed_at.isoformat() if mail_tracking and mail_tracking.mailed_at else None,
            'replied_at': mail_tracking.replied_at.isoformat() if mail_tracking and mail_tracking.replied_at else None,
            'milestones': milestones,
            'created_at': tracking.created_at.isoformat() if tracking.created_at else '',
            'updated_at': tracking.updated_at.isoformat() if tracking.updated_at else '',
        }

    def _has_company_mail_pattern(self, company):
        return bool(company and str(getattr(company, 'mail_format', '') or '').strip())

    def get(self, request):
        queryset = (
            Tracking.objects.filter(user=request.user, is_removed=False)
            .select_related('job__company', 'resume', 'tailored_resume', 'mail_tracking')
            .prefetch_related('selected_hrs', 'actions', 'job__tailored_resumes')
            .order_by('-created_at')
        )
        rows, meta = _paginate_queryset(queryset, request, default_page_size=10, max_page_size=100)
        company_ids = {
            row.job.company_id
            for row in rows
            if row.job_id and row.job and row.job.company_id
        }
        employees = Employee.objects.filter(user=request.user, company_id__in=company_ids).order_by('name')
        available_hr_map = {}
        for emp in employees:
            available_hr_map.setdefault(emp.company_id, []).append(emp)

        return Response(
            {
                **meta,
                'results': [self._serialize_tracking_row(row, available_hr_map) for row in rows],
            },
            status=status.HTTP_200_OK,
        )

    def post(self, request):
        payload = request.data or {}
        template_choice, template_subject, template_message = self._extract_template_fields(payload)
        company = self._resolve_company(request, payload)
        if not company:
            return Response({'detail': 'Company not found.'}, status=status.HTTP_400_BAD_REQUEST)
        job = self._resolve_job(request, company, payload)
        if not job:
            return Response({'detail': 'Job not found.'}, status=status.HTTP_400_BAD_REQUEST)
        resume = self._resolve_resume(request, payload)
        if payload.get('resume') not in [None, '', 'null'] and not resume:
            return Response({'detail': 'Resume not found.'}, status=status.HTTP_400_BAD_REQUEST)

        tracking = Tracking.objects.create(
            user=request.user,
            job=job,
            resume=resume,
            template_choice=template_choice,
            template_subject=template_subject,
            template_message=template_message,
            mailed=self._to_bool(payload.get('mailed'), default=False),
            mail_type='fresh',
        )
        tailored_resume_id = str(payload.get('tailored_resume') or '').strip()
        if tailored_resume_id:
            tailored = TailoredResume.objects.filter(id=tailored_resume_id, job=job).first() if job else TailoredResume.objects.filter(id=tailored_resume_id).first()
            if not tailored and job:
                job_tailored = job.tailored_resumes.all().order_by('created_at', 'id')
                tailored = job_tailored.first()
            tracking.tailored_resume = tailored
            tracking.save(update_fields=['tailored_resume', 'updated_at'])
        self._sync_selected_hrs(request, tracking, payload)
        if not self._has_company_mail_pattern(company):
            tracking.hard_delete()
            return Response(
                {'detail': 'Company mail pattern is required to create tracking.'},
                status=status.HTTP_400_BAD_REQUEST,
            )
        action_error = self._append_action(tracking, payload)
        if action_error:
            return Response({'detail': action_error}, status=status.HTTP_400_BAD_REQUEST)

        available = Employee.objects.filter(user=request.user, company_id=company.id).order_by('name')
        available_hr_map = {company.id: list(available)}
        return Response(
            self._serialize_tracking_row(
                Tracking.objects.filter(id=tracking.id).prefetch_related('selected_hrs', 'actions', 'job__tailored_resumes').select_related('job__company', 'resume', 'tailored_resume', 'mail_tracking').first(),
                available_hr_map,
            ),
            status=status.HTTP_201_CREATED,
        )


class ApplicationTrackingDetailView(APIView):
    permission_classes = [IsAuthenticated]
    parser_classes = [JSONParser, MultiPartParser, FormParser]

    def _get_object(self, request, tracking_id):
        return Tracking.objects.get(id=tracking_id, user=request.user, is_removed=False)

    def _get_object_any(self, request, tracking_id):
        return Tracking.objects.get(id=tracking_id, user=request.user)

    def _is_hard_delete(self, request):
        mode = str(request.query_params.get('delete_mode') or '').strip().lower()
        hard = str(request.query_params.get('hard') or '').strip().lower()
        return mode == 'hard' or hard in {'1', 'true', 'yes', 'y'}

    def _to_bool(self, value, default=False):
        if value is None:
            return default
        if isinstance(value, bool):
            return value
        text = str(value).strip().lower()
        if text in {'true', '1', 'yes', 'y', 'on'}:
            return True
        if text in {'false', '0', 'no', 'n', 'off'}:
            return False
        return default

    def _has_company_mail_pattern(self, company):
        return bool(company and str(getattr(company, 'mail_format', '') or '').strip())

    def _to_date(self, value):
        raw = str(value or '').strip()
        if not raw:
            return None
        try:
            return datetime.fromisoformat(raw[:10]).date()
        except Exception:
            return None

    def _to_datetime(self, value):
        raw = str(value or '').strip()
        if not raw:
            return None
        try:
            dt = datetime.fromisoformat(raw)
            if timezone.is_naive(dt):
                dt = timezone.make_aware(dt, timezone.get_current_timezone())
            return dt
        except Exception:
            return None

    def _extract_template_fields(self, payload):
        allowed = {'cold_applied', 'referral', 'job_inquire', 'custom'}
        choice = str(payload.get('template_choice') or '').strip().lower()
        subject = str(payload.get('template_subject') or payload.get('custom_subject') or '').strip()
        message = str(payload.get('template_message') or '').strip()
        legacy = str(payload.get('template_name') or '').strip()

        if choice and choice not in allowed:
            choice = ''
        if not choice:
            if legacy in allowed:
                choice = legacy
            elif legacy:
                choice = 'custom'
                message = message or legacy
        if choice == 'custom' and not message and legacy and legacy not in allowed:
            message = legacy
        if not choice:
            choice = 'cold_applied'
        if choice != 'custom':
            subject = ''
            message = ''
        return choice, subject, message

    def _serialize_tracking_row(self, row):
        company = row.job.company if row.job_id and row.job and row.job.company_id else None
        resume = row.resume if row.resume_id else None
        tailored_resume = row.tailored_resume if getattr(row, 'tailored_resume_id', None) else None
        available = []
        if company:
            available = list(Employee.objects.filter(user=row.user, company_id=company.id).order_by('name'))
        selected = list(row.selected_hrs.all())
        tailored_rows = []
        oldest_tailored = None
        if row.job_id and row.job:
            related_tailored = list(row.job.tailored_resumes.all().order_by('created_at', 'id'))
            tailored_rows = [
                {
                    'id': item.id,
                    'name': str(item.name or '').strip() or f'Tailored Resume #{item.id}',
                    'created_at': item.created_at.isoformat() if item.created_at else None,
                }
                for item in related_tailored
            ]
            if related_tailored:
                oldest = related_tailored[0]
                oldest_tailored = {
                    'id': oldest.id,
                    'name': str(oldest.name or '').strip() or f'Tailored Resume #{oldest.id}',
                    'created_at': oldest.created_at.isoformat() if oldest.created_at else None,
                    'builder_data': oldest.builder_data or {},
                }
        resume_preview = None
        if resume:
            resume_builder = resume.builder_data or {}
            resume_file_url = ''
            if getattr(resume, 'file', None):
                try:
                    resume_file_url = resume.file.url
                except Exception:
                    resume_file_url = ''
            if builder_has_substance(resume_builder) or resume_file_url:
                resume_preview = {
                    'id': resume.id,
                    'title': str(resume.title or '').strip() or f'Resume #{resume.id}',
                    'builder_data': resume_builder,
                    'file_url': resume_file_url,
                }
        tailored_resume_preview = None
        if tailored_resume:
            tailored_builder = tailored_resume.builder_data or {}
            if builder_has_substance(tailored_builder):
                tailored_resume_preview = {
                    'id': tailored_resume.id,
                    'title': str(tailored_resume.name or '').strip() or f'Tailored Resume #{tailored_resume.id}',
                    'builder_data': tailored_builder,
                }
        milestones = [
            {
                'type': item.action_type,
                'mode': item.send_mode,
                'at': item.action_at.isoformat() if item.action_at else '',
            }
            for item in row.actions.all().order_by('created_at')[:10]
        ]
        selected_employees = [
            {
                'id': emp.id,
                'name': str(emp.name or '').strip(),
                'email': str(emp.email or '').strip(),
                'department': str(emp.department or '').strip(),
                'role': str(emp.JobRole or '').strip(),
                'contact_number': str(emp.contact_number or '').strip(),
            }
            for emp in selected
        ]
        events_query = Q(tracking=row)
        if row.mail_tracking_id:
            events_query = events_query | Q(tracking__isnull=True, mail_tracking_id=row.mail_tracking_id)
        event_rows = (
            MailTrackingEvent.objects
            .filter(events_query)
            .select_related('employee')
            .order_by('created_at')
        )
        mail_events = []
        for item in event_rows:
            payload = item.raw_payload if isinstance(item.raw_payload, dict) else {}
            subject = str(payload.get('subject') or payload.get('mail_subject') or payload.get('generated_subject') or '').strip()
            message = str(payload.get('body') or payload.get('mail_body') or payload.get('generated_body') or payload.get('message') or '').strip()
            receiver = str(payload.get('to_email') or payload.get('recipient_email') or payload.get('receiver') or '').strip()
            mail_events.append(
                {
                    'id': item.id,
                    'employee_id': item.employee_id,
                    'employee_name': str(item.employee.name or '').strip() if item.employee_id and item.employee else '',
                    'mail_type': str(item.mail_type or '').strip(),
                    'send_mode': str(item.send_mode or '').strip(),
                    'action_at': item.action_at.isoformat() if item.action_at else '',
                    'got_replied': bool(item.got_replied),
                    'notes': str(item.notes or '').strip(),
                    'subject': subject,
                    'message': message,
                    'to_email': receiver,
                }
            )
        template_choice = str(row.template_choice or 'cold_applied').strip() or 'cold_applied'
        template_subject = str(row.template_subject or '')
        template_message = str(row.template_message or '')
        return {
            'id': row.id,
            'company': company.id if company else None,
            'company_name': company.name if company else '',
            'job': row.job.id if row.job_id and row.job else None,
            'job_id': row.job.job_id if row.job_id and row.job else '',
            'role': row.job.role if row.job_id and row.job else '',
            'job_url': row.job.job_link if row.job_id and row.job else '',
            'tailored_resumes': tailored_rows,
            'oldest_tailored_resume': oldest_tailored,
            'resume_preview': resume_preview,
            'tailored_resume_preview': tailored_resume_preview,
            'tailored_resume': tailored_resume.id if tailored_resume else None,
            'tailored_resume_name': str(tailored_resume.name or '').strip() if tailored_resume else '',
            'is_closed': bool(row.job.is_closed) if row.job_id and row.job else False,
            'is_removed': bool(row.job.is_removed) if row.job_id and row.job else False,
            'mailed': bool(row.mailed),
            'applied_date': row.job.applied_at.isoformat() if row.job_id and row.job and row.job.applied_at else None,
            'posting_date': row.job.date_of_posting.isoformat() if row.job_id and row.job and row.job.date_of_posting else None,
            'is_open': bool(not row.job.is_closed) if row.job_id and row.job else True,
            'available_hrs': [emp.name for emp in available],
            'available_hr_ids': [emp.id for emp in available],
            'selected_hrs': [emp.name for emp in selected],
            'selected_hr_ids': [emp.id for emp in selected],
            'selected_employees': selected_employees,
            'template_choice': template_choice,
            'template_subject': template_subject,
            'template_message': template_message,
            'template_name': (template_message if template_choice == 'custom' else template_choice),
            'mail_events': mail_events,
            'mail_type': str(row.mail_type or 'fresh'),
            'action': str(row.mail_type or 'fresh'),
            'got_replied': bool(row.mail_tracking.got_replied) if row.mail_tracking_id and row.mail_tracking else False,
            'needs_tailored': False,
            'tailoring_scope': '',
            'is_freezed': bool(row.is_freezed),
            'freezed_at': row.freezed_at.isoformat() if row.freezed_at else None,
            'mail_tracking_id': row.mail_tracking.id if row.mail_tracking_id else None,
            'maild_at': row.mail_tracking.mailed_at.isoformat() if row.mail_tracking_id and row.mail_tracking and row.mail_tracking.mailed_at else None,
            'mailed_at': row.mail_tracking.mailed_at.isoformat() if row.mail_tracking_id and row.mail_tracking and row.mail_tracking.mailed_at else None,
            'replied_at': row.mail_tracking.replied_at.isoformat() if row.mail_tracking_id and row.mail_tracking and row.mail_tracking.replied_at else None,
            'milestones': milestones,
            'created_at': row.created_at.isoformat() if row.created_at else '',
            'updated_at': row.updated_at.isoformat() if row.updated_at else '',
        }

    def get(self, request, tracking_id):
        try:
            row = (
                Tracking.objects
                .filter(id=tracking_id, user=request.user, is_removed=False)
                .select_related('job__company', 'mail_tracking', 'resume', 'tailored_resume')
                .prefetch_related('selected_hrs', 'actions', 'job__tailored_resumes')
                .first()
            )
            if not row:
                raise Tracking.DoesNotExist
        except Tracking.DoesNotExist:
            return Response({'detail': 'Tracking row not found.'}, status=status.HTTP_404_NOT_FOUND)
        return Response(self._serialize_tracking_row(row), status=status.HTTP_200_OK)

    def put(self, request, tracking_id):
        try:
            row = self._get_object(request, tracking_id)
        except Tracking.DoesNotExist:
            return Response({'detail': 'Tracking row not found.'}, status=status.HTTP_404_NOT_FOUND)

        payload = request.data or {}
        job = row.job

        company_id = payload.get('company')
        company_name = str(payload.get('company_name') or '').strip()
        company = job.company if job and job.company_id else None
        if company_id:
            try:
                company = Company.objects.get(id=company_id, user=request.user)
            except Company.DoesNotExist:
                return Response({'detail': 'Company not found.'}, status=status.HTTP_400_BAD_REQUEST)
        elif company_name:
            company, _ = Company.objects.get_or_create(user=request.user, name=company_name)

        if job and company and job.company_id != company.id:
            job.company = company
        if job and 'job_id' in payload:
            job.job_id = str(payload.get('job_id') or '').strip() or job.job_id
        if job and 'role' in payload:
            job.role = str(payload.get('role') or '').strip() or job.role
        if job and 'job_url' in payload:
            job.job_link = str(payload.get('job_url') or '').strip()
        if job and 'applied_date' in payload:
            job.applied_at = self._to_date(payload.get('applied_date'))
        if job and 'posting_date' in payload:
            job.date_of_posting = self._to_date(payload.get('posting_date'))
        if job and 'is_open' in payload:
            job.is_closed = not self._to_bool(payload.get('is_open'), default=True)
        if job and 'is_closed' in payload:
            job.is_closed = self._to_bool(payload.get('is_closed'), default=job.is_closed)
        if job and 'is_removed' in payload:
            job.is_removed = self._to_bool(payload.get('is_removed'), default=job.is_removed)
        if job:
            job.save()

        if 'mailed' in payload:
            row.mailed = self._to_bool(payload.get('mailed'), default=row.mailed)
        if 'resume' in payload:
            raw_resume_id = str(payload.get('resume') or '').strip()
            if not raw_resume_id:
                row.resume = None
            else:
                try:
                    row.resume = Resume.objects.get(id=raw_resume_id, user=request.user)
                except Resume.DoesNotExist:
                    return Response({'detail': 'Resume not found.'}, status=status.HTTP_400_BAD_REQUEST)
        if 'tailored_resume' in payload:
            raw_tailored_id = str(payload.get('tailored_resume') or '').strip()
            if not raw_tailored_id:
                row.tailored_resume = None
            else:
                tailored = TailoredResume.objects.filter(id=raw_tailored_id, job=row.job).first() if row.job_id and row.job else TailoredResume.objects.filter(id=raw_tailored_id).first()
                if not tailored and row.job_id and row.job:
                    tailored = row.job.tailored_resumes.all().order_by('created_at', 'id').first()
                if not tailored:
                    return Response({'detail': 'Tailored resume not found.'}, status=status.HTTP_400_BAD_REQUEST)
                row.tailored_resume = tailored
        if any(key in payload for key in ['template_choice', 'template_subject', 'custom_subject', 'template_message', 'template_name']):
            template_choice, template_subject, template_message = self._extract_template_fields(payload)
            row.template_choice = template_choice
            row.template_subject = template_subject
            row.template_message = template_message
        if 'mail_type' in payload or 'action' in payload:
            action_text = str(payload.get('mail_type') or payload.get('action') or '').strip()
            if action_text in {'fresh', 'followed_up'}:
                row.mail_type = action_text
        if 'schedule_time' in payload:
            row.schedule_time = self._to_datetime(payload.get('schedule_time'))
        if 'is_freezed' in payload:
            next_freezed = self._to_bool(payload.get('is_freezed'), default=row.is_freezed)
            row.is_freezed = next_freezed
            row.freezed_at = timezone.now() if next_freezed else None
        if any(key in payload for key in ['maild_at', 'mailed_at', 'replied_at', 'got_replied', 'mailed']):
            if not row.mail_tracking_id:
                row.mail_tracking = MailTracking.objects.create(
                    user=request.user,
                    employee=None,
                    job=job,
                    mailed=row.mailed,
                    got_replied=self._to_bool(payload.get('got_replied'), default=False),
                )
            mailed_at_payload = payload.get('mailed_at', payload.get('maild_at'))
            if mailed_at_payload is not None:
                row.mail_tracking.mailed_at = self._to_datetime(mailed_at_payload)
            if 'replied_at' in payload:
                row.mail_tracking.replied_at = self._to_datetime(payload.get('replied_at'))
            row.mail_tracking.mailed = row.mailed
            if 'got_replied' in payload:
                row.mail_tracking.got_replied = self._to_bool(payload.get('got_replied'), default=row.mail_tracking.got_replied)
            row.mail_tracking.save()
        row.save()

        selected_hr_ids = payload.get('selected_hr_ids')
        selected_hrs = payload.get('selected_hrs')
        if hasattr(request.data, 'getlist'):
            id_list = [str(v or '').strip() for v in request.data.getlist('selected_hr_ids') if str(v or '').strip()]
            name_list = [str(v or '').strip() for v in request.data.getlist('selected_hrs') if str(v or '').strip()]
            if id_list:
                selected_hr_ids = id_list
            if name_list:
                selected_hrs = name_list
        if isinstance(selected_hr_ids, str):
            selected_hr_ids = [x.strip() for x in selected_hr_ids.split(',') if x.strip()]
        if isinstance(selected_hrs, str):
            selected_hrs = [x.strip() for x in selected_hrs.split(',') if x.strip()]

        if isinstance(selected_hr_ids, list):
            selected = Employee.objects.filter(user=request.user, id__in=selected_hr_ids)
            row.selected_hrs.set(selected)
        elif isinstance(selected_hrs, list):
            target_names = [str(name or '').strip() for name in selected_hrs if str(name or '').strip()]
            company_id_ref = row.job.company_id if row.job_id and row.job and row.job.company_id else None
            selected = Employee.objects.filter(user=request.user, company_id=company_id_ref, name__in=target_names)
            row.selected_hrs.set(selected)

        company_ref = row.job.company if row.job_id and row.job and row.job.company_id else None
        if not self._has_company_mail_pattern(company_ref):
            return Response(
                {'detail': 'Company mail pattern is required for this tracking row.'},
                status=status.HTTP_400_BAD_REQUEST,
            )

        append_action = payload.get('append_action')
        if isinstance(append_action, dict):
            action_type = str(append_action.get('type') or '').strip().lower()
            if action_type not in {'fresh', 'followup'}:
                return Response({'detail': 'Invalid action type.'}, status=status.HTTP_400_BAD_REQUEST)
            if action_type == 'followup' and not row.actions.filter(action_type='fresh').exists():
                return Response({'detail': 'Fresh mail must be done first before follow up.'}, status=status.HTTP_400_BAD_REQUEST)
            send_mode = str(append_action.get('send_mode') or 'now').strip().lower()
            mode = 'sent' if send_mode == 'now' else 'scheduled'
            action_at = self._to_datetime(append_action.get('action_at')) or timezone.now()
            TrackingAction.objects.create(
                tracking=row,
                action_type=action_type,
                send_mode=mode,
                action_at=action_at,
            )
            row.mail_type = 'followed_up' if action_type == 'followup' else 'fresh'
            if action_type == 'fresh':
                row.mailed = True
            row.save(update_fields=['mail_type', 'mailed', 'updated_at'])

        fresh = Tracking.objects.filter(id=row.id).select_related('job__company', 'resume', 'tailored_resume', 'mail_tracking').prefetch_related('selected_hrs', 'actions', 'job__tailored_resumes').first()
        return Response(self._serialize_tracking_row(fresh), status=status.HTTP_200_OK)

    def delete(self, request, tracking_id):
        try:
            row = self._get_object_any(request, tracking_id)
        except Tracking.DoesNotExist:
            return Response({'detail': 'Tracking row not found.'}, status=status.HTTP_404_NOT_FOUND)
        if self._is_hard_delete(request):
            row.hard_delete()
            return Response(status=status.HTTP_204_NO_CONTENT)
        row.is_removed = True
        row.is_freezed = True
        row.removed_at = timezone.now()
        row.freezed_at = row.freezed_at or row.removed_at
        row.save(update_fields=['is_removed', 'is_freezed', 'removed_at', 'freezed_at', 'updated_at'])
        return Response({'status': 'soft_deleted', 'id': row.id}, status=status.HTTP_200_OK)


class CompanyListCreateView(APIView):
    permission_classes = [IsAuthenticated]
    parser_classes = [JSONParser]

    def get(self, request):
        queryset = Company.objects.filter(user=request.user).order_by('name')
        rows, meta = _paginate_queryset(queryset, request, default_page_size=10, max_page_size=100)
        return Response(
            {
                **meta,
                'results': CompanySerializer(rows, many=True).data,
            },
            status=status.HTTP_200_OK,
        )

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
    parser_classes = [JSONParser, FormParser, MultiPartParser]

    _JOB_ORDERING = {
        'date_of_posting': 'date_of_posting',
        '-date_of_posting': '-date_of_posting',
        'applied_at': 'applied_at',
        '-applied_at': '-applied_at',
        'created_at': 'created_at',
        '-created_at': '-created_at',
        'role': 'role',
        '-role': '-role',
        'job_id': 'job_id',
        '-job_id': '-job_id',
        'company_name': 'company__name',
        '-company_name': '-company__name',
    }

    def get(self, request):
        include_removed = str(request.query_params.get('include_removed') or '').strip().lower() in {'1', 'true', 'yes', 'y'}
        rows = Job.objects.filter(user=request.user).select_related('company').prefetch_related('tailored_resumes')
        if not include_removed:
            rows = rows.filter(is_removed=False)

        company_id = (request.query_params.get('company_id') or '').strip()
        if company_id.isdigit():
            rows = rows.filter(company_id=int(company_id))

        company_name = (request.query_params.get('company_name') or '').strip()
        if company_name:
            rows = rows.filter(company__name__icontains=company_name)

        job_id_q = (request.query_params.get('job_id') or '').strip()
        if job_id_q:
            rows = rows.filter(job_id__icontains=job_id_q)

        role_q = (request.query_params.get('role') or '').strip()
        if role_q:
            rows = rows.filter(role__icontains=role_q)

        posting_date = (request.query_params.get('posting_date') or '').strip()
        if posting_date:
            rows = rows.filter(date_of_posting=posting_date)

        applied_date = (request.query_params.get('applied_date') or '').strip()
        if applied_date:
            rows = rows.filter(applied_at=applied_date)

        applied_filter = (request.query_params.get('applied') or '').strip().lower()
        if applied_filter == 'yes':
            rows = rows.filter(applied_at__isnull=False)
        elif applied_filter == 'no':
            rows = rows.filter(applied_at__isnull=True)

        ordering_key = (request.query_params.get('ordering') or '-date_of_posting').strip()
        order_expr = self._JOB_ORDERING.get(ordering_key, '-date_of_posting')
        rows = rows.order_by(order_expr, '-id')

        paginated, meta = _paginate_queryset(rows, request, default_page_size=10, max_page_size=100)
        ser = JobSerializer(paginated, many=True, context={'request': request})
        return Response({**meta, 'results': ser.data}, status=status.HTTP_200_OK)

    def post(self, request):
        data = request.data.copy()
        if hasattr(data, '_mutable'):
            data._mutable = True
        company_id = data.get('company')
        new_company_name = data.get('new_company_name')
        try:
            company = resolve_company_for_job(
                request.user,
                company_id=company_id,
                new_company_name=new_company_name,
            )
        except Company.DoesNotExist:
            return Response({'company': ['Company not found.']}, status=status.HTTP_400_BAD_REQUEST)
        except ValueError as exc:
            return Response({'company': [str(exc)]}, status=status.HTTP_400_BAD_REQUEST)
        job_id_value = str(data.get('job_id') or '').strip()
        if not job_id_value:
            return Response({'job_id': ['This field is required.']}, status=status.HTTP_400_BAD_REQUEST)
        exists = Job.objects.filter(
            user=request.user,
            company=company,
            job_id__iexact=job_id_value,
            is_removed=False,
        ).exists()
        if exists:
            return Response({'job_id': ['This job id already exists for this company.']}, status=status.HTTP_400_BAD_REQUEST)
        data['company'] = company.id
        data['job_id'] = job_id_value
        data.pop('new_company_name', None)
        serializer = JobSerializer(data=data, context={'request': request})
        if serializer.is_valid():
            created = serializer.save(user=request.user, company=company)
            return Response(
                JobSerializer(created, context={'request': request}).data,
                status=status.HTTP_201_CREATED,
            )
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)


class JobDetailView(APIView):
    permission_classes = [IsAuthenticated]
    parser_classes = [JSONParser, FormParser, MultiPartParser]

    def _get_object(self, request, job_id):
        return Job.objects.get(id=job_id, user=request.user, is_removed=False)

    def _get_object_any(self, request, job_id):
        return Job.objects.get(id=job_id, user=request.user)

    def _is_hard_delete(self, request):
        mode = str(request.query_params.get('delete_mode') or '').strip().lower()
        hard = str(request.query_params.get('hard') or '').strip().lower()
        return mode == 'hard' or hard in {'1', 'true', 'yes', 'y'}

    def get(self, request, job_id):
        try:
            row = self._get_object(request, job_id)
        except Job.DoesNotExist:
            return Response({'detail': 'Job not found.'}, status=status.HTTP_404_NOT_FOUND)
        return Response(JobSerializer(row, context={'request': request}).data, status=status.HTTP_200_OK)

    def put(self, request, job_id):
        try:
            row = self._get_object(request, job_id)
        except Job.DoesNotExist:
            return Response({'detail': 'Job not found.'}, status=status.HTTP_404_NOT_FOUND)
        data = request.data.copy()
        if hasattr(data, '_mutable'):
            data._mutable = True
        target_company = row.company
        if 'company' in data or 'new_company_name' in data:
            cid = data.get('company')
            newn = data.get('new_company_name')
            norm_new = normalize_company_name(newn) if newn is not None else ''
            has_company_id = cid is not None and str(cid).strip() != ''
            if norm_new or has_company_id:
                try:
                    company = resolve_company_for_job(
                        request.user,
                        company_id=cid if has_company_id else None,
                        new_company_name=newn,
                    )
                    data['company'] = company.id
                    target_company = company
                except Company.DoesNotExist:
                    return Response({'company': ['Company not found.']}, status=status.HTTP_400_BAD_REQUEST)
                except ValueError as exc:
                    return Response({'company': [str(exc)]}, status=status.HTTP_400_BAD_REQUEST)
            data.pop('new_company_name', None)
        target_job_id = str(data.get('job_id') if 'job_id' in data else row.job_id).strip()
        if not target_job_id:
            return Response({'job_id': ['This field may not be blank.']}, status=status.HTTP_400_BAD_REQUEST)
        duplicate = Job.objects.filter(
            user=request.user,
            company=target_company,
            job_id__iexact=target_job_id,
            is_removed=False,
        ).exclude(id=row.id).exists()
        if duplicate:
            return Response({'job_id': ['This job id already exists for this company.']}, status=status.HTTP_400_BAD_REQUEST)
        data['job_id'] = target_job_id
        serializer = JobSerializer(row, data=data, partial=True, context={'request': request})
        if serializer.is_valid():
            updated = serializer.save()
            return Response(JobSerializer(updated, context={'request': request}).data, status=status.HTTP_200_OK)
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

    def delete(self, request, job_id):
        try:
            row = self._get_object_any(request, job_id)
        except Job.DoesNotExist:
            return Response({'detail': 'Job not found.'}, status=status.HTTP_404_NOT_FOUND)
        if self._is_hard_delete(request):
            row.hard_delete()
            return Response(status=status.HTTP_204_NO_CONTENT)
        row.is_removed = True
        row.is_closed = True
        row.save(update_fields=['is_removed', 'is_closed', 'updated_at'])
        return Response({'status': 'soft_deleted', 'id': row.id}, status=status.HTTP_200_OK)
