from uuid import uuid4

from django.utils import timezone

from analyzer.models import MailTracking, MailTrackingEvent


def map_tracking_mail_type(tracking):
    raw = str(getattr(tracking, "mail_type", "") or "fresh").strip().lower()
    return "followup" if raw == "followed_up" else "fresh"


def resolve_tracking_send_mode(tracking):
    return "scheduled" if tracking and getattr(tracking, "schedule_time", None) else "sent"


def ensure_mail_tracking(tracking):
    mail_tracking = getattr(tracking, "mail_tracking_record", None)
    if mail_tracking:
        update_fields = []
        if getattr(mail_tracking, "tracking_id", None) != tracking.id:
            mail_tracking.tracking = tracking
            update_fields.append("tracking")
        if getattr(mail_tracking, "resume_id", None) != getattr(tracking, "resume_id", None):
            mail_tracking.resume_id = getattr(tracking, "resume_id", None)
            update_fields.append("resume")
        if update_fields:
            update_fields.append("updated_at")
            mail_tracking.save(update_fields=update_fields)
        return mail_tracking
    return MailTracking.objects.create(profile=tracking.profile, tracking=tracking, resume=tracking.resume)


def build_history_entry(
    tracking,
    employee,
    *,
    mail_tracking,
    status,
    to_email="",
    from_email="",
    subject="",
    body="",
    notes="",
    mail_type=None,
    send_mode=None,
    at=None,
):
    job = tracking.job if tracking else None
    company = job.company if tracking and tracking.job_id and job and job.company_id else None
    timestamp = at or timezone.now()
    return {
        "history_id": str(uuid4()),
        "tracking_id": tracking.id if tracking else None,
        "mail_tracking_id": mail_tracking.id if mail_tracking else None,
        "status": str(status or "").strip().lower(),
        "to_email": str(to_email or "").strip(),
        "from_email": str(from_email or "").strip(),
        "subject": str(subject or "").strip(),
        "body": str(body or ""),
        "notes": str(notes or "").strip(),
        "employee_id": employee.id if employee else None,
        "employee_name": str(employee.name or "").strip() if employee else "",
        "company_id": company.id if company else None,
        "company_name": str(company.name or "").strip() if company else "",
        "job_ref_id": job.id if job else None,
        "job_id": str(job.job_id or "").strip() if job else "",
        "job_role": str(job.role or "").strip() if job else "",
        "resume_id": tracking.resume_id if tracking else None,
        "resume_type": "tailored" if tracking and tracking.resume_id and tracking.resume and bool(getattr(tracking.resume, "is_tailored", False)) else "base",
        "mail_type": str(mail_type or map_tracking_mail_type(tracking)),
        "send_mode": str(send_mode or resolve_tracking_send_mode(tracking)),
        "at": timestamp.isoformat(),
    }


def _save_mail_tracking(mail_tracking, *, history=None, employee=None, resume=None, history_limit=300):
    update_fields = []
    if history is not None:
        mail_tracking.mail_history = history[-history_limit:]
        update_fields.append("mail_history")
    if employee is not None and getattr(mail_tracking, "employee_id", None) != getattr(employee, "id", None):
        mail_tracking.employee = employee
        update_fields.append("employee")
    if resume is not None or getattr(mail_tracking, "resume_id", None) is not None:
        next_resume_id = getattr(resume, "id", None)
        if getattr(mail_tracking, "resume_id", None) != next_resume_id:
            mail_tracking.resume = resume
            update_fields.append("resume")
    if update_fields:
        update_fields.append("updated_at")
        mail_tracking.save(update_fields=update_fields)


