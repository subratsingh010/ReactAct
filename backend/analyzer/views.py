import json
import os
import re

from rest_framework import status
from rest_framework.parsers import FormParser, JSONParser, MultiPartParser
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from .pdf_parser import parse_resume_pdf
from .models import JobRole, Resume, ResumeAnalysis
from .serializers import (
    JobRoleSerializer,
    ResumeAnalysisSerializer,
    ResumeSerializer,
    SignupSerializer,
)
from .tailor import (
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


PRESET_KEYWORDS = {
    "frontend": ["react", "javascript", "typescript", "redux", "html", "css", "vite", "api", "ui"],
    "backend": ["python", "django", "drf", "rest", "api", "postgres", "redis", "celery", "auth", "jwt"],
    "fullstack": ["react", "python", "django", "drf", "rest", "api", "postgres", "aws", "docker", "git"],
}

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
    permission_classes = [IsAuthenticated]
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

    def _pick_base_builder(self, request_builder, matched_resume, latest_resume):
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

    def post(self, request):
        jd_text = str(request.data.get('job_description') or '').strip()
        if len(jd_text) < 40:
            return Response({'detail': 'Please paste a fuller job description.'}, status=status.HTTP_400_BAD_REQUEST)
        job_role = str(request.data.get('job_role') or '').strip()

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

        keywords, keyword_ai_used, keyword_note = extract_keywords_ai(jd_text)
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

        resumes = list(Resume.objects.filter(user=request.user).order_by('-updated_at', '-created_at'))
        best = find_best_resume_match(keywords, resumes)
        latest_resume = resumes[0] if resumes else None

        if best.resume and min_match <= best.score <= max_match:
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

        base_builder = self._pick_base_builder(request_builder, best.resume, latest_resume)
        ai_payload, ai_used, ai_note = tailor_resume_with_ai(
            base_builder,
            jd_text,
            keywords,
            job_role=job_role,
        )
        if not ai_used:
            return Response(
                {'detail': f'AI rewrite failed. {ai_note or "Please try again."}'},
                status=status.HTTP_502_BAD_GATEWAY,
            )
        tailored_builder = build_tailored_builder(base_builder, ai_payload, keywords, jd_text=jd_text)
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
                    'preview_only': True,
                },
                status=status.HTTP_200_OK,
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

        ai_payload, ai_used, ai_note = optimize_existing_resume_quality_ai(request_builder)
        if not ai_used:
            return Response(
                {'detail': f'AI quality optimization failed. {ai_note or "Please try again."}'},
                status=status.HTTP_502_BAD_GATEWAY,
            )
        optimized_builder = build_quality_optimized_builder(request_builder, ai_payload)
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
