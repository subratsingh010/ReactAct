from __future__ import annotations

import html
import re
from typing import Any

from pypdf import PdfReader

SECTION_ALIASES = {
    'SUMMARY': 'summary',
    'PROFESSIONAL SUMMARY': 'summary',
    'CAREER SUMMARY': 'summary',
    'OBJECTIVE': 'summary',
    'CAREER OBJECTIVE': 'summary',
    'PROFILE': 'summary',
    'SKILLS': 'skills',
    'TECH STACK': 'skills',
    'TECHNOLOGIES': 'skills',
    'TECHNOLOGIES USED': 'skills',
    'CORE SKILLS': 'skills',
    'EXPERIENCE': 'experience',
    'WORK EXPERIENCE': 'experience',
    'PROFESSIONAL EXPERIENCE': 'experience',
    'EMPLOYMENT HISTORY': 'experience',
    'EDUCATION': 'education',
    'ACADEMICS': 'education',
    'ACADEMIC DETAILS': 'education',
    'PROJECT': 'projects',
    'PROJECTS': 'projects',
    'PROJECT EXPERIENCE': 'projects',
    'PERSONAL PROJECTS': 'projects',
    'AWARD': 'custom:Award',
    'AWARDS': 'custom:Award',
    'ACHIEVEMENT': 'custom:Achievements',
    'ACHIEVEMENTS': 'custom:Achievements',
    'CERTIFICATION': 'custom:Certifications',
    'CERTIFICATIONS': 'custom:Certifications',
}

KNOWN_SECTION_KEYS = {'summary', 'skills', 'experience', 'education', 'projects'}

MONTH_RE = r'(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Sept|Oct|Nov|Dec)[a-z]*'
DATE_TOKEN_RE = rf'(?:{MONTH_RE}\s+\d{{4}}|\d{{4}})'
DATE_RANGE_RE = re.compile(rf'(?P<dates>{DATE_TOKEN_RE}(?:\s*[–-]\s*(?:Present|{DATE_TOKEN_RE}))?)$', re.I)
DATE_RANGE_ONLY_RE = re.compile(rf'^\s*(?:{DATE_TOKEN_RE})\s*[–-]\s*(?:Present|{DATE_TOKEN_RE})\s*$', re.I)


def _norm(value: str) -> str:
    text = re.sub(r'\s+', ' ', str(value or '').replace('\u00a0', ' ')).strip()
    return re.sub(r'\b([A-Z]{2,})(for|the|to|of|in|and|with|on|at|from|as)\b', r'\1 \2', text)


def _normalize_heading(raw: str) -> str:
    text = _norm(raw).strip()
    text = re.sub(r'[:|]+$', '', text).strip()
    text = re.sub(r'\s+', ' ', text)
    return text.upper()


def _looks_like_unknown_heading(raw: str) -> bool:
    text = _norm(raw).strip()
    if not text or len(text) > 60:
        return False
    if text.endswith('.'):
        return False
    words = [w for w in re.split(r'\s+', text) if w]
    if not (1 <= len(words) <= 6):
        return False
    if re.search(r'[\d,;]', text):
        return False
    if not re.fullmatch(r'[A-Za-z&/+ -]+', text):
        return False
    letters = [c for c in text if c.isalpha()]
    if not letters:
        return False
    upper_ratio = sum(1 for c in letters if c.isupper()) / len(letters)
    return upper_ratio >= 0.85


def _resolve_section_heading(raw: str, allow_unknown: bool = True) -> tuple[str, str] | None:
    key = _normalize_heading(raw)
    mapped = SECTION_ALIASES.get(key)
    if mapped:
        if mapped.startswith('custom:'):
            label = mapped.split(':', 1)[1]
            return (f'custom::{label}', label)
        return (mapped, '')

    if allow_unknown and _looks_like_unknown_heading(raw):
        label = _norm(raw).strip(':| ').title()
        return (f'custom::{label}', label)

    return None


def _slugify(value: str) -> str:
    text = _norm(value).lower()
    text = re.sub(r'[^a-z0-9]+', '-', text).strip('-')
    return text or 'section'


def _clean_lines(text: str) -> list[str]:
    lines = []
    for raw in str(text or '').splitlines():
        line = _norm(raw)
        if line:
            lines.append(line)
    return lines


def _escape_paragraph(text: str) -> str:
    clean = _norm(text)
    if not clean:
        return ''
    return f'<p>{html.escape(clean)}</p>'


def _lines_to_list_html(lines: list[str]) -> str:
    items = [f'<li>{html.escape(_norm(line))}</li>' for line in lines if _norm(line)]
    if not items:
        return ''
    return '<ul>' + ''.join(items) + '</ul>'


