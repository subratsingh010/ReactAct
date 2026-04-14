import re
import json
import os
import smtplib
import time
import tempfile
import urllib.error
import urllib.request
from pathlib import Path
from email.mime.base import MIMEBase
from email import encoders
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

from django.core.management.base import BaseCommand
from django.db.models import Q
from django.utils import timezone

from analyzer.mail_prompt_templates import build_tracking_mail_prompt
from analyzer.models import Achievement, Employee, MailTracking, MailTrackingEvent, Tracking, UserProfile


class Command(BaseCommand):
    help = "Send tracking mails one-by-one using company mail pattern; log all attempts in MailTracking and MailTrackingEvent."

    def add_arguments(self, parser):
        parser.add_argument("--user-id", type=int, default=None, help="Process only this user id")
        parser.add_argument("--limit", type=int, default=200, help="Max tracking rows to process")
        parser.add_argument("--include-mailed", action="store_true", help="Include already mailed tracking rows")
        parser.add_argument("--scheduled-today-only", action="store_true", help="Process only rows scheduled for today")
        parser.add_argument("--sleep-seconds", type=float, default=5.0, help="Sleep after each successful send")
        parser.add_argument("--dry-run", action="store_true", help="Do not send email; only log planned attempts")
        parser.add_argument("--use-ai", action="store_true", help="Generate subject/body via OpenAI using profile + employee context")

    def _delivery_status_from_counts(self, sent_count, failed_count):
        sent = int(sent_count or 0)
        failed = int(failed_count or 0)
        if sent > 0 and failed > 0:
            return "partially_sent"
        if sent > 0:
            return "sent"
        return "failed"

    def _default_subject_for_template(self, template_choice, role, company_name, emp_name="", job_id=""):
        choice = str(template_choice or "").strip().lower() or "cold_applied"
        role_text = role or "role"
        company_text = company_name or "the company"
        job_suffix = f" (Job ID: {job_id})" if str(job_id or "").strip() else ""
        mapping = {
            "cold_applied": f"Application for {role_text} at {company_text}{job_suffix}",
            "referral": f"Referral request for {role_text} at {company_text}",
            "job_inquire": f"Question about {role_text} at {company_text}",
            "follow_up_applied": f"Follow up on my application for {role_text} at {company_text}",
            "follow_up_call": f"Thank you and follow up on {role_text} at {company_text}",
            "follow_up_interview": f"Thank you for the interview - {role_text} at {company_text}",
            "custom": f"Hi {emp_name or 'there'} - introduction",
        }
        return mapping.get(choice, f"Application for {role_text} at {company_text}")

    def _yoe_phrase(self, profile):
        yoe = str(getattr(profile, "years_of_experience", "") or "").strip() if profile else ""
        if yoe:
            if yoe.endswith("+"):
                return f"{yoe} years of experience"
            if yoe[-1:].isdigit():
                return f"{yoe}+ years of experience"
            return f"{yoe} years of experience"
        return "3+ years of experience"

    def _is_hard_mail_failure(self, message):
        text = str(message or "").strip().lower()
        markers = [
            "user unknown",
            "address not found",
            "recipient address rejected",
            "no such user",
            "invalid recipient",
            "mailbox unavailable",
            "5.1.1",
            "550",
            "bounced",
            "undeliverable",
        ]
        return any(marker in text for marker in markers)

    def _set_employee_working_mail(self, employee, is_working):
        if not employee:
            return
        if bool(getattr(employee, "working_mail", True)) == bool(is_working):
            return
        employee.working_mail = bool(is_working)
        employee.save(update_fields=["working_mail", "updated_at"])

    def handle(self, *args, **options):
        now = timezone.now()
        user_id = options.get("user_id")
        limit = int(options.get("limit") or 200)
        include_mailed = bool(options.get("include_mailed"))
        scheduled_today_only = bool(options.get("scheduled_today_only"))
        sleep_seconds = float(options.get("sleep_seconds") or 0.0)
        dry_run = bool(options.get("dry_run"))
        use_ai = bool(options.get("use_ai"))

        qs = (
            Tracking.objects
            .filter(is_removed=False, is_freezed=False, job__isnull=False)
            .filter(Q(schedule_time__isnull=True) | Q(schedule_time__lte=now))
            .select_related("job__company", "mail_tracking", "user")
            .prefetch_related("selected_hrs")
            .order_by("created_at")
        )
        if user_id:
            qs = qs.filter(user_id=user_id)
        if not include_mailed:
            qs = qs.filter(mailed=False)
        if scheduled_today_only:
            qs = qs.filter(schedule_time__date=timezone.localdate())
        rows = list(qs[:limit])

        self.stdout.write(f"Processing tracking rows: {len(rows)}")
        total_sent = 0
        total_failed = 0

        for row in rows:
            job = row.job
            company = job.company if row.job_id and job and job.company_id else None
            pattern = str(getattr(company, "mail_format", "") or "").strip()
            mail_tracking = self._ensure_mail_tracking(row)
            if not company or not pattern:
                row.mail_delivery_status = "failed"
                row.save(update_fields=["mail_delivery_status", "updated_at"])
                self._log_event(
                    mail_tracking=mail_tracking,
                    tracking=row,
                    employee=None,
                    success=False,
                    subject="",
                    body="",
                    to_email="",
                    notes="Skipped: company mail pattern is missing.",
                )
                self.stdout.write(self.style.WARNING(f"[tracking:{row.id}] skipped (missing company/pattern)"))
                total_failed += 1
                continue

            profile = self._get_profile(row.user_id)
            employees = list(row.selected_hrs.all())
            if not employees:
                employees = list(
                    Employee.objects.filter(
                        user_id=row.user_id,
                        company_id=company.id,
                        department__iexact="HR",
                        working_mail=True,
                    )
                    .order_by("name")[:5]
                )
            else:
                employees = [emp for emp in employees if bool(getattr(emp, "working_mail", True))]
            if not employees:
                row.mail_delivery_status = "failed"
                row.save(update_fields=["mail_delivery_status", "updated_at"])
                self._log_event(
                    mail_tracking=mail_tracking,
                    tracking=row,
                    employee=None,
                    success=False,
                    subject="",
                    body="",
                    to_email="",
                    notes="Skipped: no target employees found for this tracking row.",
                )
                self.stdout.write(self.style.WARNING(f"[tracking:{row.id}] skipped (no employees to target)"))
                total_failed += 1
                continue

            row_sent = 0
            row_failed = 0
            achievements = self._get_achievements(row.user_id)
            attachment_path = self._resolve_attachment_file(row)
            for emp in employees:
                to_email = self._resolve_employee_email(emp, pattern)
                if not to_email:
                    self._log_event(
                        mail_tracking=mail_tracking,
                        tracking=row,
                        employee=emp,
                        success=False,
                        subject="",
                        body="",
                        to_email="",
                        notes="Could not resolve recipient email from company mail pattern.",
                    )
                    row_failed += 1
                    continue

                subject, body = self._build_mail(row, emp, profile, achievements, use_ai=use_ai)
                try:
                    if not dry_run:
                        self._send_email(row.user, to_email, subject, body, attachment_path=attachment_path)

                    # Keep employee email synced once resolved via pattern.
                    if not str(emp.email or "").strip():
                        emp.email = to_email
                        emp.save(update_fields=["email", "updated_at"])

                    self._log_success(mail_tracking, row, emp, subject, body, to_email)
                    self._set_employee_working_mail(emp, True)
                    row_sent += 1
                    total_sent += 1

                    if sleep_seconds > 0:
                        time.sleep(sleep_seconds)
                except Exception as exc:  # noqa: BLE001
                    self._log_event(
                        mail_tracking=mail_tracking,
                        tracking=row,
                        employee=emp,
                        success=False,
                        subject=subject,
                        body=body,
                        to_email=to_email,
                        notes=f"Send failed: {exc}",
                    )
                    if self._is_hard_mail_failure(exc):
                        self._set_employee_working_mail(emp, False)
                    row_failed += 1
                    total_failed += 1

            if row_sent > 0:
                row.mailed = True
                row.mail_delivery_status = self._delivery_status_from_counts(row_sent, row_failed)
                row.save(update_fields=["mailed", "mail_delivery_status", "updated_at"])
                self.stdout.write(self.style.SUCCESS(f"[tracking:{row.id}] sent={row_sent} failed={row_failed}"))
            else:
                row.mail_delivery_status = self._delivery_status_from_counts(row_sent, row_failed)
                row.save(update_fields=["mail_delivery_status", "updated_at"])
                total_failed += 1
                self.stdout.write(self.style.WARNING(f"[tracking:{row.id}] no successful sends (failed={row_failed})"))

        self.stdout.write(self.style.SUCCESS(f"Done. sent={total_sent} failed={total_failed}"))

    def _resolve_attachment_file(self, row):
        # Priority:
        # 1) Existing tracking attachment in MailTracking
        # 2) Uploaded resume file
        # 3) Generated PDF from builder data (tailored/resume)
        mail_tracking = row.mail_tracking
        if mail_tracking and getattr(mail_tracking, "attachment_files", None):
            try:
                path = Path(mail_tracking.attachment_files.path)
                if path.exists():
                    return str(path)
            except Exception:  # noqa: BLE001
                pass

        if row.resume and getattr(row.resume, "file", None):
            try:
                path = Path(row.resume.file.path)
                if path.exists():
                    return str(path)
            except Exception:  # noqa: BLE001
                pass

        builder = {}
        title = ""
        if row.tailored_resume and isinstance(row.tailored_resume.builder_data, dict):
            builder = row.tailored_resume.builder_data
            title = str(row.tailored_resume.name or "").strip() or "Tailored Resume"
        elif row.resume and isinstance(row.resume.builder_data, dict):
            builder = row.resume.builder_data
            title = str(row.resume.title or "").strip() or "Resume"
        if not builder:
            return None

        text = self._builder_data_to_text(builder, fallback_title=title)
        if not text.strip():
            return None
        return self._write_simple_pdf(text, filename_hint=title)

    def _builder_data_to_text(self, builder_data, fallback_title="Resume"):
        b = builder_data if isinstance(builder_data, dict) else {}
        lines = [str(b.get("resumeTitle") or fallback_title or "Resume").strip() or "Resume", ""]
        basics = b.get("basics") if isinstance(b.get("basics"), dict) else {}
        for key in ["fullName", "email", "phone", "location", "linkedin", "github", "portfolio"]:
            val = str(basics.get(key) or "").strip()
            if val:
                lines.append(f"{key}: {val}")
        if len(lines) > 2:
            lines.append("")

        summary = str(b.get("summary") or "").strip()
        if summary:
            lines.extend(["Summary", summary, ""])

        for section, heading, name_key in [
            ("experiences", "Experience", "company"),
            ("projects", "Projects", "name"),
            ("educations", "Education", "institution"),
        ]:
            rows = b.get(section) if isinstance(b.get(section), list) else []
            if not rows:
                continue
            lines.append(heading)
            for item in rows:
                if not isinstance(item, dict):
                    continue
                title = str(item.get(name_key) or item.get("title") or "").strip()
                role = str(item.get("role") or "").strip()
                first = " - ".join(part for part in [title, role] if part)
                if first:
                    lines.append(first)
                highlights = str(item.get("highlights") or "").strip()
                if highlights:
                    lines.append(highlights)
            lines.append("")

        skills = b.get("skills")
        if isinstance(skills, list) and skills:
            lines.append("Skills")
            lines.append(", ".join(str(x).strip() for x in skills if str(x).strip()))
        return "\n".join(lines).strip()

    def _write_simple_pdf(self, text, filename_hint="resume"):
        safe_hint = re.sub(r"[^a-zA-Z0-9._-]+", "_", str(filename_hint or "resume")).strip("_") or "resume"
        fd, tmp_path = tempfile.mkstemp(prefix=f"{safe_hint}_", suffix=".pdf")
        os.close(fd)
        path = Path(tmp_path)

        # Minimal one-page PDF writer.
        lines = [ln[:110] for ln in str(text or "").splitlines()[:80]]
        if not lines:
            lines = ["Resume"]
        y = 780
        stream_lines = ["BT", "/F1 11 Tf", "50 800 Td", f"({self._pdf_escape(lines[0])}) Tj"]
        for ln in lines[1:]:
            y -= 14
            if y < 40:
                break
            stream_lines.append(f"0 -14 Td ({self._pdf_escape(ln)}) Tj")
        stream_lines.append("ET")
        stream = "\n".join(stream_lines).encode("latin-1", errors="ignore")

        objects = []
        objects.append(b"1 0 obj << /Type /Catalog /Pages 2 0 R >> endobj\n")
        objects.append(b"2 0 obj << /Type /Pages /Kids [3 0 R] /Count 1 >> endobj\n")
        objects.append(b"3 0 obj << /Type /Page /Parent 2 0 R /MediaBox [0 0 595 842] /Resources << /Font << /F1 5 0 R >> >> /Contents 4 0 R >> endobj\n")
        objects.append(
            f"4 0 obj << /Length {len(stream)} >> stream\n".encode("latin-1")
            + stream
            + b"\nendstream endobj\n"
        )
        objects.append(b"5 0 obj << /Type /Font /Subtype /Type1 /BaseFont /Helvetica >> endobj\n")

        with path.open("wb") as f:
            f.write(b"%PDF-1.4\n")
            offsets = [0]
            for obj in objects:
                offsets.append(f.tell())
                f.write(obj)
            xref_pos = f.tell()
            f.write(f"xref\n0 {len(offsets)}\n".encode("latin-1"))
            f.write(b"0000000000 65535 f \n")
            for off in offsets[1:]:
                f.write(f"{off:010d} 00000 n \n".encode("latin-1"))
            f.write(
                f"trailer << /Size {len(offsets)} /Root 1 0 R >>\nstartxref\n{xref_pos}\n%%EOF\n".encode("latin-1")
            )
        return str(path)

    def _pdf_escape(self, value):
        text = str(value or "")
        text = text.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")
        return text

    def _ensure_mail_tracking(self, row):
        mail_tracking = row.mail_tracking
        if mail_tracking:
            return mail_tracking
        mail_tracking = MailTracking.objects.create(
            user=row.user,
            job=row.job,
            mailed=False,
            got_replied=False,
        )
        row.mail_tracking = mail_tracking
        row.save(update_fields=["mail_tracking", "updated_at"])
        return mail_tracking

    def _get_profile(self, user_id):
        try:
            return UserProfile.objects.get(user_id=user_id)
        except UserProfile.DoesNotExist:
            return None

    def _get_achievements(self, user_id, limit=6):
        return list(
            Achievement.objects
            .filter(user_id=user_id)
            .order_by("-created_at")[: int(limit or 6)]
        )

    def _resolve_employee_email(self, employee, pattern):
        existing = str(employee.email or "").strip()
        if existing:
            return existing
        fmt = str(pattern or "").strip()
        if "@" not in fmt:
            return ""

        name = str(employee.name or "").strip()
        if not name:
            return ""
        parts = [p for p in re.split(r"\s+", name) if p]
        first = re.sub(r"[^a-z0-9]", "", parts[0].lower()) if parts else ""
        last = re.sub(r"[^a-z0-9]", "", parts[-1].lower()) if len(parts) > 1 else ""
        if not first:
            return ""

        local, domain = fmt.split("@", 1)
        domain = domain.strip().lower()
        local = local.strip().lower()
        if not domain:
            return ""

        repl = {
            "{firstname}": first,
            "{first_name}": first,
            "{first}": first,
            "firstname": first,
            "first_name": first,
            "first": first,
            "{lastname}": last,
            "{last_name}": last,
            "{last}": last,
            "lastname": last,
            "last_name": last,
            "last": last,
            "{f}": first[:1],
            "{l}": last[:1],
            "{fname}": first[:1],
            "fname": first[:1],
            "{lname}": last[:1],
            "lname": last[:1],
        }
        built = local
        for key in sorted(repl.keys(), key=len, reverse=True):
            built = built.replace(key, repl[key])
        built = re.sub(r"[^a-z0-9._-]", "", built)
        built = re.sub(r"\.{2,}", ".", built).strip(".")
        if not built:
            return ""
        return f"{built}@{domain}"

    def _resolve_openai_model(self):
        value = str(os.getenv("OPENAI_MODEL", "gpt-4o") or "").strip()
        return value or "gpt-4o"

    def _openai_generate_mail_json(self, prompt):
        api_key = os.getenv("OPENAI_API_KEY", "").strip()
        if not api_key:
            return None, "OPENAI_API_KEY is not set"

        system = (
            "You write job application emails. Return STRICT JSON only. "
            "Do not include the sender's signature or contact details. "
            "Output format: {\"subject\":\"...\",\"body\":\"...\"}. "
            "The body must start with 'Hi <name>,' and be plain text (no markdown)."
        )
        payload = {
            "model": self._resolve_openai_model(),
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": str(prompt or "").strip()[:12000]},
            ],
            "response_format": {"type": "json_object"},
            "temperature": 0.4,
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
            if not isinstance(parsed, dict):
                return None, "AI response was not a JSON object"
            subject = str(parsed.get("subject") or "").strip()
            body = str(parsed.get("body") or "").strip()
            if not subject or not body:
                return None, "AI response missing subject/body"
            return {"subject": subject, "body": body}, ""
        except urllib.error.HTTPError as exc:
            try:
                body = exc.read().decode("utf-8")
            except Exception:  # noqa: BLE001
                body = ""
            return None, f"OpenAI request failed: {body or exc.reason}"
        except Exception as exc:  # noqa: BLE001
            return None, f"OpenAI request failed: {exc}"

    def _build_personalized_prompt(self, row, employee, profile, achievements):
        job = row.job
        company_name = job.company.name if row.job_id and job and job.company_id else "your company"
        role = str(job.role or "").strip() if row.job_id and job else ""
        job_id = str(job.job_id or "").strip() if row.job_id and job else ""
        job_link = str(getattr(job, "job_link", "") or "").strip() if row.job_id and job else ""
        emp_name = str(employee.name or "").strip() or "there"
        template_category = str(row.template_choice or "cold_applied").strip().lower() or "cold_applied"
        mail_type = str(row.mail_type or "fresh").strip().lower() or "fresh"

        # Employee context: prefer about; fallback to role + department.
        emp_about = str(getattr(employee, "about", "") or "").strip()
        emp_role = str(getattr(employee, "JobRole", "") or "").strip()
        emp_dept = str(getattr(employee, "department", "") or "").strip()
        if emp_about:
            employee_context = f"Employee about:\n{emp_about}"
        else:
            bits = [b for b in [emp_role, emp_dept] if b]
            employee_context = (
                "Employee about: (missing)\n"
                f"Fallback context: employee role/department = {', '.join(bits) if bits else 'unknown'}"
            )

        summary = str(getattr(profile, "summary", "") or "").strip() if profile else ""
        yoe = str(getattr(profile, "years_of_experience", "") or "").strip() if profile else ""
        current_employer = str(getattr(profile, "current_employer", "") or "").strip() if profile else ""
        full_name = str(getattr(profile, "full_name", "") or row.user.username or "").strip()

        # Compact achievements list (best-effort).
        ach_lines = []
        for ach in achievements or []:
            title = str(getattr(ach, "name", "") or "").strip()
            detail = str(getattr(ach, "achievement", "") or "").strip()
            skills = str(getattr(ach, "skills", "") or "").strip()
            line = ""
            if title and detail:
                line = f"- {title}: {detail}"
            elif title:
                line = f"- {title}"
            elif detail:
                line = f"- {detail}"
            if line and skills:
                line = f"{line} (skills: {skills})"
            if line:
                ach_lines.append(line)
            if len(ach_lines) >= 5:
                break
        achievements_block = "\n".join(ach_lines) if ach_lines else "- (none provided)"
        context = {
            "template_category": template_category,
            "mail_type": mail_type,
            "recipient_name": emp_name,
            "recipient_role": emp_role or "(unknown)",
            "recipient_department": emp_dept or "(unknown)",
            "company_name": company_name,
            "job_role": role or "(unknown)",
            "job_id": job_id or "(none)",
            "job_link": job_link or "(none)",
            "interaction_date": self._format_interaction_date(row),
            "candidate_name": full_name,
            "years_of_experience": yoe or "(not provided)",
            "current_employer": current_employer or "(not provided)",
            "profile_summary": summary or "(not provided)",
            "employee_context": employee_context,
            "achievements_block": achievements_block,
        }
        return build_tracking_mail_prompt(context)

    def _audience_type(self, employee):
        role = str(getattr(employee, "JobRole", "") or "").strip().lower()
        dept = str(getattr(employee, "department", "") or "").strip().lower()
        audience = f"{role} {dept}".strip()
        if any(key in audience for key in ["hr", "talent", "recruit", "people"]):
            return "hr_talent"
        if any(key in audience for key in ["manager", "team lead", "lead", "head"]):
            return "manager"
        if any(key in audience for key in ["engineer", "developer", "sde", "software"]):
            return "engineering"
        return "general"

    def _ask_line_by_audience(self, employee, template_choice="cold_applied"):
        audience = self._audience_type(employee)
        choice = str(template_choice or "cold_applied").strip().lower()
        if audience == "hr_talent":
            if choice == "referral":
                return "Would you be open to referring me, or guiding me to the right recruiter or hiring manager for this role?"
            return "Would you be open to sharing your perspective on my fit, or pointing me to the right recruiter or hiring manager for this role?"
        if audience == "manager":
            if choice == "referral":
                return "Would you be open to sharing whether my background aligns with your team needs, and referring me to the right hiring contact?"
            return "Would you be open to sharing your perspective on my fit for the team, or directing me to the right hiring contact?"
        if audience == "engineering":
            if choice == "referral":
                return "Would you be open to sharing your view on my technical fit and referring me to the right hiring contact?"
            return "Would you be open to sharing your perspective on my technical fit, or pointing me to the right hiring contact?"
        if choice == "referral":
            return "Would you be open to referring me, or pointing me to the right contact for this role?"
        return "Would you be open to sharing your perspective on my fit, or pointing me to the right person for this role?"

    def _resume_attachment_line(self, row):
        has_attached_resume = False
        mail_tracking = getattr(row, "mail_tracking", None)
        if mail_tracking is not None and getattr(mail_tracking, "attachment_files", None):
            has_attached_resume = True
        if has_attached_resume:
            return "I have attached my resume for your reference."
        return "I am happy to share my resume if helpful."

    def _build_signature(self, row, profile):
        full_name = str(getattr(profile, "full_name", "") or row.user.username or "").strip()
        linkedin = str(getattr(profile, "linkedin_url", "") or "").strip()
        contact = str(getattr(profile, "contact_number", "") or "").strip()
        email = str(getattr(profile, "email", "") or row.user.email or "").strip()

        sign_parts = [f"Sincerely,\n{full_name}".strip()]
        if linkedin:
            sign_parts.append(f"LinkedIn: {linkedin}")
        if email:
            sign_parts.append(f"Email: {email}")
        if contact:
            sign_parts.append(contact)
        return "\n".join([p for p in sign_parts if str(p or "").strip()])

    def _formal_closing_line(self, profile):
        yoe = str(getattr(profile, "years_of_experience", "") or "").strip() if profile else ""
        current_employer = str(getattr(profile, "current_employer", "") or "").strip() if profile else ""
        full_name = str(getattr(profile, "full_name", "") or "").strip() if profile else ""

        if yoe and current_employer:
            return (
                f"Thank you for your time and consideration. "
                f"I would value the opportunity to contribute with my {yoe} years of experience at {current_employer}."
            )
        if yoe:
            return (
                f"Thank you for your time and consideration. "
                f"I would value the opportunity to contribute with my {yoe} years of experience."
            )
        if current_employer:
            return (
                f"Thank you for your time and consideration. "
                f"I would value the opportunity to contribute based on my experience at {current_employer}."
            )
        if full_name:
            return (
                f"Thank you for your time and consideration. "
                f"I look forward to hearing from you."
            )
        return "Thank you for your time and consideration."

    def _inject_dynamic_names(self, text, employee_name, sender_name):
        value = str(text or "")
        emp = str(employee_name or "").strip()
        snd = str(sender_name or "").strip()

        if emp:
            for token in ["[Name]", "[Employee Name]", "<name>", "<employee_name>", "{{name}}", "{name}"]:
                value = value.replace(token, emp)
            value = re.sub(r"\bHi\s+there\s*,", f"Hi {emp},", value, flags=re.I)
            value = re.sub(r"\bHello\s+there\s*,", f"Hi {emp},", value, flags=re.I)
        else:
            # If employee name is missing, keep greeting generic and avoid fake placeholders.
            value = re.sub(r"\bHi\s+\[?[A-Za-z _-]+\]?\s*,", "Hi,", value)

        if snd:
            for token in ["[Your Name]", "<your_name>", "{{sender_name}}", "{sender_name}"]:
                value = value.replace(token, snd)
        return value

    def _format_interaction_date(self, row):
        date_value = None
        if getattr(row, "schedule_time", None):
            date_value = row.schedule_time
        elif getattr(row, "updated_at", None):
            date_value = row.updated_at
        elif getattr(row, "created_at", None):
            date_value = row.created_at
        if not date_value:
            return "recently"
        try:
            return date_value.strftime("%d %b %Y")
        except Exception:  # noqa: BLE001
            return "recently"

    def _is_follow_up_template_choice(self, choice):
        return str(choice or "").strip().lower() in {"follow_up_applied", "follow_up_call", "follow_up_interview"}

    def _use_hardcoded_follow_up_for_row(self, row, choice):
        if not self._is_follow_up_template_choice(choice):
            return False
        return bool(getattr(row, "hardcoded_follow_up", True))

    def _employee_personalization(self, employee, company_name, max_about_chars=220):
        about = str(getattr(employee, "about", "") or "").strip()
        role = str(getattr(employee, "JobRole", "") or "").strip()
        department = str(getattr(employee, "department", "") or "").strip()
        role_dept_at_company = ""
        if role and department:
            role_dept_at_company = f"as {role} in {department} at {company_name}"
        elif role:
            role_dept_at_company = f"as {role} at {company_name}"
        elif department:
            role_dept_at_company = f"in {department} at {company_name}"
        else:
            role_dept_at_company = f"at {company_name}"

        if about:
            compact_about = " ".join(about.split())
            snippet = compact_about[: int(max_about_chars or 220)].rstrip()
            if snippet and not snippet.endswith("."):
                snippet += "."
            return (
                f"I came across your profile and noticed your work {role_dept_at_company}. "
                f"{snippet}"
            )

        # Generic fallback with dynamic role/department/company when about is missing.
        return (
            f"I came across your profile and noticed your work {role_dept_at_company}. "
            "Your background stood out to me."
        )

    def _candidate_intro_line(self, profile, role, company_name, job_id, achievements):
        yoe = str(getattr(profile, "years_of_experience", "") or "").strip() if profile else ""
        summary = str(getattr(profile, "summary", "") or "").strip() if profile else ""
        skills = []
        for ach in achievements or []:
            raw = str(getattr(ach, "skills", "") or "").strip()
            if raw:
                for part in re.split(r"[,/|]", raw):
                    item = str(part or "").strip()
                    if item and item.lower() not in {s.lower() for s in skills}:
                        skills.append(item)
                    if len(skills) >= 4:
                        break
            if len(skills) >= 4:
                break

        yoe_text = f"{yoe}+ years of experience" if yoe and yoe[-1].isdigit() else (f"{yoe} years of experience" if yoe else "hands-on experience")
        skills_text = ""
        if skills:
            skills_text = f" in {', '.join(skills[:3])}"
        elif summary:
            skills_text = ""

        return (
            f"I recently applied for the {role or 'open'} role at {company_name}"
            f"{f' (Job ID: {job_id})' if job_id else ''} and wanted to reach out. "
            f"I am a full-stack engineer with {yoe_text}{skills_text}, "
            "with practical experience in building and scaling backend services."
        )

    def _achievement_impact_line(self, profile, achievements):
        current_employer = str(getattr(profile, "current_employer", "") or "").strip() if profile else ""
        for ach in achievements or []:
            name = str(getattr(ach, "name", "") or "").strip()
            detail = str(getattr(ach, "achievement", "") or "").strip()
            if detail:
                metric_match = re.search(r"(\d+%|\d+\s?ms|\d+\s?rpm|\d+\s?requests?)", detail, flags=re.I)
                if metric_match:
                    lead = f"At {current_employer}, " if current_employer else ""
                    sentence = detail[:220].strip()
                    if sentence and not sentence.endswith("."):
                        sentence += "."
                    if name:
                        return f"{lead}I delivered {name.lower()} where {sentence}"
                    return f"{lead}{sentence}"
        summary = str(getattr(profile, "summary", "") or "").strip() if profile else ""
        if summary:
            fallback = summary[:220].strip()
            if fallback and not fallback.endswith("."):
                fallback += "."
            return fallback
        return "I focus on building reliable, user-focused systems with measurable impact."

    def _build_mail(self, row, employee, profile, achievements, *, use_ai=False):
        job = row.job
        company_name = job.company.name if row.job_id and job and job.company_id else "your company"
        role = str(job.role or "").strip() if row.job_id and job else ""
        job_id = str(job.job_id or "").strip() if row.job_id and job else ""
        emp_name = str(employee.name or "").strip() or "there"
        choice = str(row.template_choice or "cold_applied").strip().lower()
        sender_name = str(getattr(profile, "full_name", "") or row.user.username or "").strip()
        interaction_date = self._format_interaction_date(row)

        # Always build signature from profile (never hard-code contact details).
        signature = self._build_signature(row, profile)
        closing_line = self._formal_closing_line(profile)
        attachment_line = self._resume_attachment_line(row)

        # Optional AI generation; for follow-ups this is controlled by row.hardcoded_follow_up.
        follow_up_hardcoded = self._use_hardcoded_follow_up_for_row(row, choice)
        if use_ai and choice != "custom" and not follow_up_hardcoded:
            prompt = self._build_personalized_prompt(row, employee, profile, achievements)
            ai, error = self._openai_generate_mail_json(prompt)
            if ai and not error:
                subject = str(ai.get("subject") or "").strip()
                body_core = str(ai.get("body") or "").strip()
                body = f"{body_core}\n\n{closing_line}\n\n{attachment_line}\n\n{signature}"
                subject = self._inject_dynamic_names(subject, emp_name, sender_name)
                body = self._inject_dynamic_names(body, emp_name, sender_name)
                return subject, body

        summary = str(getattr(profile, "summary", "") or "").strip()
        yoe = str(getattr(profile, "years_of_experience", "") or "").strip()
        current_employer = str(getattr(profile, "current_employer", "") or "").strip()
        full_name = str(getattr(profile, "full_name", "") or row.user.username or "").strip()
        linkedin = str(getattr(profile, "linkedin_url", "") or "").strip()
        contact = str(getattr(profile, "contact_number", "") or "").strip()
        email = str(getattr(profile, "email", "") or row.user.email or "").strip()

        if choice == "custom":
            # Custom template should keep user-defined subject when provided.
            subject = str(row.template_subject or "").strip() or self._default_subject_for_template(choice, role, company_name, emp_name, job_id)
            body_core = str(row.template_message or "").strip()
            if not body_core:
                body_core = f"Hi {emp_name},\n\nI hope you are doing well."
            body = f"{body_core}\n\n{closing_line}\n\n{attachment_line}\n\n{signature}"
            subject = self._inject_dynamic_names(subject, emp_name, sender_name)
            body = self._inject_dynamic_names(body, emp_name, sender_name)
            return subject, body
        elif choice == "referral":
            subject = str(row.template_subject or "").strip() or self._default_subject_for_template(choice, role or "open role", company_name, emp_name, job_id)
            yoe_text = self._yoe_phrase(profile)
            body_core = (
                f"Hi {emp_name},\n\n"
                "I hope you are doing well.\n\n"
                f"I am interested in the {role or 'open'} role at {company_name}"
                f"{f' (Job ID: {job_id})' if job_id else ''} and would value your referral guidance.\n\n"
                f"I bring {yoe_text} in backend and product engineering."
            )
        elif choice == "job_inquire":
            subject = str(row.template_subject or "").strip() or self._default_subject_for_template(choice, role or "open roles", company_name, emp_name, job_id)
            yoe_text = self._yoe_phrase(profile)
            body_core = (
                f"Hi {emp_name},\n\n"
                f"{self._employee_personalization(employee, company_name, max_about_chars=110)}\n\n"
                f"I wanted to inquire about the {role or 'open'} role at {company_name}.\n"
                f"I have {yoe_text} in full-stack and backend systems.\n"
                f"{self._achievement_impact_line(profile, achievements)[:150].rstrip('.') }.\n\n"
                f"{self._ask_line_by_audience(employee, template_choice=choice)}"
            )
            body = f"{body_core}\n\n{closing_line}\n\n{attachment_line}\n\n{signature}"
            subject = self._inject_dynamic_names(subject, emp_name, sender_name)
            body = self._inject_dynamic_names(body, emp_name, sender_name)
            return subject, body
        elif choice == "follow_up_applied" and follow_up_hardcoded:
            subject = str(row.template_subject or "").strip() or self._default_subject_for_template(choice, role or "the role", company_name, emp_name, job_id)
            body_core = (
                f"Hi {emp_name},\n\n"
                f"{self._employee_personalization(employee, company_name, max_about_chars=110)}\n\n"
                f"I wanted to follow up on my application for the {role or 'role'} position at {company_name}.\n\n"
                f"{self._achievement_impact_line(profile, achievements)[:150].rstrip('.') }.\n\n"
                "I would appreciate any update you can share, or guidance on the next step."
            )
            body = f"{body_core}\n\n{closing_line}\n\n{attachment_line}\n\n{signature}"
            subject = self._inject_dynamic_names(subject, emp_name, sender_name)
            body = self._inject_dynamic_names(body, emp_name, sender_name)
            return subject, body
        elif choice == "follow_up_call" and follow_up_hardcoded:
            subject = str(row.template_subject or "").strip() or self._default_subject_for_template(choice, role or "the role", company_name, emp_name, job_id)
            body_core = (
                f"Hi {emp_name},\n\n"
                f"Thank you again for the call on {interaction_date}. We had discussed the {role or 'role'} opportunity at {company_name}.\n\n"
                f"I remain very interested in the {role or 'role'} position at {company_name}.\n"
                f"{self._achievement_impact_line(profile, achievements)[:140].rstrip('.') }.\n\n"
                "Could you please share whether my profile is shortlisted, and what the next step in the process will be?"
            )
            body = f"{body_core}\n\n{closing_line}\n\n{attachment_line}\n\n{signature}"
            subject = self._inject_dynamic_names(subject, emp_name, sender_name)
            body = self._inject_dynamic_names(body, emp_name, sender_name)
            return subject, body
        elif choice == "follow_up_interview" and follow_up_hardcoded:
            subject = str(row.template_subject or "").strip() or self._default_subject_for_template(choice, role or "role", company_name, emp_name, job_id)
            body_core = (
                f"Hi {emp_name},\n\n"
                f"Thank you for taking the time to interview me on {interaction_date}.\n\n"
                f"I remain excited about the opportunity to contribute to the {role or 'role'} team at {company_name}.\n"
                f"{self._achievement_impact_line(profile, achievements)[:140].rstrip('.') }.\n\n"
                "Could you please share feedback from the interview and the next process/timeline?"
            )
            body = f"{body_core}\n\n{closing_line}\n\n{attachment_line}\n\n{signature}"
            subject = self._inject_dynamic_names(subject, emp_name, sender_name)
            body = self._inject_dynamic_names(body, emp_name, sender_name)
            return subject, body
        elif self._is_follow_up_template_choice(choice):
            subject = str(row.template_subject or "").strip() or self._default_subject_for_template("follow_up_applied", role or "the role", company_name, emp_name, job_id)
            body_core = (
                f"Hi {emp_name},\n\n"
                f"I wanted to follow up on our recent discussion regarding the {role or 'role'} opportunity at {company_name}.\n\n"
                f"{self._achievement_impact_line(profile, achievements)[:150].rstrip('.') }.\n\n"
                "I would appreciate any update on next steps when convenient."
            )
            body = f"{body_core}\n\n{closing_line}\n\n{attachment_line}\n\n{signature}"
            subject = self._inject_dynamic_names(subject, emp_name, sender_name)
            body = self._inject_dynamic_names(body, emp_name, sender_name)
            return subject, body
        else:
            subject = str(row.template_subject or "").strip() or self._default_subject_for_template(choice, role or "role", company_name, emp_name, job_id)
            personalized_first_para = self._employee_personalization(employee, company_name)
            intro_para = self._candidate_intro_line(profile, role, company_name, job_id, achievements)
            impact_para = self._achievement_impact_line(profile, achievements)
            ask_para = self._ask_line_by_audience(employee, template_choice=choice)
            body_core = (
                f"Hi {emp_name},\n\n"
                f"{personalized_first_para}\n\n"
                f"{intro_para}\n\n"
                f"{impact_para}\n\n"
                f"{ask_para}"
            )
            body = f"{body_core}\n\n{closing_line}\n\n{attachment_line}\n\n{signature}"
            subject = self._inject_dynamic_names(subject, emp_name, sender_name)
            body = self._inject_dynamic_names(body, emp_name, sender_name)
            return subject, body

        intro_bits = []
        if yoe:
            intro_bits.append(f"{yoe} years of experience")
        if current_employer:
            intro_bits.append(f"currently at {current_employer}")
        intro_line = f"I am {full_name}" + (f", with {' and '.join(intro_bits)}." if intro_bits else ".")

        extra = summary or "I bring hands-on backend and product engineering experience and would love to contribute."
        ask = self._ask_line_by_audience(employee, template_choice=choice)

        body = (
            f"{body_core}\n\n"
            f"{intro_line}\n"
            f"{extra}\n\n"
            f"{ask}\n\n"
            f"{closing_line}\n\n"
            f"{attachment_line}\n\n"
            + signature
        )
        subject = self._inject_dynamic_names(subject, emp_name, sender_name)
        body = self._inject_dynamic_names(body, emp_name, sender_name)
        return subject, body

    def _send_email(self, user, to_email, subject, body, attachment_path=None):
        host = str(__import__("os").environ.get("SMTP_HOST", "")).strip()
        port = int(str(__import__("os").environ.get("SMTP_PORT", "587")).strip() or 587)
        username = str(__import__("os").environ.get("SMTP_USER", "")).strip()
        password = str(__import__("os").environ.get("SMTP_PASSWORD", "")).strip()
        use_tls = str(__import__("os").environ.get("SMTP_USE_TLS", "true")).strip().lower() in {"1", "true", "yes", "on"}
        from_email = str(__import__("os").environ.get("SMTP_FROM_EMAIL", "")).strip() or username or str(user.email or "").strip()
        if not host or not from_email:
            raise RuntimeError("SMTP_HOST / SMTP_FROM_EMAIL (or SMTP_USER) is not configured.")

        if attachment_path:
            msg = MIMEMultipart()
            msg.attach(MIMEText(body, "plain", "utf-8"))
            try:
                file_path = Path(attachment_path)
                with file_path.open("rb") as fh:
                    part = MIMEBase("application", "octet-stream")
                    part.set_payload(fh.read())
                encoders.encode_base64(part)
                part.add_header("Content-Disposition", f'attachment; filename="{file_path.name}"')
                msg.attach(part)
            except Exception:  # noqa: BLE001
                # Soft-fail attachment and continue with plain body.
                msg = MIMEText(body, "plain", "utf-8")
        else:
            msg = MIMEText(body, "plain", "utf-8")
        msg["Subject"] = subject
        msg["From"] = from_email
        msg["To"] = to_email
        # No CC by design.

        with smtplib.SMTP(host, port, timeout=30) as server:
            if use_tls:
                server.starttls()
            if username and password:
                server.login(username, password)
            server.sendmail(from_email, [to_email], msg.as_string())

    def _map_mail_type(self, tracking):
        raw = str(tracking.mail_type or "fresh").strip().lower()
        return "followup" if raw == "followed_up" else "fresh"

    def _log_success(self, mail_tracking, tracking, employee, subject, body, to_email):
        now = timezone.now()
        history = mail_tracking.mail_history if isinstance(mail_tracking.mail_history, list) else []
        history.append(
            {
                "status": "sent",
                "to_email": to_email,
                "subject": subject,
                "body": body,
                "employee_id": employee.id if employee else None,
                "employee_name": str(employee.name or "").strip() if employee else "",
                "at": now.isoformat(),
            }
        )
        mail_tracking.employee = employee
        mail_tracking.mailed = True
        mail_tracking.mailed_at = now
        mail_tracking.mail_history = history[-200:]
        mail_tracking.save(update_fields=["employee", "mailed", "mailed_at", "mail_history", "updated_at"])

        MailTrackingEvent.objects.create(
            mail_tracking=mail_tracking,
            tracking=tracking,
            employee=employee,
            mail_type=self._map_mail_type(tracking),
            send_mode="sent",
            action_at=now,
            got_replied=False,
            notes="Mail sent from cron command.",
            raw_payload={
                "to_email": to_email,
                "subject": subject,
                "body": body,
                "cc": [],
            },
        )

    def _log_event(self, mail_tracking, tracking, employee, success, subject, body, to_email, notes):
        now = timezone.now()
        history = mail_tracking.mail_history if isinstance(mail_tracking.mail_history, list) else []
        history.append(
            {
                "status": "sent" if success else "failed",
                "to_email": to_email,
                "subject": subject,
                "body": body,
                "employee_id": employee.id if employee else None,
                "employee_name": str(employee.name or "").strip() if employee else "",
                "notes": notes,
                "at": now.isoformat(),
            }
        )
        mail_tracking.mail_history = history[-200:]
        mail_tracking.save(update_fields=["mail_history", "updated_at"])

        MailTrackingEvent.objects.create(
            mail_tracking=mail_tracking,
            tracking=tracking,
            employee=employee,
            mail_type=self._map_mail_type(tracking),
            send_mode="sent",
            action_at=now,
            got_replied=False,
            notes=notes,
            raw_payload={
                "to_email": to_email,
                "subject": subject,
                "body": body,
                "cc": [],
                "status": "sent" if success else "failed",
            },
        )
