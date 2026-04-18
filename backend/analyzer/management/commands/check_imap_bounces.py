import email
import imaplib
import logging
import re
from datetime import timedelta
from email.header import decode_header
from email.utils import parseaddr, parsedate_to_datetime
from logging.handlers import TimedRotatingFileHandler
from pathlib import Path

from django.contrib.auth.models import User
from django.core.management.base import BaseCommand
from django.db.models import Q
from django.utils import timezone

from analyzer.models import Employee, MailTracking, MailTrackingEvent, Tracking
from analyzer.profile_settings import resolve_imap_settings
from analyzer.tracking_mail_utils import log_mail_event, recompute_tracking_delivery_status


LOGGER_NAME = "analyzer.check_imap_bounces"


class Command(BaseCommand):
    help = "Scan IMAP inbox for bounce emails and update tracking delivery status."

    def _get_logger(self):
        logger = logging.getLogger(LOGGER_NAME)
        if logger.handlers:
            return logger

        log_dir = Path(__file__).resolve().parents[4] / "log"
        log_dir.mkdir(parents=True, exist_ok=True)
        log_path = log_dir / "check_imap_bounces.log"

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

    def add_arguments(self, parser):
        parser.add_argument("--user-id", type=int, default=None, help="Process bounce mapping only for this user id")
        parser.add_argument("--limit", type=int, default=100, help="Max IMAP messages to process")
        parser.add_argument("--since-days", type=int, default=14, help="Search recent emails in last N days")
        parser.add_argument("--scheduled-today-only", action="store_true", help="Only update rows scheduled for today (local timezone) with mailed=true")
        parser.add_argument("--dry-run", action="store_true", help="Do not write DB changes")
        parser.add_argument("--unseen-only", action="store_true", help="Only scan unread IMAP messages instead of all recent messages")

    def handle(self, *args, **options):
        user_id = options.get("user_id")
        limit = int(options.get("limit") or 100)
        since_days = int(options.get("since_days") or 14)
        scheduled_today_only = bool(options.get("scheduled_today_only"))
        dry_run = bool(options.get("dry_run"))
        unseen_only = bool(options.get("unseen_only"))

        imap_user = User.objects.filter(id=user_id).first() if user_id else None
        imap_settings = resolve_imap_settings(imap_user)
        host = str(imap_settings.get("host", "") or "").strip()
        port = int(imap_settings.get("port", 993) or 993)
        username = str(imap_settings.get("username", "") or "").strip()
        password = str(imap_settings.get("password", "") or "").strip()
        folder = str(imap_settings.get("folder", "INBOX") or "").strip() or "INBOX"

        if not host or not username or not password:
            self._emit("Missing IMAP config. Set IMAP_HOST, IMAP_USER, IMAP_PASSWORD.", level="error", style=self.style.ERROR)
            return

        since_date = (timezone.now() - timedelta(days=since_days)).strftime("%d-%b-%Y")
        processed = 0
        matched = 0
        updated = 0
        self._emit(
            f"Starting IMAP scan folder={folder} host={host} since_days={since_days} limit={limit} unseen_only={unseen_only} dry_run={dry_run}"
        )
        with imaplib.IMAP4_SSL(host, port) as mail:
            mail.login(username, password)
            mail.select(folder)

            search_terms = ["SINCE", since_date]
            if unseen_only:
                search_terms.insert(0, "UNSEEN")
            typ, data = mail.search(None, *search_terms)
            if typ != "OK":
                self._emit("Could not search IMAP inbox.", level="error", style=self.style.ERROR)
                return
            ids = data[0].split()
            if not ids:
                self._emit("No recent IMAP messages found for the current search.")
                return
            ids = ids[-limit:]
            candidate_events = self._candidate_events(
                since_days=since_days,
                user_id=user_id,
                scheduled_today_only=scheduled_today_only,
            )
            self._emit(f"Loaded candidate sent events: {len(candidate_events)}")

            for msg_id in ids:
                imap_uid = self._fetch_uid(mail, msg_id)
                typ, msg_data = mail.fetch(msg_id, "(RFC822)")
                if typ != "OK" or not msg_data:
                    self._emit(f"Skipping IMAP message id={msg_id!r}: fetch failed", level="warning")
                    continue

                raw = msg_data[0][1] if isinstance(msg_data[0], tuple) and len(msg_data[0]) > 1 else b""
                if not raw:
                    self._emit(f"Skipping IMAP message id={msg_id!r}: empty RFC822 payload", level="warning")
                    continue
                msg = email.message_from_bytes(raw)
                subject = self._decode_header_value(msg.get("Subject"))
                from_addr = str(msg.get("From") or "")
                body_text = self._extract_text(msg)
                message_id = str(msg.get("Message-ID") or "").strip()
                thread_message_ids = self._thread_message_ids(msg)
                message_at = self._message_datetime(msg)
                sender_email = self._extract_sender_email(from_addr)
                recipients = self._extract_bounced_recipients(subject, body_text) if self._looks_like_bounce(subject, from_addr, body_text) else []

                if not self._message_relates_to_tracking(
                    candidate_events,
                    sender_email=sender_email,
                    thread_message_ids=thread_message_ids,
                    bounce_recipients=recipients,
                ):
                    self._emit(
                        f"Skipped unrelated inbox mail uid={imap_uid or msg_id!r} from={sender_email or from_addr} subject={subject!r} thread_ids={thread_message_ids}",
                        level="info",
                    )
                    continue

                processed += 1
                self._emit(
                    f"Processing related mail uid={imap_uid or msg_id!r} from={sender_email or from_addr} subject={subject!r} bounce={bool(recipients)} thread_ids={thread_message_ids}"
                )

                if not self._looks_like_bounce(subject, from_addr, body_text):
                    thread_rows = self._match_tracking_rows_for_thread(
                        thread_message_ids,
                        user_id=user_id,
                        since_days=since_days,
                        scheduled_today_only=scheduled_today_only,
                    )
                    if not dry_run:
                        inserted = self._record_reply_if_applicable(
                            subject=subject,
                            from_addr=from_addr,
                            body_text=body_text,
                            source_uid=imap_uid,
                            source_message_id=message_id,
                            thread_message_ids=thread_message_ids,
                            action_at=message_at,
                            user_id=user_id,
                            since_days=since_days,
                            scheduled_today_only=scheduled_today_only,
                        )
                        if inserted:
                            matched += inserted
                            updated += inserted
                            self._emit(f"Recorded reply events={inserted} for uid={imap_uid or msg_id!r}")
                        else:
                            reason = self._reply_skip_reason(
                                sender_email,
                                candidate_events,
                                thread_rows=thread_rows,
                            )
                            self._emit(
                                f"No tracking row matched reply uid={imap_uid or msg_id!r} from={sender_email or from_addr} subject={subject!r} reason={reason}",
                                level="warning",
                            )
                    mail.store(msg_id, "+FLAGS", "\\Seen")
                    continue

                if not recipients:
                    self._emit(
                        f"Bounce-like message uid={imap_uid or msg_id!r} had no extracted recipients; skipped",
                        level="warning",
                    )
                    mail.store(msg_id, "+FLAGS", "\\Seen")
                    continue

                for recipient in recipients:
                    rows = self._match_tracking_rows_for_recipient(
                        recipient,
                        user_id=user_id,
                        since_days=since_days,
                        scheduled_today_only=scheduled_today_only,
                    )
                    if not dry_run:
                        self._mark_employee_mail_failed(recipient, user_id=user_id)
                    if not rows:
                        self._emit(
                            f"No tracking rows matched bounce recipient={recipient} uid={imap_uid or msg_id!r} subject={subject!r}",
                            level="warning",
                        )
                        continue
                    matched += len(rows)
                    for row in rows:
                        if not dry_run:
                            inserted = self._record_bounce(
                                row,
                                recipient,
                                subject,
                                body_text,
                                source_uid=imap_uid,
                                source_message_id=message_id,
                                action_at=message_at,
                            )
                            if inserted:
                                self._recompute_delivery_status(row)
                                updated += 1
                                self._emit(
                                    f"Recorded bounce for tracking={row.id} recipient={recipient} uid={imap_uid or msg_id!r}"
                                )
                            else:
                                self._emit(
                                    f"Skipped duplicate bounce for tracking={row.id} recipient={recipient} uid={imap_uid or msg_id!r}",
                                    level="info",
                                )

                mail.store(msg_id, "+FLAGS", "\\Seen")

        # Recompute statuses for eligible rows (today + mailed=true when requested).
        eligible_rows = self._eligible_rows(user_id=user_id, scheduled_today_only=scheduled_today_only)
        recomputed = 0
        if not dry_run:
            for row in eligible_rows:
                self._recompute_delivery_status(row)
                recomputed += 1

        self._emit(
            f"Done. processed={processed} matched={matched} updated={updated} recomputed={recomputed} dry_run={dry_run}",
            style=self.style.SUCCESS,
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

    def _fetch_uid(self, mail, msg_id):
        try:
            typ, data = mail.fetch(msg_id, "(UID)")
        except Exception:
            return ""
        if typ != "OK" or not data:
            return ""
        for item in data:
            if isinstance(item, tuple):
                text = item[0].decode(errors="ignore")
            else:
                text = str(item or "")
            match = re.search(r"UID\s+(\d+)", text, flags=re.I)
            if match:
                return str(match.group(1) or "").strip()
        return ""

    def _message_datetime(self, msg):
        raw = str(msg.get("Date") or "").strip()
        if not raw:
            return timezone.now()
        try:
            dt = parsedate_to_datetime(raw)
            if dt is None:
                return timezone.now()
            if timezone.is_naive(dt):
                dt = timezone.make_aware(dt, timezone.get_current_timezone())
            return dt
        except Exception:
            return timezone.now()

    def _already_processed_message(self, mail_tracking, *, source_uid="", source_message_id=""):
        if not mail_tracking:
            return False
        uid = str(source_uid or "").strip()
        message_id = str(source_message_id or "").strip()
        if uid and MailTrackingEvent.objects.filter(mail_tracking=mail_tracking, source_uid=uid).exists():
            return True
        if message_id and MailTrackingEvent.objects.filter(mail_tracking=mail_tracking, source_message_id=message_id).exists():
            return True
        return False

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

    def _extract_sender_email(self, from_addr):
        _, addr = parseaddr(str(from_addr or "").strip())
        return str(addr or "").strip().lower()

    def _thread_message_ids(self, msg):
        values = []
        for key in ("In-Reply-To", "References"):
            raw = str(msg.get(key) or "").strip()
            if raw:
                values.extend(re.findall(r"<[^>]+>", raw))
        cleaned = []
        seen = set()
        for item in values:
            normalized = str(item or "").strip()
            if not normalized:
                continue
            key = normalized.lower()
            if key in seen:
                continue
            seen.add(key)
            cleaned.append(normalized)
        return cleaned

    def _recent_tracking_ids(self, since_days=14, user_id=None, scheduled_today_only=False):
        since_at = timezone.now() - timedelta(days=int(since_days or 14))
        today_local = timezone.localdate()
        sent_events = (
            MailTrackingEvent.objects
            .filter(
                tracking_id__isnull=False,
                tracking__is_freezed=False,
                status="sent",
                action_at__gte=since_at,
            )
            .select_related("tracking")
        )
        if user_id:
            sent_events = sent_events.filter(tracking__user_id=int(user_id))
        if scheduled_today_only:
            sent_events = sent_events.filter(tracking__schedule_time__date=today_local)
        tracking_ids = set(sent_events.values_list("tracking_id", flat=True))
        if tracking_ids:
            return tracking_ids

        qs = MailTracking.objects.filter(
            tracking_id__isnull=False,
            tracking__is_freezed=False,
            created_at__gte=since_at,
        )
        if user_id:
            qs = qs.filter(tracking__user_id=int(user_id))
        if scheduled_today_only:
            qs = qs.filter(tracking__schedule_time__date=today_local)
        return set(qs.values_list("tracking_id", flat=True))

    def _candidate_events(self, since_days=14, user_id=None, scheduled_today_only=False):
        tracking_ids = self._recent_tracking_ids(
            since_days=since_days,
            user_id=user_id,
            scheduled_today_only=scheduled_today_only,
        )
        if not tracking_ids:
            return []
        return list(
            MailTrackingEvent.objects
            .select_related("tracking", "mail_tracking", "employee")
            .filter(
                Q(tracking_id__in=tracking_ids) | Q(mail_tracking__tracking_id__in=tracking_ids)
            )
            .order_by("-action_at", "-created_at")[:3000]
        )

    def _message_relates_to_tracking(self, candidate_events, *, sender_email="", thread_message_ids=None, bounce_recipients=None):
        if not candidate_events:
            return False
        normalized_sender = str(sender_email or "").strip().lower()
        normalized_thread_ids = {
            str(item or "").strip().lower()
            for item in (thread_message_ids or [])
            if str(item or "").strip()
        }
        normalized_bounce_recipients = {
            str(item or "").strip().lower()
            for item in (bounce_recipients or [])
            if str(item or "").strip()
        }
        for event in candidate_events:
            payload = event.raw_payload if isinstance(event.raw_payload, dict) else {}
            to_email = str(payload.get("to_email") or "").strip().lower()
            if normalized_sender and to_email == normalized_sender:
                return True
            if normalized_bounce_recipients and to_email in normalized_bounce_recipients:
                return True
            if normalized_thread_ids:
                event_message_ids = {
                    str(value or "").strip().lower()
                    for value in [
                        payload.get("message_id"),
                        payload.get("in_reply_to"),
                        event.source_message_id,
                    ]
                    if str(value or "").strip()
                }
                for ref in payload.get("references") or []:
                    text = str(ref or "").strip().lower()
                    if text:
                        event_message_ids.add(text)
                if event_message_ids & normalized_thread_ids:
                    return True
        return False

    def _match_tracking_rows_for_recipient(self, recipient, user_id=None, since_days=14, scheduled_today_only=False):
        candidate_events = self._candidate_events(
            since_days=since_days,
            user_id=user_id,
            scheduled_today_only=scheduled_today_only,
        )
        if not candidate_events:
            return []
        rows = []
        seen_ids = set()
        today_local = timezone.localdate()
        for event in candidate_events:
            payload = event.raw_payload if isinstance(event.raw_payload, dict) else {}
            to_email = str(payload.get("to_email") or "").strip().lower()
            if to_email != recipient:
                continue
            tracking = event.tracking
            if tracking is None and event.mail_tracking and getattr(event.mail_tracking, "tracking_id", None):
                tracking = event.mail_tracking.tracking
            if tracking is None:
                continue
            if user_id and tracking.user_id != int(user_id):
                continue
            if bool(getattr(tracking, "is_freezed", False)):
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

    def _reply_skip_reason(self, sender_email, candidate_events, *, thread_rows=None):
        normalized_sender = str(sender_email or "").strip().lower()
        if not normalized_sender:
            return "missing sender email"

        owner_like_emails = set()
        tracked_recipient_emails = set()
        for event in candidate_events or []:
            payload = event.raw_payload if isinstance(event.raw_payload, dict) else {}
            to_email = str(payload.get("to_email") or "").strip().lower()
            from_email = str(payload.get("from_email") or "").strip().lower()
            if to_email:
                tracked_recipient_emails.add(to_email)
            if from_email:
                owner_like_emails.add(from_email)
            tracking = event.tracking
            if tracking is None and event.mail_tracking and getattr(event.mail_tracking, "tracking_id", None):
                tracking = event.mail_tracking.tracking
            if tracking and getattr(tracking, "user", None):
                user_email = str(getattr(tracking.user, "email", "") or "").strip().lower()
                if user_email:
                    owner_like_emails.add(user_email)

        if normalized_sender in owner_like_emails:
            return "sender is mailbox owner/sent-mail copy"
        if tracked_recipient_emails and normalized_sender not in tracked_recipient_emails:
            if thread_rows:
                return f"thread matched but sender {normalized_sender} is not the tracked recipient"
            return f"sender {normalized_sender} is not among tracked recipients"
        return "thread matched, but no eligible tracking row was resolved"

    def _match_tracking_rows_for_thread(self, thread_message_ids, user_id=None, since_days=14, scheduled_today_only=False):
        normalized_ids = {str(item or "").strip().lower() for item in (thread_message_ids or []) if str(item or "").strip()}
        if not normalized_ids:
            return []
        candidate_events = self._candidate_events(
            since_days=since_days,
            user_id=user_id,
            scheduled_today_only=scheduled_today_only,
        )
        rows = []
        seen_ids = set()
        today_local = timezone.localdate()
        for event in candidate_events:
            payload = event.raw_payload if isinstance(event.raw_payload, dict) else {}
            event_message_ids = {
                str(value or "").strip().lower()
                for value in [
                    payload.get("message_id"),
                    payload.get("in_reply_to"),
                    event.source_message_id,
                ]
                if str(value or "").strip()
            }
            for ref in payload.get("references") or []:
                text = str(ref or "").strip().lower()
                if text:
                    event_message_ids.add(text)
            if not (normalized_ids & event_message_ids):
                continue
            tracking = event.tracking
            if tracking is None and event.mail_tracking and getattr(event.mail_tracking, "tracking_id", None):
                tracking = event.mail_tracking.tracking
            if tracking is None:
                continue
            if user_id and tracking.user_id != int(user_id):
                continue
            if bool(getattr(tracking, "is_freezed", False)):
                continue
            if scheduled_today_only:
                st = getattr(tracking, "schedule_time", None)
                if not st:
                    continue
                try:
                    if timezone.localtime(st).date() != today_local:
                        continue
                except Exception:
                    continue
            if tracking.id not in seen_ids:
                seen_ids.add(tracking.id)
                rows.append(tracking)
        return rows

    def _record_reply_if_applicable(self, subject, from_addr, body_text, source_uid="", source_message_id="", thread_message_ids=None, action_at=None, user_id=None, since_days=14, scheduled_today_only=False):
        sender_email = self._extract_sender_email(from_addr)
        rows = self._match_tracking_rows_for_thread(
            thread_message_ids or [],
            user_id=user_id,
            since_days=since_days,
            scheduled_today_only=scheduled_today_only,
        )
        if not rows:
            return 0
        inserted = 0
        for tracking in rows:
            if self._record_reply(
                tracking,
                sender_email,
                subject,
                body_text,
                source_uid=source_uid,
                source_message_id=source_message_id,
                thread_message_ids=thread_message_ids,
                action_at=action_at,
            ):
                self._recompute_delivery_status(tracking)
                inserted += 1
        return inserted

    def _extract_bounce_reason(self, subject, body_text):
        text = str(body_text or "").strip()
        subject_text = str(subject or "").strip()
        patterns = [
            r"Diagnostic-Code:\s*[^;]+;\s*(.+)",
            r"Status:\s*([45]\.\d+\.\d+.*)",
            r"Reason:\s*(.+)",
            r"Action:\s*(failed.*)",
            r"This is .*?:\s*(.+)",
        ]
        for pattern in patterns:
            match = re.search(pattern, text, flags=re.I)
            if match:
                value = re.sub(r"\s+", " ", str(match.group(1) or "").strip(" .;:-"))
                if value:
                    return value[:240]

        for line in text.splitlines():
            normalized = re.sub(r"\s+", " ", str(line or "").strip())
            lower = normalized.lower()
            if not normalized:
                continue
            if any(marker in lower for marker in ["user unknown", "address not found", "mailbox unavailable", "recipient address rejected", "undeliverable", "no such user", "delivery has failed"]):
                return normalized[:240]

        if subject_text:
            return subject_text[:240]
        return "Bounce detected from IMAP inbox."

    def _record_bounce(self, tracking, recipient, subject, body_text, source_uid="", source_message_id="", action_at=None):
        mail_tracking = getattr(tracking, "mail_tracking_record", None)
        if not mail_tracking:
            return False
        if self._already_processed_message(mail_tracking, source_uid=source_uid, source_message_id=source_message_id):
            return False

        # De-duplicate bounce event for same recipient+subject.
        recent = (
            MailTrackingEvent.objects
            .filter(mail_tracking=mail_tracking, status="bounced")
            .order_by("-created_at")[:80]
        )
        for item in recent:
            payload = item.raw_payload if isinstance(item.raw_payload, dict) else {}
            p_to = str(payload.get("to_email") or "").strip().lower()
            p_subject = str(payload.get("subject") or "").strip()
            p_status = str(payload.get("status") or "").strip().lower()
            if p_to == str(recipient or "").strip().lower() and p_subject == str(subject or "").strip() and p_status == "bounced":
                return False

        latest_event = (
            MailTrackingEvent.objects
            .filter(mail_tracking=mail_tracking)
            .order_by('-action_at', '-created_at')
            .only('id', 'employee_id', 'mail_type', 'send_mode', 'status', 'raw_payload')
        )
        matched_event = None
        normalized_recipient = str(recipient or "").strip().lower()
        for item in latest_event[:120]:
            payload = item.raw_payload if isinstance(item.raw_payload, dict) else {}
            item_to = str(payload.get("to_email") or "").strip().lower()
            item_status = str(item.status or payload.get("status") or "").strip().lower()
            if item_to == normalized_recipient and item_status in {"sent", "failed"}:
                matched_event = item
                break

        employee = matched_event.employee if matched_event and matched_event.employee_id else None
        mail_type = str(matched_event.mail_type or "").strip() if matched_event else ""
        send_mode = str(matched_event.send_mode or "").strip() if matched_event else ""
        bounce_reason = self._extract_bounce_reason(subject, body_text)

        event, _ = log_mail_event(
            mail_tracking=mail_tracking,
            tracking=tracking,
            employee=employee,
            status="bounced",
            notes=f"Bounce detected: {bounce_reason}",
            subject=subject,
            body="",
            to_email=recipient,
            action_at=action_at,
            source_uid=source_uid,
            source_message_id=source_message_id,
            raw_payload={
                "to_email": recipient,
                "subject": subject,
                "body": "",
                "status": "bounced",
                "reason": bounce_reason,
            },
            mail_type=mail_type or ("followup" if str(tracking.mail_type or "").strip().lower() == "followed_up" else "fresh"),
            send_mode=send_mode or "sent",
        )
        return True

    def _record_reply(self, tracking, sender_email, subject, body_text, source_uid="", source_message_id="", thread_message_ids=None, action_at=None):
        mail_tracking = getattr(tracking, "mail_tracking_record", None)
        if not mail_tracking:
            return False
        if self._already_processed_message(mail_tracking, source_uid=source_uid, source_message_id=source_message_id):
            return False

        normalized_email = str(sender_email or "").strip().lower()
        normalized_subject = str(subject or "").strip()

        latest_event = (
            MailTrackingEvent.objects
            .filter(mail_tracking=mail_tracking)
            .select_related("employee")
            .order_by("-action_at", "-created_at")
        )
        matched_event = None
        for item in latest_event[:120]:
            payload = item.raw_payload if isinstance(item.raw_payload, dict) else {}
            item_to = str(payload.get("to_email") or "").strip().lower()
            if item_to == normalized_email:
                matched_event = item
                break

        employee = matched_event.employee if matched_event and matched_event.employee_id else getattr(mail_tracking, "employee", None)
        status_value = str(matched_event.status or "sent").strip() if matched_event else "sent"
        if status_value not in {"pending", "sent", "failed", "bounced"}:
            status_value = "sent"
        log_mail_event(
            mail_tracking=mail_tracking,
            tracking=tracking,
            employee=employee,
            status=status_value,
            notes="Reply detected from IMAP inbox.",
            subject=normalized_subject,
            body=str(body_text or "").strip(),
            to_email=normalized_email,
            from_email=normalized_email,
            got_replied=True,
            action_at=action_at,
            source_uid=source_uid,
            source_message_id=source_message_id,
            raw_payload={
                "from_email": normalized_email,
                "subject": normalized_subject,
                "body": str(body_text or "").strip(),
                "status": "replied",
                "message_id": str(source_message_id or "").strip(),
                "thread_message_ids": [
                    str(item or "").strip()
                    for item in (thread_message_ids or [])
                    if str(item or "").strip()
                ],
            },
            mail_type=str(matched_event.mail_type or "").strip() if matched_event else ("followup" if str(tracking.mail_type or "").strip().lower() == "followed_up" else "fresh"),
            send_mode=str(matched_event.send_mode or "").strip() if matched_event else ("scheduled" if tracking and tracking.schedule_time else "sent"),
        )
        return True

    def _eligible_rows(self, user_id=None, scheduled_today_only=False):
        since_at = timezone.now() - timedelta(days=14)
        today_local = timezone.localdate()
        recent_sent_tracking_ids = set(
            MailTrackingEvent.objects
            .filter(
                tracking_id__isnull=False,
                status="sent",
                action_at__gte=since_at,
            )
            .values_list("tracking_id", flat=True)
        )
        qs = Tracking.objects.filter(is_freezed=False).select_related("mail_tracking_record", "resume", "job__company")
        if recent_sent_tracking_ids:
            qs = qs.filter(id__in=recent_sent_tracking_ids)
        else:
            qs = qs.filter(mail_tracking_record__created_at__gte=since_at)
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
        recompute_tracking_delivery_status(tracking, mark_successful=True)