def _strip_list_prefix(text: str) -> str:
    line = _norm(text)
    if not line:
        return ''
    # Remove explicit list prefixes only (dot, bullet, dash, asterisk, numbered markers).
    line = re.sub(r'^\s*(?:[•\-*]|\.|(?:\d{1,3}[\).\]]))\s*', '', line)
    return _norm(line)


def _is_explicit_bullet_line(text: str) -> bool:
    line = _norm(text)
    if not line:
        return False
    return bool(re.match(r'^\s*(?:[•\-*]|\.|(?:\d{1,3}[\).\]]))\s+', line))


def _lines_to_custom_html(lines: list[str]) -> str:
    cleaned = [_norm(line) for line in (lines or []) if _norm(line) and _norm(line).lower() != 'link']
    if not cleaned:
        return ''

    # Only preserve bullets when the source clearly uses explicit bullet markers.
    if any(_is_explicit_bullet_line(line) for line in cleaned):
        items = [f'<li>{html.escape(_strip_list_prefix(line))}</li>' for line in cleaned if _strip_list_prefix(line)]
        if items:
            return '<ul>' + ''.join(items) + '</ul>'

    # Otherwise keep as plain paragraph text (no synthetic bullets).
    merged = ' '.join(_strip_list_prefix(line) for line in cleaned if _strip_list_prefix(line)).strip()
    return _escape_paragraph(merged)


def _group_bullets(lines: list[str]) -> list[str]:
    bullets: list[str] = []
    current: list[str] = []

    for raw in lines:
        line = _norm(raw)
        if not line or line.lower() == 'link':
            continue

        starts_with_marker = line.startswith(('•', '-', '*'))
        starts_new = False
        if current:
            prev = _norm(current[-1]).rstrip()
            prev_ends_sentence = prev.endswith(('.', '!', '?'))
            if starts_with_marker:
                starts_new = True
            elif prev_ends_sentence and (line[0].isupper() or line[0].isdigit()):
                starts_new = True

        if starts_new:
            bullets.append(_norm(' '.join(current)))
            current = [line]
        else:
            current.append(line)

    if current:
        bullets.append(_norm(' '.join(current)))

    return [bullet for bullet in bullets if bullet]


def _extract_pdf_urls(reader: PdfReader) -> list[str]:
    found: list[dict[str, Any]] = []

    for page in reader.pages:
        annots = page.get('/Annots') or []
        for annot_ref in annots:
            try:
                annot = annot_ref.get_object()
            except Exception:
                continue

            action = annot.get('/A')
            if action is None:
                continue
            try:
                action = action.get_object()
            except Exception:
                pass

            uri = None
            if hasattr(action, 'get'):
                uri = action.get('/URI')
            if not uri:
                continue

            rect = annot.get('/Rect') or [0, 0, 0, 0]
            try:
                x0, y0, x1, y1 = [float(v) for v in rect[:4]]
            except Exception:
                x0 = y0 = x1 = y1 = 0.0
            found.append({'url': str(uri).strip(), 'rect': [x0, y0, x1, y1]})

    found.sort(key=lambda item: (-item['rect'][3], item['rect'][0]))
    return [item['url'] for item in found if item.get('url')]


def _split_contact(lines: list[str]) -> tuple[str, str, str]:
    location = ''
    phone = ''
    email = ''

    if not lines:
        return location, phone, email

    parts = [part.strip() for part in lines[0].split('|') if part.strip()]
    for part in parts:
        if '@' in part and not email:
            email = part
        elif re.search(r'\+?\d[\d\s().-]{7,}', part) and not phone:
            phone = part
        elif not location:
            location = part

    return location, phone, email


def _split_date_range(value: str) -> tuple[str, str, bool]:
    clean = _norm(value)
    if not clean:
        return '', '', False

    parts = [_norm(part) for part in re.split(r'\s*[–-]\s*', clean) if _norm(part)]
    if len(parts) >= 2:
        start = parts[0]
        end = parts[-1]
        return start, '' if end.lower() == 'present' else end, end.lower() == 'present'

    if clean.lower() == 'present':
        return '', '', True

    return clean, '', False


def _split_experience_header(line: str) -> tuple[str, str, str, str, bool] | None:
    clean = _norm(line)
    match = DATE_RANGE_RE.search(clean)
    if not match:
        return None

    dates = _norm(match.group('dates'))
    leading = _norm(clean[: match.start('dates')].rstrip(' -–'))
    parts = [part.strip() for part in re.split(r'\s+[–-]\s+', leading, maxsplit=1) if part.strip()]
    if len(parts) != 2:
        return None

    company, title = parts
    start, end, is_current = _split_date_range(dates)
    return company, title, start, end, is_current


