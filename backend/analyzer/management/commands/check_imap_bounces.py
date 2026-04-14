import email
import imaplib
import re
from datetime import timedelta
from email.header import decode_header

from django.core.management.base import BaseCommand
from django.db.models import Q
from django.utils import timezone

from analyzer.models import Employee, MailTrackingEvent, Tracking


class Command(BaseCommand):
    help = "Scan IMAP inbox for bounce emails and update tracking delivery status."

    def add_arguments(self, parser):
        parser.add_argument("--user-id", type=int, default=None, help="Process bounce mapping only for this user id")
        parser.add_argument("--limit", type=int, default=100, help="Max IMAP messages to process")
        parser.add_argument("--since-days", type=int, default=14, help="Search recent emails in last N days")
        parser.add_argument("--scheduled-today-only", action="store_true", help="Only update rows scheduled for today (local timezone) with mailed=true")
        parser.add_argument("--dry-run", action="store_true", help="Do not write DB changes")

    def handle(self, *args, **options):
        import os

        user_id = options.get("user_id")
        limit = int(options.get("limit") or 100)
        since_days = int(options.get("since_days") or 14)
        scheduled_today_only = bool(options.get("scheduled_today_only"))
        dry_run = bool(options.get("dry_run"))

        host = str(os.getenv("IMAP_HOST", "")).strip()
        port = int(str(os.getenv("IMAP_PORT", "993")).strip() or 993)
        username = str(os.getenv("IMAP_USER", "")).strip()
        password = str(os.getenv("IMAP_PASSWORD", "")).strip()
        folder = str(os.getenv("IMAP_FOLDER", "INBOX")).strip() or "INBOX"

        if not host or not username or not password:
            self.stdout.write(self.style.ERROR("Missing IMAP config. Set IMAP_HOST, IMAP_USER, IMAP_PASSWORD."))
            return

        since_date = (timezone.now() - timedelta(days=since_days)).strftime("%d-%b-%Y")
        processed = 0
        matched = 0
        updated = 0

        with imaplib.IMAP4_SSL(host, port) as mail:
            mail.login(username, password)
            mail.select(folder)

            typ, data = mail.search(None, "UNSEEN", "SINCE", since_date)
            if typ != "OK":
                self.stdout.write(self.style.ERROR("Could not search IMAP inbox."))
                return
            ids = data[0].split()
            if not ids:
                self.stdout.write("No unseen recent bounce emails found.")
                return
            ids = ids[-limit:]

            for msg_id in ids:
                typ, msg_data = mail.fetch(msg_id, "(RFC822)")
                if typ != "OK" or not msg_data:
                    continue
                processed += 1

                raw = msg_data[0][1] if isinstance(msg_data[0], tuple) and len(msg_data[0]) > 1 else b""
                if not raw:
                    continue
                msg = email.message_from_bytes(raw)
                subject = self._decode_header_value(msg.get("Subject"))
                from_addr = str(msg.get("From") or "")
                body_text = self._extract_text(msg)

                if not self._looks_like_bounce(subject, from_addr, body_text):
                    # Mark read so we do not keep re-checking non-bounce operational mail.
                    mail.store(msg_id, "+FLAGS", "\\Seen")
                    continue

                recipients = self._extract_bounced_recipients(subject, body_text)
                if not recipients:
                    mail.store(msg_id, "+FLAGS", "\\Seen")
                    continue

                for recipient in recipients:
                    rows = self._match_tracking_rows_for_recipient(
                        recipient,
                        user_id=user_id,
                        scheduled_today_only=scheduled_today_only,
                    )
                    if not dry_run:
                        self._mark_employee_mail_failed(recipient, user_id=user_id)
                    if not rows:
                        continue
                    matched += 1
                    for row in rows:
                        if not dry_run:
                            inserted = self._record_bounce(row, recipient, subject)
                            if inserted:
                                self._recompute_delivery_status(row)
                        updated += 1

                mail.store(msg_id, "+FLAGS", "\\Seen")

        # Recompute statuses for eligible rows (today + mailed=true when requested).
        eligible_rows = self._eligible_rows(user_id=user_id, scheduled_today_only=scheduled_today_only)
        recomputed = 0
        if not dry_run:
            for row in eligible_rows:
                self._recompute_delivery_status(row)
                recomputed += 1

        self.stdout.write(
            self.style.SUCCESS(
                f"Done. processed={processed} matched={matched} updated={updated} recomputed={recomputed} dry_run={dry_run}"
            )
        )

    def _decode_header_value(self, value):
        raw = str(value or "")
        parts = decode_header(raw)
        out = []
        for item, enc in parts:
            if isinstance(item, bytes):
                out.append(item.decode(enc or "utf-8", errors="ignore"))
            else:
                out.append(str(item))
        return "".join(out).strip()

    def _extract_text(self, msg):
        chunks = []
        if msg.is_multipart():
            for part in msg.walk():
                ctype = str(part.get_content_type() or "").lower()
                if ctype not in {"text/plain", "message/delivery-status"}:
                    continue
                payload = part.get_payload(decode=True)
                if not payload:
                    continue
                charset = part.get_content_charset() or "utf-8"
                chunks.append(payload.decode(charset, errors="ignore"))
        else:
            payload = msg.get_payload(decode=True)
            if payload:
                charset = msg.get_content_charset() or "utf-8"
                chunks.append(payload.decode(charset, errors="ignore"))
        return "\n".join(chunks)

    def _looks_like_bounce(self, subject, from_addr, body_text):
        src = f"{subject}\n{from_addr}\n{body_text}".lower()
        bounce_markers = [
            "delivery status notification",
            "mail delivery failed",
            "delivery has failed",
            "undeliverable",
            "failure notice",
            "returned mail",
            "couldn't be delivered",
            "address not found",
            "mailer-daemon",
            "postmaster",
            "final-recipient:",
            "status: 5.",
        ]
        return any(marker in src for marker in bounce_markers)

    def _extract_bounced_recipients(self, subject, body_text):
        text = f"{subject}\n{body_text}"
        recipients = set()

        for match in re.finditer(r"Final-Recipient:\s*rfc822;\s*([^\s;]+)", text, flags=re.I):
            recipients.add(str(match.group(1) or "").strip().lower())
        for match in re.finditer(r"Original-Recipient:\s*rfc822;\s*([^\s;]+)", text, flags=re.I):
            recipients.add(str(match.group(1) or "").strip().lower())

        if not recipients:
            for match in re.finditer(r"\b[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}\b", text):
                recipients.add(str(match.group(0) or "").strip().lower())

        # Ignore obvious sender system addresses.
        blocked = {"mailer-daemon", "postmaster"}
        cleaned = {
            r for r in recipients
            if r and not any(key in r for key in blocked)
        }
        return sorted(cleaned)

    def _match_tracking_rows_for_recipient(self, recipient, user_id=None, scheduled_today_only=False):
        candidate_events = (
            MailTrackingEvent.objects
            .select_related("tracking", "mail_tracking")
            .order_by("-created_at")[:3000]
        )
        rows = []
        seen_ids = set()
        today_local = timezone.localdate()
        for event in candidate_events:
            payload = event.raw_payload if isinstance(event.raw_payload, dict) else {}
            to_email = str(payload.get("to_email") or "").strip().lower()
            if to_email != recipient:
                continue
            tracking = event.tracking
            if tracking is None and event.mail_tracking and event.mail_tracking.tracking_rows.exists():
                tracking = event.mail_tracking.tracking_rows.order_by("-created_at").first()
            if tracking is None:
                continue
            if user_id and tracking.user_id != int(user_id):
                continue
            if bool(getattr(tracking, "is_freezed", False)):
                continue
            if not bool(getattr(tracking, "mailed", False)):
                continue
            if scheduled_today_only:
                st = getattr(tracking, "schedule_time", None)
                if not st:
                    continue
                try:
                    if timezone.localtime(st).date() != today_local:
                        continue
                except Exception:  # noqa: BLE001
                    continue
            if tracking.id not in seen_ids:
                seen_ids.add(tracking.id)
                rows.append(tracking)
        return rows

    def _record_bounce(self, tracking, recipient, subject):
        mail_tracking = tracking.mail_tracking
        if not mail_tracking:
            return False

        # De-duplicate bounce event for same recipient+subject.
        recent = (
            MailTrackingEvent.objects
            .filter(mail_tracking=mail_tracking, notes="Bounce detected from IMAP inbox.")
            .order_by("-created_at")[:80]
        )
        for item in recent:
            payload = item.raw_payload if isinstance(item.raw_payload, dict) else {}
            p_to = str(payload.get("to_email") or "").strip().lower()
            p_subject = str(payload.get("subject") or "").strip()
            p_status = str(payload.get("status") or "").strip().lower()
            if p_to == str(recipient or "").strip().lower() and p_subject == str(subject or "").strip() and p_status == "bounced":
                return False

        now = timezone.now()
        history = mail_tracking.mail_history if isinstance(mail_tracking.mail_history, list) else []
        history.append(
            {
                "status": "failed",
                "to_email": recipient,
                "subject": subject,
                "body": "",
                "employee_id": None,
                "employee_name": "",
                "notes": "Bounce detected from IMAP inbox.",
                "at": now.isoformat(),
            }
        )
        mail_tracking.mail_history = history[-300:]
        mail_tracking.save(update_fields=["mail_history", "updated_at"])

        MailTrackingEvent.objects.create(
            mail_tracking=mail_tracking,
            tracking=tracking,
            employee=None,
            mail_type="followup" if str(tracking.mail_type or "").strip().lower() == "followed_up" else "fresh",
            send_mode="sent",
            action_at=now,
            got_replied=False,
            notes="Bounce detected from IMAP inbox.",
            raw_payload={
                "to_email": recipient,
                "subject": subject,
                "body": "",
                "status": "bounced",
            },
        )
        return True

    def _eligible_rows(self, user_id=None, scheduled_today_only=False):
        qs = Tracking.objects.filter(mailed=True, is_removed=False, is_freezed=False).select_related("mail_tracking")
        if user_id:
            qs = qs.filter(user_id=int(user_id))
        if scheduled_today_only:
            qs = qs.filter(schedule_time__date=timezone.localdate())
        return list(qs[:5000])

    def _mark_employee_mail_failed(self, recipient, user_id=None):
        qs = Employee.objects.filter(email__iexact=str(recipient or "").strip())
        if user_id:
            qs = qs.filter(user_id=int(user_id))
        qs = qs.exclude(working_mail=False)
        if qs.exists():
            qs.update(working_mail=False)

    def _recompute_delivery_status(self, tracking):
        mail_tracking = tracking.mail_tracking
        if not mail_tracking:
            tracking.mail_delivery_status = "pending"
            tracking.save(update_fields=["mail_delivery_status", "updated_at"])
            return

        history = mail_tracking.mail_history if isinstance(mail_tracking.mail_history, list) else []
        latest_by_email = {}
        for row in history:
            if not isinstance(row, dict):
                continue
            to_email = str(row.get("to_email") or "").strip().lower()
            status = str(row.get("status") or "").strip().lower()
            if not to_email:
                continue
            if status in {"sent", "failed", "bounced"}:
                latest_by_email[to_email] = status

        sent_count = sum(1 for value in latest_by_email.values() if value == "sent")
        failed_count = sum(1 for value in latest_by_email.values() if value in {"failed", "bounced"})

        if sent_count > 0 and failed_count > 0:
            tracking.mail_delivery_status = "partially_sent"
        elif sent_count > 0:
            tracking.mail_delivery_status = "sent"
        elif failed_count > 0:
            tracking.mail_delivery_status = "failed"
        else:
            tracking.mail_delivery_status = "pending"

        tracking.mailed = sent_count > 0
        tracking.save(update_fields=["mail_delivery_status", "mailed", "updated_at"])