def log_mail_event(
    *,
    mail_tracking,
    tracking,
    employee,
    status,
    notes,
    subject="",
    body="",
    to_email="",
    from_email="",
    got_replied=False,
    raw_payload=None,
    history_limit=300,
    action_at=None,
    mail_type=None,
    send_mode=None,
    source_uid='',
    source_message_id='',
):
    event_time = action_at or timezone.now()
    entry = build_history_entry(
        tracking,
        employee,
        mail_tracking=mail_tracking,
        status=status,
        to_email=to_email,
        from_email=from_email,
        subject=subject,
        body=body,
        notes=notes,
        mail_type=mail_type,
        send_mode=send_mode,
        at=event_time,
    )
    history = mail_tracking.mail_history if isinstance(mail_tracking.mail_history, list) else []
    history.append(entry)
    _save_mail_tracking(
        mail_tracking,
        history=history,
        employee=employee if employee else None,
        resume=tracking.resume if tracking else None,
        history_limit=history_limit,
    )

    normalized_status = str(status or "").strip().lower()
    if normalized_status not in {"pending", "sent", "failed", "bounced"}:
        normalized_status = "pending"
    payload = dict(raw_payload or {})
    if "status" not in payload:
        payload["status"] = normalized_status
    event = MailTrackingEvent.objects.create(
        mail_tracking=mail_tracking,
        tracking=tracking,
        employee=employee,
        mail_type=str(mail_type or map_tracking_mail_type(tracking)),
        send_mode=str(send_mode or resolve_tracking_send_mode(tracking)),
        status=normalized_status,
        action_at=event_time,
        notes=str(notes or "").strip(),
        source_uid=str(source_uid or '').strip(),
        source_message_id=str(source_message_id or '').strip(),
        raw_payload=payload,
    )
    history[-1]["event_id"] = event.id
    _save_mail_tracking(mail_tracking, history=history, history_limit=history_limit)
    return event, history[-1]


def build_mail_tracking_status_map(mail_tracking):
    if not mail_tracking:
        return {}

    latest_by_key = {}
    event_rows = (
        MailTrackingEvent.objects
        .filter(mail_tracking=mail_tracking)
        .select_related("employee")
        .order_by("action_at", "created_at")
    )
    for item in event_rows:
        payload = item.raw_payload if isinstance(item.raw_payload, dict) else {}
        to_email = str(payload.get("to_email") or payload.get("recipient_email") or payload.get("receiver") or "").strip()
        status = str(item.status or payload.get("status") or "").strip().lower()
        if status not in {"pending", "sent", "failed", "bounced"}:
            continue
        reason = str(
            payload.get("reason")
            or payload.get("failure_reason")
            or payload.get("bounce_reason")
            or item.notes
            or ""
        ).strip()
        entry = {
            "employee_id": item.employee_id,
            "employee_name": str(item.employee.name or "").strip() if item.employee_id and item.employee else "",
            "email": to_email,
            "status": status,
            "reason": reason,
            "action_at": item.action_at.isoformat() if item.action_at else "",
        }
        if item.employee_id:
            latest_by_key[f"employee:{item.employee_id}"] = entry
        if to_email:
            latest_by_key[f"email:{to_email.lower()}"] = entry
    return latest_by_key


def recompute_tracking_delivery_status(tracking):
    mail_tracking = getattr(tracking, "mail_tracking_record", None)
    if not mail_tracking:
        tracking.mail_delivery_status = "pending"
        tracking.mailed = False
        tracking.save(update_fields=["mail_delivery_status", "mailed", "updated_at"])
        return tracking.mail_delivery_status

    latest_by_email = {}
    status_map = build_mail_tracking_status_map(mail_tracking)
    for key, value in status_map.items():
        if not key.startswith("email:"):
            continue
        to_email = str(value.get("email") or "").strip().lower()
        status = str(value.get("status") or "").strip().lower()
        if to_email and status in {"sent", "failed", "bounced"}:
            latest_by_email[to_email] = status

    if not latest_by_email:
        history = mail_tracking.mail_history if isinstance(mail_tracking.mail_history, list) else []
        for row in history:
            if not isinstance(row, dict):
                continue
            to_email = str(row.get("to_email") or "").strip().lower()
            status = str(row.get("status") or "").strip().lower()
            if to_email and status in {"sent", "failed", "bounced"}:
                latest_by_email[to_email] = status

    sent_count = sum(1 for value in latest_by_email.values() if value == "sent")
    failed_count = sum(1 for value in latest_by_email.values() if value in {"failed", "bounced"})

    if sent_count and failed_count:
        tracking.mail_delivery_status = "partial_sent"
    elif sent_count:
        tracking.mail_delivery_status = "complete_sent"
    elif failed_count:
        tracking.mail_delivery_status = "failed"
    else:
        tracking.mail_delivery_status = "pending"

    tracking.mailed = bool(latest_by_email)
    tracking.save(update_fields=["mail_delivery_status", "mailed", "updated_at"])
    return tracking.mail_delivery_status