def _parse_experiences(lines: list[str]) -> list[dict[str, Any]]:
    entries: list[dict[str, Any]] = []
    current: dict[str, Any] | None = None

    def looks_like_role_line(value: str) -> bool:
        clean = _norm(value)
        if not clean:
            return False
        if DATE_RANGE_ONLY_RE.fullmatch(clean):
            return False
        if re.search(r'\d', clean):
            return False
        if re.search(r'\s+[–-]\s+', clean):
            parts = [part.strip() for part in re.split(r'\s+[–-]\s+', clean, maxsplit=1) if part.strip()]
            return len(parts) == 2
        return False

    i = 0
    while i < len(lines):
        line = _norm(lines[i])
        if not line:
            i += 1
            continue

        header = _split_experience_header(line)
        if header:
            if current:
                entries.append(current)
            company, title, start, end, is_current = header
            current = {
                'company': company,
                'title': title,
                'startDate': start,
                'endDate': end,
                'isCurrent': is_current,
                'bullets': [],
            }
            i += 1
            continue

        # Handle two-line header:
        # Company – Title
        # Mar 2025 – Present
        if (i + 1) < len(lines):
            next_line = _norm(lines[i + 1])
            if looks_like_role_line(line) and DATE_RANGE_ONLY_RE.fullmatch(next_line):
                if current:
                    entries.append(current)
                parts = [part.strip() for part in re.split(r'\s+[–-]\s+', line, maxsplit=1) if part.strip()]
                company = parts[0] if parts else ''
                title = parts[1] if len(parts) > 1 else ''
                start, end, is_current = _split_date_range(next_line)
                current = {
                    'company': company,
                    'title': title,
                    'startDate': start,
                    'endDate': end,
                    'isCurrent': is_current,
                    'bullets': [],
                }
                i += 2
                continue

        if current is not None:
            current['bullets'].append(line)
        i += 1

    if current:
        entries.append(current)

    parsed: list[dict[str, Any]] = []
    for entry in entries:
        parsed.append(
            {
                'company': entry['company'],
                'title': entry['title'],
                'startDate': entry['startDate'],
                'endDate': entry['endDate'],
                'isCurrent': bool(entry['isCurrent']),
                'highlights': _lines_to_list_html(_group_bullets(entry['bullets'])),
            }
        )

    return parsed


def _parse_skills(lines: list[str]) -> str:
    merged: list[str] = []
    for raw in lines:
        line = _norm(raw)
        if not line:
            continue
        is_new_category = ':' in line and re.match(r'^[A-Za-z][A-Za-z/& +.-]{1,40}:', line)
        if merged and not is_new_category:
            merged[-1] = _norm(f"{merged[-1]} {line}")
        else:
            merged.append(line)
    return _lines_to_list_html(merged)


def _parse_summary(lines: list[str]) -> str:
    summary = _norm(' '.join(lines))
    return _escape_paragraph(summary)


def _parse_education(lines: list[str]) -> list[dict[str, Any]]:
    if not lines:
        return []

    groups: list[list[str]] = []
    current: list[str] = []

    for line in lines:
        current.append(line)
        if DATE_RANGE_RE.search(_norm(line)) or re.fullmatch(r'\d{4}', _norm(line)):
            groups.append(current)
            current = []

    if current:
        groups.append(current)

    parsed: list[dict[str, Any]] = []
    for group in groups:
        if not group:
            continue

        institution = _norm(group[0])
        program_line = _norm(group[1]) if len(group) > 1 else ''
        date_line = _norm(group[-1]) if len(group) > 1 else ''

        program = program_line
        score_enabled = False
        score_type = 'cgpa'
        score_value = ''
        score_label = ''

        if '|' in program_line:
            program_part, score_part = [part.strip() for part in program_line.split('|', 1)]
            program = program_part
            score_match = re.match(r'(?P<label>[^:]+?)\s*:\s*(?P<value>.+)$', score_part)
            if score_match:
                score_label = _norm(score_match.group('label'))
                score_value = _norm(score_match.group('value'))
                score_enabled = True
                lowered = score_label.lower()
                if lowered.startswith('cgpa'):
                    score_type = 'cgpa'
                elif lowered.startswith('percentage'):
                    score_type = 'percentage'
                else:
                    score_type = 'custom'

        start_date, end_date, is_current = _split_date_range(date_line)

        parsed.append(
            {
                'institution': institution,
                'program': program,
                'scoreEnabled': score_enabled,
                'scoreType': score_type,
                'scoreValue': score_value,
                'scoreLabel': score_label,
                'startDate': start_date,
                'endDate': end_date,
                'isCurrent': is_current,
            }
        )

    return parsed


