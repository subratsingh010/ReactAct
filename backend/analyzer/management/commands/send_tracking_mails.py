import re
import json
import html
import os
import smtplib
import time
import tempfile
import urllib.error
import urllib.request
import logging
from datetime import datetime
from pathlib import Path
from email.mime.base import MIMEBase
from email import encoders
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.utils import make_msgid
from logging.handlers import TimedRotatingFileHandler

from django.core.management.base import BaseCommand
from django.utils import timezone

from analyzer.models import Template, Tracking, TrackingAction, UserProfile
from analyzer.profile_settings import resolve_openai_settings, resolve_smtp_settings
from analyzer.resume_rendering import (
    available_browser_binaries,
    build_builder_pdf_bytes,
    build_frontend_ats_pdf_html,
    default_pdf_filename,
    pick_local_pdf_path,
    pdf_page_count,
    render_pdf_bytes_from_html,
)
from analyzer.template_access import resolve_template_ids_for_user
from analyzer.tracking_mail_utils import build_mail_tracking_status_map, ensure_mail_tracking, log_mail_event, recompute_tracking_delivery_status


LOGGER_NAME = "analyzer.send_tracking_mails"


class Command(BaseCommand):
    help = "Send tracking mails one-by-one using company mail pattern; log all attempts in MailTracking and MailTrackingEvent."

    def add_arguments(self, parser):
        parser.add_argument("--user-id", type=int, default=None, help="Process only this user id")
        parser.add_argument("--limit", type=int, default=200, help="Max tracking rows to process")
        parser.add_argument("--include-mailed", action="store_true", help="Include already mailed tracking rows")
        parser.add_argument("--scheduled-today-only", action="store_true", help="Process only rows scheduled for today")
        parser.add_argument("--sleep-seconds", type=float, default=5.0, help="Sleep after each successful send")
        parser.add_argument("--dry-run", action="store_true", help="Do not send email; only log planned attempts")
        parser.add_argument("--test-mode", action="store_true", help="Skip SMTP send but still record successful tracking data and mark rows as processed")
        parser.add_argument("--use-ai", action="store_true", help="Allow AI only for personalized employee intro generation")

    def _delivery_status_from_counts(self, sent_count, failed_count):
        sent = int(sent_count or 0)
        failed = int(failed_count or 0)
        if sent > 0 and failed > 0:
            return "partial_sent"
        if sent > 0:
            return "complete_sent"
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
            "follow_up_referral": f"Follow up on my referral request for {role_text} at {company_text}",
            "follow_up_call": f"Thank you and follow up on {role_text} at {company_text}",
            "follow_up_interview": f"Thank you for the interview - {role_text} at {company_text}",
            "custom": f"Hi {emp_name or 'there'} - introduction",
        }
        return mapping.get(choice, f"Application for {role_text} at {company_text}")

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

    def _normalize_message_id(self, value):
        normalized = str(value or "").strip()
        if not normalized:
            return ""
        if normalized.startswith("<") and normalized.endswith(">"):
            return normalized
        if "<" in normalized and ">" in normalized:
            match = re.search(r"<[^>]+>", normalized)
            if match:
                return match.group(0).strip()
        return f"<{normalized.strip('<>')}>"

    def _thread_reference_list(self, *values):
        refs = []
        seen = set()
        for value in values:
            items = value if isinstance(value, (list, tuple)) else [value]
            for item in items:
                for raw_ref in re.findall(r"<[^>]+>", str(item or "")):
                    normalized = self._normalize_message_id(raw_ref)
                    key = normalized.lower()
                    if normalized and key not in seen:
                        refs.append(normalized)
                        seen.add(key)
        return refs

    def _reply_subject(self, subject):
        normalized = str(subject or "").strip()
        if not normalized:
            return "Re:"
        return normalized if normalized.lower().startswith("re:") else f"Re: {normalized}"

    def _fresh_subject(self, subject):
        normalized = str(subject or "").strip()
        if not normalized:
            return ""
        return re.sub(r"^\s*re\s*:\s*", "", normalized, flags=re.I).strip()

    def _resolve_thread_context(self, mail_tracking, tracking, to_email):
        normalized_to = str(to_email or "").strip().lower()
        if not mail_tracking or not normalized_to:
            return {}
        if str(getattr(tracking, "mail_type", "") or "").strip().lower() != "followed_up":
            return {}

        events = (
            mail_tracking.events
            .filter(status="sent")
            .select_related("employee")
            .order_by("-action_at", "-created_at")
        )
        for item in events:
            payload = item.raw_payload if isinstance(item.raw_payload, dict) else {}
            item_to = str(payload.get("to_email") or "").strip().lower()
            if item_to != normalized_to:
                continue
            message_id = self._normalize_message_id(
                payload.get("message_id") or item.source_message_id or ""
            )
            if not message_id:
                continue
            references = self._thread_reference_list(
                payload.get("references"),
                payload.get("thread_references"),
                payload.get("in_reply_to"),
                message_id,
            )
            subject = str(payload.get("subject") or "").strip()
            return {
                "in_reply_to": message_id,
                "references": references,
                "subject": self._reply_subject(subject) if subject else "",
            }
        return {}

    def _should_use_ai_for_row(self, row, explicit_use_ai=False):
        return bool(explicit_use_ai)

    def _set_employee_working_mail(self, employee, is_working):
        if not employee:
            return
        if bool(getattr(employee, "working_mail", True)) == bool(is_working):
            return
        employee.working_mail = bool(is_working)
        employee.save(update_fields=["working_mail", "updated_at"])

    def _get_logger(self):
        logger = logging.getLogger(LOGGER_NAME)
        if logger.handlers:
            return logger

        log_dir = Path(__file__).resolve().parents[4] / "log"
        log_dir.mkdir(parents=True, exist_ok=True)
        log_path = log_dir / "send_tracking_mails.log"

        handler = TimedRotatingFileHandler(
            filename=log_path,
            when="midnight",
            interval=1,
            backupCount=14,
            encoding="utf-8",
        )
        handler.suffix = "%Y-%m-%d"
        handler.setFormatter(logging.Formatter("%(asctime)s [%(levelname)s] %(message)s"))

        logger.setLevel(logging.INFO)
        logger.addHandler(handler)
        logger.propagate = False
        return logger

    def _emit(self, message, *, level="info", style=None):
        text = str(message or "")
        logger = self._get_logger()
        log_method = getattr(logger, str(level or "info").lower(), logger.info)
        log_method(text)

        styled = style(text) if style else text
        self.stdout.write(styled)

    def handle(self, *args, **options):
        now = timezone.localtime(timezone.now())
        user_id = options.get("user_id")
        limit = int(options.get("limit") or 200)
        include_mailed = bool(options.get("include_mailed"))
        scheduled_today_only = bool(options.get("scheduled_today_only"))
        sleep_seconds = float(options.get("sleep_seconds") or 0.0)
        dry_run = bool(options.get("dry_run"))
        test_mode = bool(options.get("test_mode"))
        use_ai = bool(options.get("use_ai"))

        qs = (
            Tracking.objects
            .filter(is_freezed=False, job__isnull=False)
            .filter(schedule_time__isnull=False, schedule_time__lte=now)
            .select_related("job__company", "mail_tracking_record", "resume", "profile__user")
            .prefetch_related("selected_hrs")
            .order_by("created_at")
        )
        if user_id:
            qs = qs.filter(profile__user_id=user_id)
        if scheduled_today_only:
            qs = qs.filter(schedule_time__date=timezone.localdate())
        rows = list(qs[:limit])

        self._emit(f"Processing tracking rows: {len(rows)}")
        total_sent = 0
        total_failed = 0

        for row in rows:
            row_sent, row_failed = self._process_tracking_row(
                row,
                include_mailed=include_mailed,
                dry_run=dry_run,
                test_mode=test_mode,
                use_ai=use_ai,
                sleep_seconds=sleep_seconds,
                clear_schedule=not dry_run,
                append_tracking_action=True,
                force_resend=False,
            )
            total_sent += row_sent
            total_failed += row_failed

        self._emit(f"Done. sent={total_sent} failed={total_failed}", level="info", style=self.style.SUCCESS)

    def _process_tracking_row(
        self,
        row,
        *,
        include_mailed=False,
        dry_run=False,
        test_mode=False,
        use_ai=False,
        sleep_seconds=0.0,
        clear_schedule=True,
        append_tracking_action=True,
        force_resend=False,
    ):
        job = row.job
        company = job.company if row.job_id and job and job.company_id else None
        pattern = str(getattr(company, "mail_format", "") or "").strip()
        mail_tracking = ensure_mail_tracking(row)
        row_started_scheduled = bool(getattr(row, "schedule_time", None))
        if not company or not pattern:
            row.mail_delivery_status = "failed"
            row.save(update_fields=["mail_delivery_status", "updated_at"])
            if clear_schedule and not dry_run:
                self._clear_schedule_if_processed(row)
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
            self._emit(f"[tracking:{row.id}] skipped (missing company/pattern)", level="warning", style=self.style.WARNING)
            return 0, 1

        profile = self._get_profile(row.user_id)
        employees = [emp for emp in row.selected_hrs.all() if bool(getattr(emp, "working_mail", True))]
        if not employees:
            row.mail_delivery_status = "failed"
            row.save(update_fields=["mail_delivery_status", "updated_at"])
            if clear_schedule and not dry_run:
                self._clear_schedule_if_processed(row)
            self._log_event(
                mail_tracking=mail_tracking,
                tracking=row,
                employee=None,
                success=False,
                subject="",
                body="",
                to_email="",
                notes="Skipped: no selected employees found for this tracking row.",
            )
            self._emit(f"[tracking:{row.id}] skipped (no selected employees to target)", level="warning", style=self.style.WARNING)
            return 0, 1

        row_sent = 0
        row_failed = 0
        achievements = self._get_achievements(row)
        attachment_payload = self._resolve_attachment_payload(row) or {}
        attachment_path = attachment_payload.get("path")
        attachment_bytes = attachment_payload.get("bytes")
        latest_status_map = build_mail_tracking_status_map(mail_tracking)
        is_scheduled_replay = bool(getattr(row, "schedule_time", None))
        pending_employees = []
        for emp in employees:
            to_email = self._resolve_employee_email(emp, pattern)
            existing_status = latest_status_map.get(f"employee:{emp.id}")
            if not existing_status and to_email:
                existing_status = latest_status_map.get(f"email:{to_email.strip().lower()}")
            status_value = str(existing_status.get("status") or "").strip().lower() if existing_status else ""
            if not include_mailed and not is_scheduled_replay and not force_resend and status_value in {"sent", "failed", "bounced"}:
                continue
            pending_employees.append((emp, to_email))

        if not pending_employees:
            recompute_tracking_delivery_status(row)
            if clear_schedule and not dry_run:
                self._clear_schedule_if_processed(row)
            self._emit(f"[tracking:{row.id}] skipped (no pending employees left to process)", level="warning", style=self.style.WARNING)
            return 0, 0

        for emp, to_email in pending_employees:
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

            subject, body = self._build_mail(
                row,
                emp,
                profile,
                achievements,
                use_ai=self._should_use_ai_for_row(row, explicit_use_ai=use_ai),
            )
            thread_context = self._resolve_thread_context(mail_tracking, row, to_email)
            if thread_context.get("subject"):
                subject = thread_context["subject"]
            if str(getattr(row, "mail_type", "") or "").strip().lower() != "followed_up":
                subject = self._fresh_subject(subject)
            try:
                if dry_run:
                    self._emit(
                        f"[tracking:{row.id}] dry run planned for {to_email or 'unresolved-recipient'}",
                        level="info",
                        style=self.style.HTTP_INFO,
                    )
                    continue

                if test_mode:
                    self._emit(
                        f"[tracking:{row.id}] test mode simulated send to {to_email}",
                        level="info",
                        style=self.style.HTTP_INFO,
                    )
                    sent_message_id = self._normalize_message_id(make_msgid())
                else:
                    sent_message_id = self._send_email(
                        row.user,
                        to_email,
                        subject,
                        body,
                        attachment_path=attachment_path,
                        attachment_bytes=attachment_bytes,
                        attachment_name=self._attachment_download_name(row, profile, attachment_path),
                        in_reply_to=thread_context.get("in_reply_to", ""),
                        references=thread_context.get("references", []),
                    )

                if not str(emp.email or "").strip():
                    emp.email = to_email
                    emp.save(update_fields=["email", "updated_at"])

                self._log_success(
                    mail_tracking,
                    row,
                    emp,
                    subject,
                    body,
                    to_email,
                    simulated=test_mode,
                    message_id=sent_message_id,
                    in_reply_to=thread_context.get("in_reply_to", ""),
                    references=thread_context.get("references", []),
                )
                self._set_employee_working_mail(emp, True)
                row_sent += 1

                if sleep_seconds > 0 and not test_mode:
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
                self._set_employee_working_mail(emp, False)
                row_failed += 1

        if dry_run:
            self._emit(f"[tracking:{row.id}] dry run only; planned recipients={len(pending_employees)}", level="warning", style=self.style.WARNING)
            return row_sent, row_failed

        if row_sent > 0 and append_tracking_action:
            self._append_tracking_action_for_send(
                row,
                action_at=timezone.now(),
                send_mode="scheduled" if row_started_scheduled else "sent",
            )
        recompute_tracking_delivery_status(row)
        if clear_schedule:
            self._clear_schedule_if_processed(row)
        attempted_count = row_sent + row_failed
        if attempted_count > 0:
            self._emit(f"[tracking:{row.id}] sent={row_sent} failed={row_failed}", level="info", style=self.style.SUCCESS)
        else:
            self._emit(f"[tracking:{row.id}] no pending sends attempted", level="warning", style=self.style.WARNING)
        return row_sent, row_failed

    def _clear_schedule_if_processed(self, row, *, extra_fields=None):
        if not row or not getattr(row, "schedule_time", None):
            return
        row.schedule_time = None
        update_fields = ["schedule_time", "updated_at"]
        for field in (extra_fields or []):
            if field and field not in update_fields:
                update_fields.append(field)
        row.save(update_fields=update_fields)

    def _tracking_action_note_meta(self, notes):
        raw = str(notes or "").strip()
        if not raw:
            return {"label": "", "employee_ids": [], "count": 1}
        try:
            data = json.loads(raw)
        except Exception:
            return {"label": raw, "employee_ids": [], "count": 1}
        if not isinstance(data, dict):
            return {"label": raw, "employee_ids": [], "count": 1}
        employee_ids = []
        for value in data.get("employee_ids") or []:
            try:
                employee_ids.append(int(value))
            except Exception:
                continue
        try:
            count = max(1, int(data.get("count") or 1))
        except Exception:
            count = 1
        return {
            "label": str(data.get("label") or "").strip(),
            "employee_ids": employee_ids,
            "count": count,
        }

    def _build_tracking_action_notes(self, *, label="", employee_ids=None, count=1):
        normalized_ids = []
        for value in employee_ids or []:
            try:
                normalized_ids.append(int(value))
            except Exception:
                continue
        payload = {}
        if str(label or "").strip():
            payload["label"] = str(label).strip()
        if normalized_ids:
            payload["employee_ids"] = sorted(set(normalized_ids))
        try:
            safe_count = max(1, int(count))
        except Exception:
            safe_count = 1
        if safe_count > 1:
            payload["count"] = safe_count
        return json.dumps(payload, separators=(",", ":")) if payload else ""

    def _append_tracking_action_for_send(self, row, *, action_at=None, send_mode="sent"):
        if not row:
            return
        existing_actions = row.actions.all()
        has_any_action = existing_actions.exists()
        has_fresh_action = existing_actions.filter(action_type="fresh").exists()
        action_type = str(getattr(row, "mail_type", "fresh") or "fresh").strip().lower()
        action_type = "followup" if action_type == "followed_up" else "fresh"
        if not has_any_action:
            action_type = "fresh"
        elif action_type == "followup" and not has_fresh_action:
            action_type = "fresh"

        selected_employee_ids = sorted([emp.id for emp in row.selected_hrs.all() if emp.id])
        effective_action_at = action_at or timezone.now()
        notes = self._build_tracking_action_notes(employee_ids=selected_employee_ids)
        last_action = existing_actions.order_by("-created_at").first()
        if last_action and str(last_action.action_type or "").strip().lower() == action_type:
            last_day = timezone.localdate(last_action.action_at) if last_action.action_at else None
            current_day = timezone.localdate(effective_action_at)
            last_meta = self._tracking_action_note_meta(last_action.notes)
            last_employee_ids = sorted(last_meta.get("employee_ids") or [])
            if last_day == current_day and (not last_employee_ids or last_employee_ids == selected_employee_ids):
                next_count = int(last_meta.get("count") or 1) + 1
                last_action.notes = self._build_tracking_action_notes(
                    label=last_meta.get("label") or "",
                    employee_ids=selected_employee_ids,
                    count=next_count,
                )
                last_action.action_at = effective_action_at
                last_action.send_mode = send_mode
                last_action.save(update_fields=["notes", "action_at", "send_mode", "updated_at"])
                return

        TrackingAction.objects.create(
            tracking=row,
            action_type=action_type,
            send_mode=send_mode,
            action_at=effective_action_at,
            notes=notes,
        )

    def _resolve_attachment_payload(self, row):
        builder = row.resume.builder_data if row and row.resume and isinstance(row.resume.builder_data, dict) else {}
        title = str(getattr(row.resume, "title", "") or "").strip() or "Resume"
        saved_pdf_path = str(getattr(row.resume, "ats_pdf_path", "") or "").strip() if row and row.resume else ""

        if saved_pdf_path:
            saved_path = Path(saved_pdf_path)
            if saved_path.exists() and saved_path.is_file():
                return {"path": str(saved_path), "bytes": None}

        if builder:
            exact_pdf = self._build_builder_pdf_bytes(
                builder,
                filename_hint=title,
                preserve_highlights=True,
            )
            if exact_pdf:
                persisted_path = self._persist_attachment_pdf(row, builder, exact_pdf)
                if persisted_path:
                    return {"path": persisted_path, "bytes": None}
                return {"path": None, "bytes": exact_pdf}

        if not builder:
            return None

        text = self._builder_data_to_text(builder, fallback_title=title)
        if text.strip():
            return {"path": None, "bytes": self._build_simple_pdf_bytes(text, filename_hint=title)}
        return None

    def _build_builder_pdf_bytes(self, builder_data, filename_hint="resume", preserve_highlights=False):
        return build_builder_pdf_bytes(builder_data, preserve_highlights=preserve_highlights)

    def _persist_attachment_pdf(self, row, builder_data, pdf_bytes):
        if not row or not row.resume or not pdf_bytes:
            return None
        try:
            file_name = default_pdf_filename(builder_data, resume=row.resume)
            output_path = pick_local_pdf_path(file_name, row.resume.id if row.resume else None)
            output_path.write_bytes(pdf_bytes)
            row.resume.ats_pdf_path = str(output_path)
            row.resume.save(update_fields=["ats_pdf_path", "updated_at"])
            return str(output_path)
        except Exception:
            return None

    def _render_browser_pdf_bytes(self, html_text, browser_bins):
        return render_pdf_bytes_from_html(html_text)

    def _pdf_page_count(self, pdf_bytes):
        return pdf_page_count(pdf_bytes)

    def _available_browser_binaries(self):
        return available_browser_binaries()

    def _build_frontend_ats_pdf_html(self, builder_data):
        return build_frontend_ats_pdf_html(builder_data)

    def _sanitize_resume_html(self, value):
        raw = str(value or "")
        if not raw.strip():
            return ""
        text = re.sub(r"<script[^>]*>[\s\S]*?</script>", "", raw, flags=re.I)
        text = re.sub(r"<style[^>]*>[\s\S]*?</style>", "", text, flags=re.I)
        text = re.sub(r"\son[a-zA-Z]+\s*=\s*(['\"]).*?\1", "", text, flags=re.I | re.S)
        text = re.sub(r"\s(href|src)\s*=\s*(['\"])\s*javascript:.*?\2", "", text, flags=re.I | re.S)
        return text.strip()

    def _escape_html(self, value):
        return html.escape(str(value or ""), quote=True)

    def _resume_html_to_block(self, value):
        safe = self._sanitize_resume_html(value)
        if safe:
            return safe
        plain = self._plain_text_from_html(value)
        if not plain:
            return ""
        return f"<p>{self._escape_html(plain)}</p>"

    def _render_experience_html(self, item):
        if not isinstance(item, dict):
            return ""
        company = self._escape_html(item.get("company") or "")
        title = self._escape_html(item.get("title") or item.get("role") or "")
        start = str(item.get("startDate") or "").strip()
        end = "Present" if item.get("isCurrent") else str(item.get("endDate") or "").strip()
        date_line = self._escape_html(" - ".join(part for part in [start, end] if part))
        content = self._resume_html_to_block(item.get("highlights") or "")
        if not any([company, title, date_line, content]):
            return ""
        return f"""
        <div class="resume-exp">
          <div class="resume-exp-head">
            <div class="resume-exp-left">
              {f'<span class="resume-exp-company">{company}</span>' if company else ''}
              {'<span class="resume-exp-sep"> - </span>' if company and title else ''}
              {f'<span class="resume-exp-title">{title}</span>' if title else ''}
            </div>
            {f'<span class="resume-exp-right">{date_line}</span>' if date_line else ''}
          </div>
          <div class="resume-exp-body resume-rich">{content}</div>
        </div>
        """

    def _render_project_html(self, item):
        if not isinstance(item, dict):
            return ""
        name = self._escape_html(item.get("name") or "")
        link = str(item.get("normalizedUrl") or item.get("link") or "").strip()
        link_html = ""
        if link:
            safe_link = self._escape_html(link)
            link_html = f'<a class="resume-link resume-project-link" href="{safe_link}">link</a>'
        content = self._resume_html_to_block(item.get("highlights") or "")
        if not any([name, link_html, content]):
            return ""
        return f"""
        <div class="resume-exp">
          <div class="resume-exp-head">
            <div class="resume-exp-left">
              {f'<span class="resume-exp-company">{name}</span>' if name else ''}
              {link_html}
            </div>
          </div>
          <div class="resume-exp-body resume-rich">{content}</div>
        </div>
        """

    def _render_education_html(self, item):
        if not isinstance(item, dict):
            return ""
        institution = self._escape_html(item.get("institution") or "")
        program = self._escape_html(item.get("program") or "")
        score = self._escape_html(item.get("scoreText") or item.get("score") or "")
        start = str(item.get("startDate") or "").strip()
        end = "Present" if item.get("isCurrent") else str(item.get("endDate") or "").strip()
        date_line = self._escape_html(" - ".join(part for part in [start, end] if part))
        return f"""
        <div class="resume-exp">
          <div class="resume-exp-head">
            <div class="resume-exp-left">
              {f'<div class="resume-edu-inst"><span class="resume-exp-company">{institution}</span></div>' if institution else ''}
              {f'<div class="resume-edu-meta">{program}{(" | " + score) if program and score else score}</div>' if (program or score) else ''}
            </div>
            {f'<span class="resume-exp-right">{date_line}</span>' if date_line else ''}
          </div>
        </div>
        """

    def _render_custom_section_html(self, item):
        if not isinstance(item, dict):
            return ""
        title = self._escape_html(item.get("title") or "Custom Section")
        content = self._resume_html_to_block(item.get("content") or "")
        if not content:
            return ""
        return f'<section class="resume-section"><h2>{title}</h2><div class="resume-rich">{content}</div></section>'

    def _build_resume_pdf_html(self, builder_data, fallback_title="Resume", page_margin_in=0.55):
        data = builder_data if isinstance(builder_data, dict) else {}
        basics = data.get("basics") if isinstance(data.get("basics"), dict) else {}
        full_name = self._escape_html(
            basics.get("fullName")
            or data.get("fullName")
            or data.get("resumeTitle")
            or fallback_title
            or "Resume"
        )
        contact_line = " | ".join(
            self._escape_html(part)
            for part in [
                basics.get("location") or data.get("location"),
                basics.get("phone"),
                basics.get("email"),
            ]
            if str(part or "").strip()
        )
        links = []
        for label, key in [
            ("LinkedIn", "linkedin"),
            ("GitHub", "github"),
            ("Portfolio", "portfolio"),
        ]:
            value = str(basics.get(key) or "").strip()
            if value:
                links.append(f'<a href="{self._escape_html(value)}">{label}</a>')
        sections = []
        summary_html = self._resume_html_to_block(data.get("summary") or "")
        if summary_html:
            sections.append(f'<section class="resume-section"><h2>Summary</h2><div class="resume-summary">{summary_html}</div></section>')

        skills = data.get("skills")
        skills_html = ""
        if isinstance(skills, list):
            skills_values = ", ".join(str(item).strip() for item in skills if str(item).strip())
            if skills_values:
                skills_html = f"<p>{self._escape_html(skills_values)}</p>"
        else:
            skills_html = self._resume_html_to_block(skills or "")
        if skills_html:
            sections.append(f'<section class="resume-section"><h2>Skills</h2><div class="resume-rich">{skills_html}</div></section>')

        experiences = "".join(self._render_experience_html(item) for item in (data.get("experiences") or []))
        if experiences.strip():
            sections.append(f'<section class="resume-section"><h2>Experience</h2>{experiences}</section>')

        projects = "".join(self._render_project_html(item) for item in (data.get("projects") or []))
        if projects.strip():
            sections.append(f'<section class="resume-section"><h2>Projects</h2>{projects}</section>')

        educations = "".join(self._render_education_html(item) for item in (data.get("educations") or []))
        if educations.strip():
            sections.append(f'<section class="resume-section"><h2>Education</h2>{educations}</section>')

        for item in (data.get("customSections") or []):
            custom = self._render_custom_section_html(item)
            if custom:
                sections.append(custom)

        if not sections:
            return ""

        safe_margin_in = max(0.2, min(0.75, float(page_margin_in or 0.55)))

        return f"""<!DOCTYPE html>
<html>
<head>
  <meta charset="utf-8" />
  <title>{full_name}</title>
  <style>
    @page {{ size: A4; margin: {safe_margin_in}in; }}
    html, body {{ margin: 0; padding: 0; background: #fff; color: #111827; font-family: Arial, Helvetica, sans-serif; }}
    body {{ padding: 0.1in 0; font-size: 10pt; line-height: 1.25; -webkit-print-color-adjust: exact; print-color-adjust: exact; }}
    .resume-sheet {{ color: #111827; }}
    .resume-head {{ margin-bottom: 6pt; padding-bottom: 2pt; text-align: center; border-bottom: 0; }}
    .resume-head h1 {{ margin: 0; font-size: 20pt; font-weight: 700; letter-spacing: 0.02em; }}
    .resume-head-line, .resume-head-links {{ color: #374151; }}
    .resume-head-line {{ margin-top: 2pt; }}
    .resume-head-links {{ margin-top: 2pt; word-break: break-word; }}
    .resume-head-links a, .resume-link {{ color: inherit; text-decoration: none; }}
    .resume-section {{ margin-top: 8pt; }}
    .resume-section h2 {{ margin: 0 0 2pt; font-size: 11pt; font-weight: 700; text-transform: uppercase; letter-spacing: 0.08em; border-bottom: 1px solid #d1d5db; padding-bottom: 1pt; }}
    .resume-exp {{ margin-top: 4pt; }}
    .resume-exp-head {{ display: flex; justify-content: space-between; gap: 12pt; align-items: baseline; font-weight: 700; }}
    .resume-exp-left {{ min-width: 0; flex: 1; }}
    .resume-exp-right, .resume-project-link {{ font-weight: 400; color: #374151; text-decoration: none; white-space: nowrap; }}
    .resume-rich p, .resume-summary p {{ margin: 2pt 0 0; line-height: 1.35; }}
    .resume-rich ul, .resume-summary ul, .resume-rich ol, .resume-summary ol {{ margin: 4pt 0 0; padding-left: 16pt; }}
    .resume-rich li, .resume-summary li {{ margin: 1.5pt 0; }}
    .resume-edu-meta {{ margin-top: 1pt; font-weight: 400; }}
    * {{ box-shadow: none !important; text-shadow: none !important; filter: none !important; }}
  </style>
</head>
<body>
  <article class="resume-sheet">
    <header class="resume-head">
      <h1>{full_name}</h1>
      {f'<div class="resume-head-line">{contact_line}</div>' if contact_line else ''}
      {f'<div class="resume-head-links">{" | ".join(links)}</div>' if links else ''}
    </header>
    {"".join(sections)}
  </article>
</body>
</html>"""

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

        summary = self._plain_text_from_html(b.get("summary") or "")
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
                highlights = self._plain_text_from_html(item.get("highlights") or "")
                if highlights:
                    lines.append(highlights)
            lines.append("")

        skills = b.get("skills")
        if isinstance(skills, list) and skills:
            lines.append("Skills")
            lines.append(", ".join(str(x).strip() for x in skills if str(x).strip()))
        else:
            skills_text = self._plain_text_from_html(skills or "")
            if skills_text:
                lines.extend(["Skills", skills_text])
        return "\n".join(lines).strip()

    def _plain_text_from_html(self, value):
        text = str(value or "")
        text = re.sub(r"<style[^>]*>[\s\S]*?</style>", " ", text, flags=re.I)
        text = re.sub(r"<script[^>]*>[\s\S]*?</script>", " ", text, flags=re.I)
        text = re.sub(r"</li>\s*<li[^>]*>", "\n", text, flags=re.I)
        text = text.replace("</li>", "\n")
        text = re.sub(r"<li[^>]*>", "- ", text, flags=re.I)
        text = re.sub(r"</p>|</div>|</h[1-6]>", "\n", text, flags=re.I)
        text = re.sub(r"<br\s*/?>", "\n", text, flags=re.I)
        text = re.sub(r"<[^>]+>", " ", text)
        text = (
            text.replace("&nbsp;", " ")
            .replace("&amp;", "&")
            .replace("&lt;", "<")
            .replace("&gt;", ">")
        )
        text = re.sub(r"[ \t]+\n", "\n", text)
        text = re.sub(r"\n{3,}", "\n\n", text)
        text = re.sub(r"[ \t]{2,}", " ", text)
        return text.strip()

    def _build_simple_pdf_bytes(self, text, filename_hint="resume"):
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

        payload = bytearray()
        offsets = [0]

        def write(chunk):
            payload.extend(chunk)

        write(b"%PDF-1.4\n")
        for obj in objects:
            offsets.append(len(payload))
            write(obj)
        xref_pos = len(payload)
        write(f"xref\n0 {len(offsets)}\n".encode("latin-1"))
        write(b"0000000000 65535 f \n")
        for off in offsets[1:]:
            write(f"{off:010d} 00000 n \n".encode("latin-1"))
        write(
            f"trailer << /Size {len(offsets)} /Root 1 0 R >>\nstartxref\n{xref_pos}\n%%EOF\n".encode("latin-1")
        )
        return bytes(payload)

    def _write_simple_pdf(self, text, filename_hint="resume"):
        safe_hint = re.sub(r"[^a-zA-Z0-9._-]+", "_", str(filename_hint or "resume")).strip("_") or "resume"
        fd, tmp_path = tempfile.mkstemp(prefix=f"{safe_hint}_", suffix=".pdf")
        os.close(fd)
        path = Path(tmp_path)
        with path.open("wb") as f:
            f.write(self._build_simple_pdf_bytes(text, filename_hint=filename_hint))
        return str(path)

    def _pdf_escape(self, value):
        text = str(value or "")
        text = text.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")
        return text

    def _get_profile(self, user_id):
        try:
            return UserProfile.objects.get(user_id=user_id)
        except UserProfile.DoesNotExist:
            return None

    def _slug_attachment_name(self, value):
        return re.sub(r"[^a-z0-9]+", "", str(value or "").strip().lower())

    def _normalized_yoe_token(self, value):
        raw = str(value or "").strip().lower()
        if not raw:
            return ""
        match = re.search(r"\d+(?:\.\d+)?", raw)
        if not match:
            return ""
        token = match.group(0)
        if "." in token:
            token = token.rstrip("0").rstrip(".")
        return token

    def _attachment_download_name(self, row, profile=None, attachment_path=None):
        builder = row.resume.builder_data if row and row.resume and isinstance(getattr(row.resume, "builder_data", None), dict) else {}
        basics = builder.get("basics") if isinstance(builder.get("basics"), dict) else {}
        full_name = (
            str(basics.get("fullName") or "").strip()
            or str(builder.get("fullName") or "").strip()
            or str(getattr(profile, "full_name", "") or "").strip()
            or str(getattr(row.user, "get_full_name", lambda: "")() or "").strip()
            or str(getattr(row.user, "username", "") or "").strip()
        )
        name_token = self._slug_attachment_name(full_name) or "resume"

        yoe_token = (
            self._normalized_yoe_token(getattr(profile, "years_of_experience", "") or "")
            or self._normalized_yoe_token(basics.get("yearsOfExperience") or "")
            or self._normalized_yoe_token(builder.get("yearsOfExperience") or "")
        )
        if not yoe_token and attachment_path:
            match = re.search(r"_(\d+(?:\.\d+)?)yoe\.pdf$", Path(attachment_path).name, flags=re.I)
            if match:
                yoe_token = match.group(1)

        if yoe_token:
            return f"{name_token}_{yoe_token}yoe.pdf"
        return f"{name_token}.pdf"

    def _get_achievements(self, row):
        template_ids = getattr(row, "template_ids_ordered", None)
        if isinstance(template_ids, list) and template_ids:
            target_ids = [str(item or "").strip() for item in template_ids if str(item or "").strip()]
            return resolve_template_ids_for_user(row.user, target_ids)
        template = getattr(row, "template", None)
        if getattr(row, "template_id", None) and template is not None:
            return [template]
        return []

    def _template_category(self, row):
        return str(getattr(row, "category", "general") or "general").strip().lower() or "general"

    def _template_sequence_is_ready(self, rows, mail_type):
        items = list(rows or [])
        normalized_mail_type = str(mail_type or "fresh").strip().lower()
        if not items:
            return False
        if normalized_mail_type == "followed_up":
            return 1 <= len(items) <= 2
        return len(items) >= 1

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

    def _preferred_employee_name(self, employee):
        first_name = str(getattr(employee, "first_name", "") or "").strip()
        if first_name:
            return self._display_first_name(first_name)

        full_name = str(getattr(employee, "name", "") or "").strip()
        if not full_name:
            return "there"

        parts = [part for part in re.split(r"\s+", full_name) if part]
        if parts:
            return self._display_first_name(parts[0])
        return self._display_first_name(full_name) or "there"

    def _display_first_name(self, value):
        raw = str(value or "").strip()
        if not raw:
            return ""
        token = raw.split()[0].strip()
        if not token:
            return ""
        return token[:1].upper() + token[1:]

    def _display_company_name(self, value):
        raw = str(value or "").strip()
        if not raw:
            return "Your company"
        return raw[:1].upper() + raw[1:]

    def _capitalize_inserted_value(self, key, value):
        normalized_key = str(key or "").strip().lower()
        if normalized_key == "job_id_line":
            return str(value or "")
        text = " ".join(str(value or "").split()).strip()
        if not text:
            return ""
        if normalized_key in {"name", "employee_name", "first_name"}:
            return self._display_first_name(text)
        if normalized_key in {"company", "company_name", "role", "profile_role", "employee_role", "employee_department", "interview_round", "user_name", "full_name"}:
            return text[:1].upper() + text[1:]
        if normalized_key in {"resume_link", "job_link", "sender_linkedin", "employee_email", "sender_email"}:
            return text
        if normalized_key == "employee_focus_area":
            return text[:1].lower() + text[1:] if text else ""
        if normalized_key == "skills_text":
            parts = [part.strip() for part in re.split(r"\s*,\s*", text) if part.strip()]
            if not parts:
                return text[:1].upper() + text[1:]
            return ", ".join(part[:1].upper() + part[1:] for part in parts)
        return text

    def _profile_role_text(self, row, profile):
        job = getattr(row, "job", None)
        if getattr(row, "job_id", None) and job and str(getattr(job, "role", "") or "").strip():
            return str(job.role).strip()
        summary = self._plain_text_from_html(getattr(profile, "summary", "") or "") if profile else ""
        first_line = next((line.strip() for line in summary.splitlines() if line.strip()), "")
        if first_line:
            return first_line
        return "Software engineer"

    def _profile_skills_text(self, row):
        builder = row.resume.builder_data if row and row.resume and isinstance(getattr(row.resume, "builder_data", None), dict) else {}
        skills = builder.get("skills")
        if isinstance(skills, list):
            values = [str(item).strip() for item in skills if str(item).strip()]
            if values:
                return ", ".join(values)
        text = self._plain_text_from_html(skills or "")
        if text:
            return text
        return "Python, Django, React, FastAPI, MCP"

    def _profile_resume_link(self, profile):
        configured = str(getattr(profile, "resume_link", "") or "").strip() if profile else ""
        return configured

    def _sender_identity(self, row, profile):
        full_name = (
            str(getattr(profile, "full_name", "") or "").strip()
            or str(getattr(getattr(row, "user", None), "get_full_name", lambda: "")() or "").strip()
            or str(getattr(getattr(row, "user", None), "username", "") or "").strip()
            or "User"
        )
        email = (
            str(getattr(profile, "email", "") or "").strip()
            or str(getattr(getattr(row, "user", None), "email", "") or "").strip()
        )
        contact = str(getattr(profile, "contact_number", "") or "").strip() if profile else ""
        linkedin = str(getattr(profile, "linkedin_url", "") or "").strip() if profile else ""
        resume_link = self._profile_resume_link(profile)
        return {
            "full_name": full_name,
            "first_name": self._display_first_name(full_name) or "User",
            "email": email,
            "contact": contact,
            "linkedin": linkedin,
            "resume_link": resume_link,
        }

    def _employee_focus_area_text(self, employee):
        about = " ".join(str(getattr(employee, "about", "") or "").split()).strip()
        role = str(getattr(employee, "JobRole", "") or "").strip()
        department = str(getattr(employee, "department", "") or "").strip()

        if about:
            patterns = [
                r"\bexperienced\s+in\s+([^.;,\n]{4,90})",
                r"\bexperience\s+(?:across|in|with)\s+([^.;,\n]{4,90})",
                r"\bbackground\s+in\s+([^.;,\n]{4,90})",
                r"\bfocused\s+on\s+([^.;,\n]{4,90})",
                r"\bworking\s+on\s+([^.;,\n]{4,90})",
            ]
            for pattern in patterns:
                match = re.search(pattern, about, flags=re.I)
                if match:
                    return " ".join(match.group(1).split()).strip(" -,:;")

        merged = f"{role} {department}".lower()
        if any(token in merged for token in ["talent", "recruit", "hiring", "acquisition", "hr"]):
            return "technical and non-technical hiring"
        if "backend" in merged:
            return "backend engineering"
        if "frontend" in merged:
            return "frontend engineering"
        if "full" in merged and "stack" in merged:
            return "full-stack engineering"
        if "software" in merged or "engineer" in merged or "engineering" in merged:
            return "software engineering"
        if department:
            return department.lower()
        if role:
            return role.lower()
        return "your field"

    def _sender_first_name(self, row, profile):
        return self._sender_identity(row, profile).get("first_name") or "User"

    def _resolve_openai_model(self, user=None):
        return resolve_openai_settings(user).get("model", "gpt-4o")

    def _openai_generate_text(self, prompt, *, system, user=None):
        settings = resolve_openai_settings(user)
        api_key = settings.get("api_key", "").strip()
        if not api_key:
            return None, "OPENAI_API_KEY is not set"

        system_prompt = str(system or "").strip()
        task_instructions = str(settings.get("task_instructions", "") or "").strip()
        if task_instructions:
            system_prompt = f"{system_prompt}\n\nAdditional user instructions:\n{task_instructions[:2000]}"

        payload = {
            "model": self._resolve_openai_model(user),
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": str(prompt or "").strip()[:8000]},
            ],
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
            content = data.get("choices", [{}])[0].get("message", {}).get("content", "")
            text = str(content or "").strip()
            if not text:
                return None, "AI response was empty"
            return text, ""
        except urllib.error.HTTPError as exc:
            try:
                body = exc.read().decode("utf-8")
            except Exception:  # noqa: BLE001
                body = ""
            return None, f"OpenAI request failed: {body or exc.reason}"
        except Exception as exc:  # noqa: BLE001
            return None, f"OpenAI request failed: {exc}"

    def _resume_attachment_line(self, row):
        has_attached_resume = False
        if row.resume and isinstance(getattr(row.resume, "builder_data", None), dict) and row.resume.builder_data:
            has_attached_resume = True
        if has_attached_resume:
            return "I have attached my resume for your reference."
        return "I am happy to share my resume if helpful."

    def _build_signature(self, row, profile):
        mail_type = str(getattr(row, "mail_type", "") or "").strip().lower() if row else ""
        sender = self._sender_identity(row, profile)
        sender_name = str(sender.get("full_name") or "").strip()
        if mail_type == "followed_up":
            sign_parts = [
                "Thanks,",
                sender_name,
            ]
        else:
            sign_parts = [
                "Thanks,",
                *self._sender_detail_lines(
                    sender_name,
                    sender.get("email"),
                    sender.get("contact"),
                    sender.get("linkedin"),
                ),
            ]
        return "\n".join([p for p in sign_parts if str(p or "").strip()])

    def _inject_dynamic_names(self, text, employee_name, sender_name):
        value = str(text or "")
        emp = str(employee_name or "").strip()
        snd = str(sender_name or "").strip()

        if emp:
            for token in ["[]", "[Name]", "[Employee Name]", "<name>", "<employee_name>", "{{name}}", "{name}"]:
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

    def _display_interaction_time(self, row):
        raw_value = str(getattr(row, "interaction_time", "") or "").strip() if row else ""
        if not raw_value:
            return self._format_interaction_date(row)
        try:
            parsed = datetime.fromisoformat(raw_value.replace("Z", "+00:00"))
            return parsed.strftime("%d %b %Y, %I:%M %p")
        except Exception:  # noqa: BLE001
            return raw_value

    def _approved_preview_for_employee(self, row, employee, to_email=""):
        payloads = getattr(row, "approved_test_mail_payloads", None)
        if not isinstance(payloads, list):
            return None
        normalized_mail_type = str(getattr(row, "mail_type", "fresh") or "fresh").strip().lower()
        employee_id = getattr(employee, "id", None)
        normalized_email = str(to_email or getattr(employee, "email", "") or "").strip().lower()
        for item in payloads:
            if not isinstance(item, dict):
                continue
            subject = str(item.get("subject") or "").strip()
            body = str(item.get("body") or "").strip()
            if not subject or not body:
                continue
            if normalized_mail_type != "followed_up":
                subject = self._fresh_subject(subject)
                if not subject:
                    continue
            item_employee_id = item.get("employee_id")
            item_email = str(item.get("email") or "").strip().lower()
            if employee_id and str(item_employee_id or "") == str(employee_id):
                return {"subject": subject, "body": body}
            if normalized_email and item_email and item_email == normalized_email:
                return {"subject": subject, "body": body}
        return None

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

    def _clean_single_paragraph(self, text, *, max_words=None):
        value = " ".join(str(text or "").split()).strip()
        if not value:
            return ""
        if max_words:
            words = value.split()
            if len(words) > int(max_words):
                value = " ".join(words[: int(max_words)]).rstrip(",;:-")
        return value.rstrip(".") + "."

    def _strip_leading_greeting(self, text):
        value = " ".join(str(text or "").split()).strip()
        if not value:
            return ""
        value = re.sub(r"^(hi|hello|dear)\s+[^,:\n]{1,80}[,:]\s*", "", value, flags=re.I)
        return value.strip()

    def _build_cold_applied_personalization_prompt(self, employee, company_name, role):
        about = str(getattr(employee, "about", "") or "").strip()
        employee_role = str(getattr(employee, "JobRole", "") or "").strip()
        department = str(getattr(employee, "department", "") or "").strip()
        profile_url = str(getattr(employee, "profile", "") or "").strip()
        return (
            "Write exactly one personalized opening paragraph for a cold outreach email.\n"
            "Rules:\n"
            "- Exactly 30 to 35 words.\n"
            "- Single paragraph, plain text.\n"
            "- Warm, professional, human tone.\n"
            "- Focus on the employee's background/profile only.\n"
            "- Do not mention the sender's achievements, ask, signature, email, phone, or LinkedIn.\n"
            "- Do not use placeholders.\n\n"
            f"Employee name: {self._preferred_employee_name(employee)}\n"
            f"Employee role: {employee_role or '(unknown)'}\n"
            f"Employee department: {department or '(unknown)'}\n"
            f"Company: {company_name or 'the company'}\n"
            f"Target role applied for: {role or 'the role'}\n"
            f"Employee profile/about: {about or '(not provided)'}\n"
            f"Employee profile URL: {profile_url or '(not provided)'}\n"
        )

    def _cold_applied_personalized_intro(self, employee, company_name, role, *, allow_generate=False):
        existing = self._strip_leading_greeting(
            self._clean_single_paragraph(getattr(employee, "personalized_template", "") or "", max_words=35)
        )
        if existing:
            return existing

        if allow_generate:
            prompt = self._build_cold_applied_personalization_prompt(employee, company_name, role)
            system = (
                "You write concise personalized first paragraphs for job outreach emails. "
                "Return plain text only, one paragraph, 30 to 35 words."
            )
            generated, error = self._openai_generate_text(prompt, system=system, user=employee.user)
            if generated and not error:
                cleaned = self._strip_leading_greeting(self._clean_single_paragraph(generated, max_words=35))
                if cleaned:
                    employee.personalized_template = cleaned
                    employee.save(update_fields=["personalized_template", "updated_at"])
                    return cleaned

        return self._strip_leading_greeting(self._employee_personalization(employee, company_name, max_about_chars=140))

    def _mail_placeholder_pairs(self, row=None, employee=None, profile=None, *, company_name="", role="", job_id="", job_link="", employee_email=""):
        current_employer = str(getattr(profile, "current_employer", "") or "").strip() if profile else ""
        sender = self._sender_identity(row, profile)
        sender_full_name = str(sender.get("full_name") or "").strip()
        employee_name = self._preferred_employee_name(employee)
        employee_role = str(getattr(employee, "JobRole", "") or "").strip()
        employee_department = str(getattr(employee, "department", "") or "").strip()
        normalized_job_link = str(job_link or "").strip()
        first_name = self._display_first_name(employee_name)
        yoe = str(getattr(profile, "years_of_experience", "") or "").strip() if profile else ""
        interview_round = str(getattr(row, "interview_round", "") or "").strip() if row else ""
        return [
            ("name", employee_name),
            ("employee_name", employee_name),
            ("first_name", first_name),
            ("user_name", sender_full_name),
            ("employee_role", employee_role),
            ("department", employee_department),
            ("employee_department", employee_department),
            ("company_name", str(company_name or "").strip()),
            ("current_employer", current_employer),
            ("role", str(role or "").strip()),
            ("job_id", str(job_id or "").strip()),
            ("job_id_line", f" (Job ID: {str(job_id or '').strip()})" if str(job_id or "").strip() else ""),
            ("job_link", normalized_job_link),
            ("resume_link", str(sender.get("resume_link") or "").strip()),
            ("years_of_experience", yoe),
            ("yoe", yoe),
            ("interaction_time", self._display_interaction_time(row)),
            ("interview_round", interview_round),
        ]

    def _mail_placeholder_map(self, row, employee, profile, *, company_name="", role="", job_id="", job_link="", employee_email=""):
        return dict(
            self._mail_placeholder_pairs(
                row,
                employee,
                profile,
                company_name=company_name,
                role=role,
                job_id=job_id,
                job_link=job_link,
                employee_email=employee_email,
            )
        )

    def _allowed_dynamic_placeholder_keys(self):
        return {key for key, _value in self._mail_placeholder_pairs()}

    def _render_mail_placeholders(self, text, replacements):
        value = str(text or "")
        if not value:
            return ""
        allowed_keys = self._allowed_dynamic_placeholder_keys()
        mapping = {
            key: replacement
            for key, replacement in (replacements or {}).items()
            if str(key or "").strip() in allowed_keys
        }
        for key, replacement in mapping.items():
            safe_value = self._capitalize_inserted_value(key, replacement)
            value = value.replace(f"{{{key}}}", safe_value)
            value = value.replace(f"[{key}]", safe_value)
        value = re.sub(r"\{[A-Za-z_][A-Za-z0-9_]*\}", "", value)
        value = re.sub(r"\[[A-Za-z_][A-Za-z0-9_]*\]", "", value)
        # Clean punctuation artifacts left behind by empty placeholders.
        value = re.sub(r"\bAt\s*,\s*", "", value, flags=re.I)
        value = re.sub(r"\s+\(", " (", value)
        value = re.sub(r"\s+,", ",", value)
        value = re.sub(r"\(\s*\)", "", value)
        value = re.sub(r"\s+-\s*(?=[,.)]|$)", "", value)
        value = re.sub(r"[ \t]{2,}", " ", value)
        value = re.sub(r"\s+\n", "\n", value)
        value = re.sub(r"\n\s+", "\n", value)
        return value.strip()

    def _ordered_achievement_paragraphs(self, achievements, replacements=None):
        paragraphs = []
        for ach in achievements or []:
            if self._template_category(ach) == "personalized":
                continue
            detail = self._render_mail_placeholders(getattr(ach, "achievement", "") or "", replacements)
            if not detail:
                continue
            if not detail.endswith("."):
                detail += "."
            paragraphs.append(detail)
            if len(paragraphs) >= 5:
                break
        return paragraphs

    def _hardcoded_personalized_intro(self, row, replacements=None):
        template = getattr(row, "personalized_template", None)
        if not template:
            return ""
        text = self._render_mail_placeholders(getattr(template, "achievement", "") or "", replacements)
        if not text:
            return ""
        if not text.endswith("."):
            text += "."
        return self._strip_leading_greeting(text)

    def _sender_detail_lines(self, sender_name, email, contact, linkedin):
        lines = []
        if sender_name:
            lines.append(str(sender_name).strip())
        if contact:
            lines.append(f"Contact: {str(contact).strip()}")
        if email:
            lines.append(f"Email: {str(email).strip()}")
        if linkedin:
            lines.append(f"LinkedIn: {str(linkedin).strip()}")
        return lines

    def _build_ordered_hardcoded_mail(self, *, row=None, emp_name, intro_paragraphs=None, achievement_paragraphs=None, ask_line="", attachment_line="", sender_name="", email="", contact="", linkedin=""):
        body_sections = [f"Hi {emp_name},"]

        for paragraph in intro_paragraphs or []:
            text = " ".join(str(paragraph or "").split()).strip()
            if text:
                body_sections.append(text)

        for paragraph in achievement_paragraphs or []:
            text = " ".join(str(paragraph or "").split()).strip()
            if text:
                body_sections.append(text)

        ask_text = " ".join(str(ask_line or "").split()).strip()
        if ask_text:
            body_sections.append(ask_text)

        attachment_text = " ".join(str(attachment_line or "").split()).strip()
        if attachment_text:
            body_sections.append(attachment_text)

        signature_text = self._build_signature(row, None)
        if signature_text:
            body_sections.append(signature_text)

        return "\n\n".join([section for section in body_sections if section])

    def _build_mail(self, row, employee, profile, achievements, *, use_ai=False):
        job = row.job
        company_name = self._display_company_name(job.company.name if row.job_id and job and job.company_id else "your company")
        role = str(job.role or "").strip() if row.job_id and job else ""
        job_id = str(job.job_id or "").strip() if row.job_id and job else ""
        job_link = str(getattr(job, "job_link", "") or "").strip() if row.job_id and job else ""
        emp_name = self._preferred_employee_name(employee)
        mail_type = str(getattr(row, "mail_type", "fresh") or "fresh").strip().lower()
        choice = "follow_up_applied" if mail_type == "followed_up" else "cold_applied"
        sender_name = self._sender_first_name(row, profile)
        resolved_email = self._resolve_employee_email(employee, str(getattr(job.company, "mail_format", "") or "").strip()) if row.job_id and job and job.company_id else str(getattr(employee, "email", "") or "").strip()
        placeholder_values = self._mail_placeholder_map(
            row,
            employee,
            profile,
            company_name=company_name,
            role=role,
            job_id=job_id,
            job_link=job_link,
            employee_email=resolved_email,
        )
        approved_preview = self._approved_preview_for_employee(row, employee, resolved_email)
        if approved_preview:
            return approved_preview["subject"], approved_preview["body"]

        attachment_line = self._resume_attachment_line(row)
        ordered_template_paragraphs = self._ordered_achievement_paragraphs(achievements, placeholder_values)
        personalized_intro = self._hardcoded_personalized_intro(row, placeholder_values)

        subject = self._default_subject_for_template(
            choice,
            role or "role",
            company_name,
            emp_name,
            job_id,
        )
        saved_subject = self._render_mail_placeholders(str(getattr(row, "mail_subject", "") or "").strip(), placeholder_values)
        if saved_subject:
            subject = saved_subject
        body = self._build_ordered_hardcoded_mail(
            row=row,
            emp_name=emp_name,
            intro_paragraphs=[personalized_intro] if personalized_intro else [],
            achievement_paragraphs=ordered_template_paragraphs,
            ask_line="",
            attachment_line=attachment_line,
            sender_name=sender_name,
            email=str(getattr(profile, "email", "") or row.user.email or "").strip(),
            contact=str(getattr(profile, "contact_number", "") or "").strip(),
            linkedin=str(getattr(profile, "linkedin_url", "") or "").strip(),
        )
        subject = self._inject_dynamic_names(subject, emp_name, sender_name)
        if mail_type != "followed_up":
            subject = self._fresh_subject(subject)
        body = self._inject_dynamic_names(body, emp_name, sender_name)
        return subject, body

    def _body_html(self, body):
        text = str(body or "").replace("\r\n", "\n")
        if not text.strip():
            return ""
        if re.search(r"(?is)^\s*(<!doctype html\b|<html\b)", text) or 'class="resume-sheet"' in text or "class='resume-sheet'" in text:
            return text

        def _linkify(segment):
            escaped = html.escape(segment, quote=True)
            escaped = re.sub(
                r'(https?://[^\s<]+)',
                lambda match: f'<a href="{match.group(1)}">{match.group(1)}</a>',
                escaped,
            )
            escaped = re.sub(
                r'(?<!["/=])\b([A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,})\b',
                lambda match: f'<a href="mailto:{match.group(1)}">{match.group(1)}</a>',
                escaped,
            )
            return escaped

        paragraphs = []
        for block in re.split(r"\n\s*\n", text):
            lines = [line.strip() for line in block.split("\n")]
            rendered_lines = [_linkify(line) if line else "" for line in lines]
            paragraphs.append("<br>".join(rendered_lines))

        return (
            '<html><body style="font-family: Arial, sans-serif; font-size: 14px; line-height: 1.6; color: #111827;">'
            + "".join(f"<p>{paragraph}</p>" for paragraph in paragraphs if paragraph.strip())
            + "</body></html>"
        )

    def _send_email(self, user, to_email, subject, body, attachment_path=None, attachment_bytes=None, *, attachment_name=None, in_reply_to="", references=None):
        smtp_settings = resolve_smtp_settings(user)
        host = smtp_settings.get("host", "")
        port = int(smtp_settings.get("port", 587) or 587)
        username = smtp_settings.get("username", "")
        password = smtp_settings.get("password", "")
        use_tls = bool(smtp_settings.get("use_tls", True))
        from_email = str(smtp_settings.get("from_email", "") or "").strip() or username or str(user.email or "").strip()
        if not host or not from_email:
            raise RuntimeError("SMTP_HOST / SMTP_FROM_EMAIL (or SMTP_USER) is not configured.")

        html_body = self._body_html(body)
        content_part = MIMEMultipart("alternative")
        content_part.attach(MIMEText(body, "plain", "utf-8"))
        if html_body:
            content_part.attach(MIMEText(html_body, "html", "utf-8"))

        if attachment_path or attachment_bytes:
            msg = MIMEMultipart()
            msg.attach(content_part)
            try:
                part = MIMEBase("application", "octet-stream")
                if attachment_bytes is not None:
                    part.set_payload(attachment_bytes)
                    fallback_name = "resume.pdf"
                else:
                    file_path = Path(attachment_path)
                    with file_path.open("rb") as fh:
                        part.set_payload(fh.read())
                    fallback_name = file_path.name
                encoders.encode_base64(part)
                download_name = str(attachment_name or "").strip() or fallback_name
                part.add_header("Content-Disposition", f'attachment; filename="{download_name}"')
                msg.attach(part)
            except Exception:  # noqa: BLE001
                # Soft-fail attachment and continue with multipart mail body.
                msg = content_part
        else:
            msg = content_part
        msg["Subject"] = subject
        msg["From"] = from_email
        msg["To"] = to_email
        domain = str(from_email.split("@", 1)[1] if "@" in from_email else "").strip() or None
        message_id = self._normalize_message_id(make_msgid(domain=domain))
        msg["Message-ID"] = message_id
        normalized_reply_to = self._normalize_message_id(in_reply_to)
        if normalized_reply_to:
            msg["In-Reply-To"] = normalized_reply_to
        thread_references = self._thread_reference_list(references, normalized_reply_to)
        if thread_references:
            msg["References"] = " ".join(thread_references)
        # No CC by design.

        with smtplib.SMTP(host, port, timeout=30) as server:
            if use_tls:
                server.starttls()
            if username and password:
                server.login(username, password)
            server.sendmail(from_email, [to_email], msg.as_string())
        return message_id

    def _log_success(self, mail_tracking, tracking, employee, subject, body, to_email, *, simulated=False, message_id="", in_reply_to="", references=None):
        notes = "Mail send simulated in test mode." if simulated else "Mail sent from cron command."
        normalized_message_id = self._normalize_message_id(message_id)
        normalized_reply_to = self._normalize_message_id(in_reply_to)
        thread_references = self._thread_reference_list(references, normalized_reply_to)
        log_mail_event(
            mail_tracking=mail_tracking,
            tracking=tracking,
            employee=employee,
            status="sent",
            notes=notes,
            subject=subject,
            body=body,
            to_email=to_email,
            raw_payload={
                "to_email": to_email,
                "subject": subject,
                "body": body,
                "cc": [],
                "status": "sent",
                "simulated": bool(simulated),
                "message_id": normalized_message_id,
                "in_reply_to": normalized_reply_to,
                "references": thread_references,
            },
            source_message_id=normalized_message_id,
        )

    def _log_event(self, mail_tracking, tracking, employee, success, subject, body, to_email, notes, event_status=None):
        normalized_status = str(event_status or ("sent" if success else "failed")).strip().lower()
        if normalized_status not in {"pending", "sent", "failed", "bounced"}:
            normalized_status = "failed"
        log_mail_event(
            mail_tracking=mail_tracking,
            tracking=tracking,
            employee=employee,
            status=normalized_status,
            notes=notes,
            subject=subject,
            body=body,
            to_email=to_email,
            raw_payload={
                "to_email": to_email,
                "subject": subject,
                "body": body,
                "cc": [],
                "status": normalized_status,
                "reason": str(notes or "").strip(),
            },
        )