def _parse_projects(lines: list[str], project_urls: list[str]) -> list[dict[str, Any]]:
    clean_lines = [line for line in lines if _norm(line) and _norm(line).lower() != 'link']
    if not clean_lines:
        return []

    def looks_like_project_title(value: str) -> bool:
        text = _norm(value)
        if not text:
            return False
        if text.endswith('.'):
            return False
        if re.search(r'[|]', text):
            return False
        words = text.split()
        if len(words) > 6:
            return False
        return True

    projects: list[dict[str, Any]] = []
    current_name = ''
    current_lines: list[str] = []

    for line in clean_lines:
        line_clean = _norm(line)
        if not current_name:
            current_name = line_clean
            continue

        if looks_like_project_title(line_clean) and current_lines:
            projects.append(
                {
                    'name': current_name,
                    'url': '',
                    'highlights': _lines_to_list_html(_group_bullets(current_lines)),
                }
            )
            current_name = line_clean
            current_lines = []
            continue

        current_lines.append(line_clean)

    if current_name:
        projects.append(
            {
                'name': current_name,
                'url': '',
                'highlights': _lines_to_list_html(_group_bullets(current_lines)),
            }
        )

    for idx, item in enumerate(projects):
        item['url'] = project_urls[idx] if idx < len(project_urls) else ''
    return projects


def parse_resume_pdf(file_obj) -> dict[str, Any]:
    if hasattr(file_obj, 'seek'):
        file_obj.seek(0)

    reader = PdfReader(file_obj)
    text = '\n'.join((page.extract_text() or '') for page in reader.pages)
    lines = _clean_lines(text)
    urls = _extract_pdf_urls(reader)

    sections: dict[str, list[str]] = {value: [] for value in KNOWN_SECTION_KEYS}
    custom_section_titles: dict[str, str] = {}
    preamble: list[str] = []
    current_section = 'preamble'
    has_seen_known_section = False

    for line in lines:
        resolved = _resolve_section_heading(line, allow_unknown=has_seen_known_section)
        if resolved:
            key, label = resolved
            current_section = key
            if key.startswith('custom::'):
                custom_section_titles[key] = label or key.split('::', 1)[1]
                sections.setdefault(key, [])
            elif key in KNOWN_SECTION_KEYS:
                has_seen_known_section = True
            continue

        if current_section == 'preamble':
            preamble.append(line)
        else:
            sections.setdefault(current_section, [])
            sections[current_section].append(line)

    full_name = _norm(preamble[0]).title() if preamble else ''
    location, phone, email = _split_contact(preamble[1:2])

    link_labels = [part.strip() for part in preamble[2].split('|') if part.strip()] if len(preamble) > 2 else []
    top_urls = urls[: len(link_labels)]
    project_urls = urls[len(link_labels) :]

    links = [
        {'label': label, 'url': top_urls[index] if index < len(top_urls) else ''}
        for index, label in enumerate(link_labels)
    ]

    experiences = _parse_experiences(sections.get('experience') or [])
    educations = _parse_education(sections.get('education') or [])
    projects = _parse_projects(sections.get('projects') or [], project_urls)
    custom_sections = []
    custom_order_keys: list[str] = []
    for key, title in custom_section_titles.items():
        lines_for_section = sections.get(key) or []
        if not lines_for_section:
            continue
        content = _lines_to_custom_html(lines_for_section)
        if not content:
            content = _escape_paragraph(' '.join(lines_for_section))
        if content:
            section_id = _slugify(title)
            suffix = 2
            existing_ids = {item.get('id') for item in custom_sections}
            while section_id in existing_ids:
                section_id = f"{_slugify(title)}-{suffix}"
                suffix += 1
            custom_sections.append({'id': section_id, 'title': title, 'content': content})
            custom_order_keys.append(f'custom:{section_id}')

    role = experiences[0]['title'] if experiences else ''

    summary_html = _parse_summary(sections.get('summary') or [])
    skills_html = _parse_skills(sections.get('skills') or [])

    return {
        'fullName': full_name,
        'role': role,
        'email': email,
        'phone': phone,
        'location': location,
        'links': links,
        'summaryEnabled': bool(summary_html),
        'summaryHeading': 'Summary',
        'summaryStyle': 'auto',
        'summary': summary_html,
        'skills': skills_html,
        'experiences': experiences,
        'projects': projects,
        'educations': educations,
        'bodyFontSizePt': 10,
        'bodyLineHeight': 1,
        'sectionOrder': ['summary', 'skills', 'experience', 'projects', 'education', *custom_order_keys],
        'sectionUnderline': False,
        'customSections': custom_sections,
    }
