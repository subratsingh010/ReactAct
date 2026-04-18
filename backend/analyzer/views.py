import json
import os
import re
import subprocess
import tempfile
import urllib.error
import urllib.request
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

from django.contrib.auth.models import User
from django.db import transaction
from django.db.models import Q
from rest_framework import status
from rest_framework.exceptions import ValidationError
from rest_framework.parsers import FormParser, JSONParser, MultiPartParser
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView
from django.utils import timezone

from .pdf_parser import parse_resume_pdf
from .company_utils import normalize_company_name, resolve_company_for_job
from .models import Resume, MailTracking, MailTrackingEvent, Company, Employee, Job, Tracking, TrackingAction, UserProfile, ProfilePanel, WorkspaceMember, Template, Interview, Location
from .serializers import (
    ResumeSerializer,
    TailoredResumeSerializer,
    SignupSerializer,
    MailTrackingSerializer,
    CompanySerializer,
    EmployeeSerializer,
    JobSerializer,
    UserProfileSerializer,
    ProfilePanelSerializer,
    WorkspaceMemberSerializer,
    TemplateSerializer,
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
from .tracking_mail_utils import build_mail_tracking_status_map
from .management.commands.send_tracking_mails import Command as SendTrackingMailsCommand


APP_UI_TIME_ZONE = ZoneInfo('Asia/Kolkata')


def _user_profile_for_permissions(user):
    if not getattr(user, 'is_authenticated', False):
        return None
    profile = getattr(user, 'profile_info', None)
    if profile is not None:
        return profile
    return UserProfile.objects.filter(user=user).first()


def _user_role(user):
    if not getattr(user, 'is_authenticated', False):
        return UserProfile.ROLE_READ_ONLY
    if bool(getattr(user, 'is_superuser', False)):
        return UserProfile.ROLE_SUPERADMIN
    profile = _user_profile_for_permissions(user)
    role = str(getattr(profile, 'role', '') or '').strip().lower()
    allowed = {choice[0] for choice in UserProfile.ROLE_CHOICES}
    return role if role in allowed else UserProfile.ROLE_ADMIN


def _is_superadmin(user):
    return _user_role(user) == UserProfile.ROLE_SUPERADMIN


def _is_read_only_user(user):
    return _user_role(user) == UserProfile.ROLE_READ_ONLY


def _ensure_write_allowed(request):
    if _is_read_only_user(request.user):
        return Response({'detail': 'Read only users cannot create, update, or delete data.'}, status=status.HTTP_403_FORBIDDEN)
    return None


def _visible_user_ids_for_user(user):
    if not getattr(user, 'is_authenticated', False):
        return []
    if _is_superadmin(user):
        return list(User.objects.values_list('id', flat=True))
    return [user.id]


def _workspace_owner_for_user(user):
    if not getattr(user, 'is_authenticated', False):
        return None
    return user


def _accessible_owner_ids_for_user(user):
    return _visible_user_ids_for_user(user)


def _workspace_profile_for_user(user):
    if not getattr(user, 'is_authenticated', False):
        return None
    profile, _ = UserProfile.objects.get_or_create(
        user=user,
        defaults={
            'role': UserProfile.ROLE_ADMIN,
            'full_name': user.username,
            'email': user.email or '',
        },
    )
    if not profile.full_name:
        profile.full_name = user.username
    if not profile.email:
        profile.email = user.email or ''
    profile.save(update_fields=['full_name', 'email', 'updated_at'])
    return profile


def _accessible_profile_ids_for_user(user):
    user_ids = _accessible_owner_ids_for_user(user)
    if not user_ids:
        return []
    profile_ids = list(UserProfile.objects.filter(user_id__in=user_ids).values_list('id', flat=True))
    missing_user_ids = [uid for uid in user_ids if uid not in set(UserProfile.objects.filter(user_id__in=user_ids).values_list('user_id', flat=True))]
    for user_id in missing_user_ids:
        auth_user = User.objects.filter(id=user_id).first()
        if not auth_user:
            continue
        profile_ids.append(_workspace_profile_for_user(auth_user).id)
    return profile_ids


def _accessible_jobs_for_user(user):
    return Job.objects.filter(company__profile_id__in=_accessible_profile_ids_for_user(user))


def _workspace_owner_jobs_for_user(user):
    owner_profile = _workspace_profile_for_user(user)
    return Job.objects.filter(company__profile=owner_profile)


def _is_workspace_owner(user):
    return bool(getattr(user, 'is_authenticated', False)) and not _is_read_only_user(user)


def _can_manage_workspace_fully(user):
    return bool(getattr(user, 'is_authenticated', False)) and not _is_read_only_user(user)


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


def _resolve_tracking_delivery_status_from_events(event_rows, fallback_status='pending'):
    latest_by_target = {}
    fallback_counter = 0
    fallback_value = str(fallback_status or 'pending').strip().lower()

    for item in event_rows:
        payload = item.raw_payload if isinstance(getattr(item, 'raw_payload', None), dict) else {}
        status_value = str(getattr(item, 'status', '') or payload.get('status') or '').strip().lower()
        if status_value not in {'sent', 'failed', 'bounced'}:
            continue

        to_email = str(payload.get('to_email') or payload.get('recipient_email') or payload.get('receiver') or '').strip().lower()
        if to_email:
            latest_by_target[to_email] = status_value
            continue

        latest_by_target[f'event-{fallback_counter}'] = status_value
        fallback_counter += 1

    if not latest_by_target:
        return fallback_value if fallback_value in {'pending', 'sent_via_cron', 'successful_sent', 'mail_bounced', 'partial_sent', 'failed'} else 'pending'

    sent_count = sum(1 for value in latest_by_target.values() if value == 'sent')
    failed_count = sum(1 for value in latest_by_target.values() if value in {'failed', 'bounced'})

    if sent_count and failed_count:
        return 'partial_sent'
    if sent_count:
        if fallback_value == 'successful_sent':
            return 'successful_sent'
        return 'sent_via_cron'
    if failed_count:
        if any(value == 'bounced' for value in latest_by_target.values()):
            return 'mail_bounced'
        return 'failed'
    return 'pending'


def _build_tracking_delivery_summary(event_rows):
    passed_by_target = {}
    failed_by_target = {}

    for item in event_rows:
        payload = item.raw_payload if isinstance(getattr(item, 'raw_payload', None), dict) else {}
        status_value = str(getattr(item, 'status', '') or payload.get('status') or '').strip().lower()
        if status_value not in {'sent', 'failed', 'bounced'}:
            continue

        to_email = str(payload.get('to_email') or payload.get('recipient_email') or payload.get('receiver') or '').strip()
        employee_name = ''
        employee_id = getattr(item, 'employee_id', None)
        if employee_id and getattr(item, 'employee', None):
            employee_name = str(item.employee.name or '').strip()
        target_key = to_email.lower() if to_email else f'employee-{employee_id or item.id}'
        reason = str(
            payload.get('reason')
            or payload.get('failure_reason')
            or payload.get('bounce_reason')
            or getattr(item, 'notes', '')
            or ''
        ).strip()

        entry = {
            'employee_id': employee_id,
            'employee_name': employee_name,
            'email': to_email,
            'failure_type': 'bounced' if status_value == 'bounced' else status_value,
            'reason': reason,
            'action_at': item.action_at.isoformat() if item.action_at else '',
        }
        if status_value == 'sent':
            passed_by_target[target_key] = entry
        elif status_value in {'failed', 'bounced'}:
            failed_by_target[target_key] = entry

    passed = []
    failed = []
    for entry in passed_by_target.values():
        passed.append({
            'employee_id': entry['employee_id'],
            'employee_name': entry['employee_name'],
            'email': entry['email'],
            'reason': entry.get('reason', ''),
            'failure_type': entry.get('failure_type', ''),
            'action_at': entry['action_at'],
        })
    for entry in failed_by_target.values():
        failed.append({
            'employee_id': entry['employee_id'],
            'employee_name': entry['employee_name'],
            'email': entry['email'],
            'reason': entry.get('reason', ''),
            'failure_type': entry.get('failure_type', ''),
            'action_at': entry['action_at'],
        })

    passed.sort(key=lambda item: ((item.get('employee_name') or '').lower(), (item.get('email') or '').lower()))
    failed.sort(key=lambda item: ((item.get('employee_name') or '').lower(), (item.get('email') or '').lower()))

    return {
        'passed': passed,
        'failed': failed,
        'passed_count': len(passed),
        'failed_count': len(failed),
    }


def _build_tracking_employee_delivery_overview(selected_employees, mail_tracking):
    selected_list = selected_employees if isinstance(selected_employees, list) else []
    event_rows = []
    if mail_tracking:
        event_rows = list(
            MailTrackingEvent.objects
            .filter(mail_tracking=mail_tracking)
            .select_related('employee')
            .order_by('action_at', 'created_at')
        )

    events_by_employee = {}
    for item in event_rows:
        payload = item.raw_payload if isinstance(getattr(item, 'raw_payload', None), dict) else {}
        payload_status = str(payload.get('status') or '').strip().lower()
        status_value = str(getattr(item, 'status', '') or payload_status or '').strip().lower()
        if status_value == 'replied':
            continue

        employee_id = getattr(item, 'employee_id', None)
        to_email = str(payload.get('to_email') or payload.get('recipient_email') or payload.get('receiver') or '').strip().lower()
        if employee_id:
            key = f'employee:{employee_id}'
        elif to_email:
            key = f'email:{to_email}'
        else:
            continue
        events_by_employee.setdefault(key, []).append((item, payload, status_value))

    overview = []
    for employee in selected_list:
        employee_id = employee.get('id')
        email = str(employee.get('email') or '').strip()
        employee_events = events_by_employee.get(f'employee:{employee_id}') or events_by_employee.get(f'email:{email.lower()}') or []

        last_reason = ''
        latest_delivery_email = email
        latest_status_value = 'pending'
        latest_mail_type = ''
        latest_send_mode = ''
        latest_action_at = ''

        if employee_events:
            last_item = employee_events[-1][0]
            last_payload = employee_events[-1][1]
            latest_status_value = employee_events[-1][2] or 'pending'
            latest_action_at = last_item.action_at.isoformat() if last_item.action_at else ''
            latest_mail_type = str(getattr(last_item, 'mail_type', '') or '').strip()
            latest_send_mode = str(getattr(last_item, 'send_mode', '') or '').strip()
            latest_delivery_email = str(
                last_payload.get('to_email')
                or last_payload.get('recipient_email')
                or last_payload.get('receiver')
                or email
                or ''
            ).strip()

            for item, payload, item_status in employee_events:
                reason = str(
                    payload.get('reason')
                    or payload.get('failure_reason')
                    or payload.get('bounce_reason')
                    or getattr(item, 'notes', '')
                    or ''
                ).strip()
                if reason:
                    last_reason = reason

        overview.append({
            'employee_id': employee_id,
            'employee_name': str(employee.get('name') or '').strip(),
            'email': latest_delivery_email,
            'mail_type': latest_mail_type,
            'send_mode': latest_send_mode,
            'status': latest_status_value,
            'reason': last_reason,
            'action_at': latest_action_at,
        })
    return overview


def _follow_up_eligible_employees(tracking):
    if not tracking:
        return []
    events_query = Q(tracking=tracking)
    mail_tracking = _mail_tracking_for_row(tracking)
    if mail_tracking:
        events_query = events_query | Q(tracking__isnull=True, mail_tracking_id=mail_tracking.id)

    latest_by_employee = {}
    event_rows = (
        MailTrackingEvent.objects
        .filter(events_query, employee_id__isnull=False)
        .select_related('employee')
        .order_by('action_at', 'created_at')
    )
    for item in event_rows:
        payload = item.raw_payload if isinstance(getattr(item, 'raw_payload', None), dict) else {}
        status_value = str(getattr(item, 'status', '') or payload.get('status') or '').strip().lower()
        if status_value not in {'sent', 'failed', 'bounced'}:
            continue
        latest_by_employee[item.employee_id] = item

    eligible = []
    for item in latest_by_employee.values():
        payload = item.raw_payload if isinstance(getattr(item, 'raw_payload', None), dict) else {}
        status_value = str(getattr(item, 'status', '') or payload.get('status') or '').strip().lower()
        if status_value != 'sent':
            continue
        if not getattr(item, 'employee', None):
            continue
        eligible.append(item.employee)
    return eligible


def _normalize_tracking_template_ids(payload, request_data=None):
    values = payload.get('template_ids_ordered')
    if values in [None, '', []]:
        values = payload.get('achievement_ids_ordered')
    if hasattr(request_data, 'getlist'):
        list_values = [str(v or '').strip() for v in request_data.getlist('template_ids_ordered') if str(v or '').strip()]
        if not list_values:
            list_values = [str(v or '').strip() for v in request_data.getlist('achievement_ids_ordered') if str(v or '').strip()]
        if list_values:
            values = list_values
    if isinstance(values, str):
        values = [item.strip() for item in values.split(',') if item.strip()]
    if not isinstance(values, list):
        values = []
    cleaned = []
    seen = set()
    for value in values:
        text = str(value or '').strip()
        if not text or text in seen:
            continue
        seen.add(text)
        cleaned.append(text)
        if len(cleaned) >= 5:
            break
    return cleaned


def _resolve_tracking_templates(user, template_ids):
    if not template_ids:
        return []
    profile = _workspace_profile_for_user(user)
    if not profile:
        return []
    rows = list(Template.objects.filter(profile=profile, id__in=template_ids))
    row_map = {str(item.id): item for item in rows}
    return [row_map[item_id] for item_id in template_ids if item_id in row_map]


def _template_category(template_row):
    return str(getattr(template_row, 'category', 'general') or 'general').strip().lower() or 'general'


def _selected_intro_template_category(mail_type='fresh'):
    normalized_mail_type = str(mail_type or 'fresh').strip().lower()
    return 'follow_up' if normalized_mail_type == 'followed_up' else 'personalized'


def _validate_tracking_templates(templates, mail_type='fresh'):
    normalized_mail_type = str(mail_type or 'fresh').strip().lower()
    rows = list(templates or [])
    if normalized_mail_type == 'followed_up':
        if not rows:
            return 'For follow up, select at least 1 template.'
        if len(rows) > 2:
            return 'For follow up, select at most 2 templates.'
        categories = [_template_category(item) for item in rows]
        if any(category != 'follow_up' for category in categories):
            return 'For follow up, use only Follow Up templates.'
        return ''
    if not rows:
        return 'Select at least one template.'
    if len(rows) > 5:
        return 'Select at most 5 templates.'

    if len(rows) < 3:
        return 'For fresh mail, select at least 3 templates.'
    categories = [_template_category(item) for item in rows]
    if 'opening' not in categories:
        return 'For fresh mail, include at least one Opening template.'
    if 'closing' not in categories:
        return 'For fresh mail, include at least one Closing template.'
    return ''


def _mail_tracking_for_row(tracking):
    if not tracking:
        return None
    return getattr(tracking, 'mail_tracking_record', None)


def _mail_tracking_sent_at(mail_tracking):
    if not mail_tracking:
        return None
    event = (
        MailTrackingEvent.objects
        .filter(mail_tracking=mail_tracking, status='sent')
        .order_by('-action_at', '-created_at')
        .only('action_at')
        .first()
    )
    return event.action_at if event and event.action_at else None


def _event_got_replied(event):
    if not event:
        return False
    payload = event.raw_payload if isinstance(getattr(event, 'raw_payload', None), dict) else {}
    payload_status = str(payload.get('status') or '').strip().lower()
    if payload_status == 'replied':
        return True
    notes = str(getattr(event, 'notes', '') or '').strip().lower()
    return 'reply detected' in notes or 'got reply' in notes


def _mail_tracking_replied_at(mail_tracking):
    if not mail_tracking:
        return None
    events = (
        MailTrackingEvent.objects
        .filter(mail_tracking=mail_tracking)
        .order_by('-action_at', '-created_at')
    )
    for item in events:
        if _event_got_replied(item):
            return item.action_at if item.action_at else None
    return None


def _mail_tracking_got_replied(mail_tracking):
    if not mail_tracking:
        return False
    return any(_event_got_replied(item) for item in MailTrackingEvent.objects.filter(mail_tracking=mail_tracking))


def _tracking_action_delivery_fallback(tracking):
    if not tracking:
        return {'mailed': False, 'status': 'pending'}
    if getattr(tracking, 'schedule_time', None):
        return {'mailed': False, 'status': 'pending'}
    actions = list(tracking.actions.all().order_by('created_at'))
    if not actions:
        return {'mailed': False, 'status': 'pending'}
    has_sent = any(str(item.send_mode or '').strip().lower() == 'sent' for item in actions)
    has_scheduled = any(str(item.send_mode or '').strip().lower() == 'scheduled' for item in actions)
    if has_sent:
        return {'mailed': True, 'status': 'sent_via_cron'}
    if has_scheduled:
        return {'mailed': False, 'status': 'pending'}
    return {'mailed': bool(getattr(tracking, 'mailed', False)), 'status': str(getattr(tracking, 'mail_delivery_status', 'pending') or 'pending')}


def _should_force_pending_display(tracking):
    if not tracking:
        return False
    return (not bool(getattr(tracking, 'mailed', False))) and str(getattr(tracking, 'mail_delivery_status', 'pending') or 'pending').strip().lower() == 'pending'


def _tracking_sent_employee_map_for_day(tracking, action_type, action_at):
    if not tracking or not action_at:
        return {}
    action_day = timezone.localdate(action_at)
    mail_tracking = _mail_tracking_for_row(tracking)
    query = Q(tracking=tracking)
    if mail_tracking:
        query = query | Q(tracking__isnull=True, mail_tracking=mail_tracking)
    rows = (
        MailTrackingEvent.objects
        .filter(query, status='sent', mail_type=action_type, action_at__date=action_day)
        .select_related('employee')
        .order_by('action_at', 'id')
    )
    sent_map = {}
    for item in rows:
        if not item.employee_id:
            continue
        sent_map[item.employee_id] = str(item.employee.name or '').strip() if item.employee_id and item.employee else f'Employee #{item.employee_id}'
    return sent_map


def _user_sent_employee_map_for_day(user, action_type, action_at, employee_ids=None, exclude_tracking_id=None):
    if not user or not action_at:
        return {}
    action_day = timezone.localdate(action_at)
    profile = _workspace_profile_for_user(user)
    query = Q(tracking__profile=profile) | Q(mail_tracking__profile=profile)
    rows = (
        MailTrackingEvent.objects
        .filter(query, status='sent', mail_type=action_type, action_at__date=action_day)
        .select_related('employee', 'tracking', 'mail_tracking__tracking')
        .order_by('action_at', 'id')
    )
    if employee_ids:
        rows = rows.filter(employee_id__in=employee_ids)

    sent_map = {}
    for item in rows:
        item_tracking_id = item.tracking_id
        if not item_tracking_id and item.mail_tracking_id and item.mail_tracking and item.mail_tracking.tracking_id:
            item_tracking_id = item.mail_tracking.tracking_id
        if exclude_tracking_id and item_tracking_id == exclude_tracking_id:
            continue
        if not item.employee_id:
            continue
        sent_map[item.employee_id] = str(item.employee.name or '').strip() if item.employee_id and item.employee else f'Employee #{item.employee_id}'
    return sent_map


def _user_fresh_tracking_employee_map_for_day(user, employee_ids=None, exclude_tracking_id=None, day=None):
    if not user:
        return {}
    target_day = day or timezone.localdate()
    profile = _workspace_profile_for_user(user)
    rows = (
        Tracking.objects
        .filter(profile=profile, mail_type='fresh', created_at__date=target_day)
        .exclude(id=exclude_tracking_id)
    )
    if employee_ids:
        rows = rows.filter(selected_hrs__id__in=employee_ids)
    rows = rows.distinct()
    if not rows.exists():
        return {}

    employees = (
        Employee.objects
        .filter(selected_in_tracking_rows__in=rows)
        .distinct()
        .order_by('name', 'id')
    )
    if employee_ids:
        employees = employees.filter(id__in=employee_ids)

    employee_map = {}
    for item in employees:
        employee_map[item.id] = str(item.name or '').strip() or f'Employee #{item.id}'
    return employee_map


def _job_fresh_tracking_employee_map_for_day(user, job, employee_ids=None, exclude_tracking_id=None, day=None):
    if not user or not job:
        return {}
    target_day = day or timezone.localdate()
    profile = _workspace_profile_for_user(user)
    rows = (
        Tracking.objects
        .filter(profile=profile, job=job, mail_type='fresh', created_at__date=target_day)
        .exclude(id=exclude_tracking_id)
    )
    if employee_ids:
        rows = rows.filter(selected_hrs__id__in=employee_ids)
    rows = rows.distinct()
    if not rows.exists():
        return {}

    employees = (
        Employee.objects
        .filter(selected_in_tracking_rows__in=rows)
        .distinct()
        .order_by('name', 'id')
    )
    if employee_ids:
        employees = employees.filter(id__in=employee_ids)

    employee_map = {}
    for item in employees:
        employee_map[item.id] = str(item.name or '').strip() or f'Employee #{item.id}'
    return employee_map


def _same_day_job_tracking_row(user, job, day=None, exclude_tracking_id=None):
    if not user or not job:
        return None
    target_day = day or timezone.localdate()
    profile = _workspace_profile_for_user(user)
    rows = (
        Tracking.objects
        .filter(profile=profile, job=job, created_at__date=target_day)
        .exclude(id=exclude_tracking_id)
        .order_by('-created_at', '-id')
    )
    return rows.first()


def _fresh_action_employee_map_for_day(tracking, action_at, employee_ids=None):
    if not tracking or not action_at:
        return {}
    action_day = timezone.localdate(action_at)
    actions = tracking.actions.filter(action_type='fresh')
    employee_id_set = set()
    for item in actions:
        item_day = timezone.localdate(item.action_at) if item.action_at else None
        if item_day != action_day:
            continue
        meta = _tracking_action_note_meta(item.notes)
        for employee_id in meta.get('employee_ids') or []:
            try:
                employee_id_set.add(int(employee_id))
            except Exception:
                continue
    if employee_ids:
        employee_id_set &= {int(value) for value in employee_ids if str(value).strip()}
    if not employee_id_set:
        return {}
    employees = Employee.objects.filter(id__in=employee_id_set).order_by('name', 'id')
    employee_map = {}
    for item in employees:
        employee_map[item.id] = str(item.name or '').strip() or f'Employee #{item.id}'
    return employee_map


def _tracking_action_note_meta(notes):
    raw = str(notes or '').strip()
    if not raw:
        return {'label': '', 'employee_ids': [], 'count': 1}
    try:
        data = json.loads(raw)
    except Exception:
        return {'label': raw, 'employee_ids': [], 'count': 1}
    if not isinstance(data, dict):
        return {'label': raw, 'employee_ids': [], 'count': 1}
    employee_ids = []
    for value in data.get('employee_ids') or []:
        try:
            employee_ids.append(int(value))
        except Exception:
            continue
    count = data.get('count')
    try:
        count = max(1, int(count))
    except Exception:
        count = 1
    return {
        'label': str(data.get('label') or '').strip(),
        'employee_ids': employee_ids,
        'count': count,
    }


def _build_tracking_action_notes(*, label='', employee_ids=None, count=1):
    normalized_ids = []
    for value in employee_ids or []:
        try:
            normalized_ids.append(int(value))
        except Exception:
            continue
    payload = {}
    if str(label or '').strip():
        payload['label'] = str(label).strip()
    if normalized_ids:
        payload['employee_ids'] = sorted(set(normalized_ids))
    try:
        safe_count = max(1, int(count))
    except Exception:
        safe_count = 1
    if safe_count > 1:
        payload['count'] = safe_count
    return json.dumps(payload, separators=(',', ':')) if payload else ''


def _resolve_extension_user(request):
    user = getattr(request, 'user', None)
    if getattr(user, 'is_authenticated', False):
        return user
    return None

def _plain_text_from_html(value: str) -> str:
    import re

    t = str(value or "")
    t = re.sub(r"<style[^>]*>[\s\S]*?</style>", " ", t, flags=re.I)
    t = re.sub(r"<script[^>]*>[\s\S]*?</script>", " ", t, flags=re.I)
    t = re.sub(r"<[^>]+>", " ", t)
    t = t.replace("&nbsp;", " ").replace("&amp;", "&").replace("&lt;", "<").replace("&gt;", ">")
    t = re.sub(r"\s+", " ", t).strip()
    return t


def _remove_resume_file(resume):
    if not resume:
        return
    file_field = getattr(resume, 'file', None)
    if not file_field:
        return
    file_name = str(getattr(file_field, 'name', '') or '').strip()
    if not file_name:
        return
    try:
        file_field.delete(save=False)
    except Exception:
        pass
    if getattr(resume, 'file', None):
        resume.file = None


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


def _department_bucket_from_text(value: str) -> str:
    text = str(value or '').strip().lower()
    if not text:
        return 'other'
    if any(token in text for token in ['hr', 'human resource', 'talent', 'recruit', 'people ops', 'people operation']):
        return 'hr'
    if any(token in text for token in ['engineer', 'developer', 'sde', 'software', 'devops', 'architect', 'qa', 'data']):
        return 'engineering'
    return 'other'


def _employee_department_bucket(employee) -> str:
    dept = str(getattr(employee, 'department', '') or '').strip()
    role = str(getattr(employee, 'JobRole', '') or '').strip()
    merged = f'{dept} {role}'.strip()
    return _department_bucket_from_text(merged)


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
    value = value.strip("._- ")
    value = value.replace("-", " ")
    value = re.sub(r"\s+", "_", value).strip("._-").lower()
    return value or "resume"


def _default_pdf_filename(builder_data: dict, resume=None) -> str:
    data = builder_data if isinstance(builder_data, dict) else {}
    full_name = str(data.get("fullName") or "").strip()
    parts = []
    if full_name:
        parts.append(full_name)
    elif str(getattr(resume, "title", "") or "").strip():
        parts.append(str(getattr(resume, "title", "") or "").strip())

    resume_job = getattr(resume, "job", None) if resume else None
    company_name = ""
    job_code = ""
    if resume_job:
        job_code = str(getattr(resume_job, "job_id", "") or "").strip()
        company = getattr(resume_job, "company", None)
        company_name = str(getattr(company, "name", "") or "").strip()

    if company_name:
        parts.append(company_name)
    if job_code:
        parts.append(job_code)
    if not company_name:
        parts.append("3 YOE")

    stem = _sanitize_filename_stem(" - ".join([part for part in parts if part]) or "Resume")
    return f"{stem}.pdf"


def _pick_local_pdf_path(file_name: str, resume_id: int | None = None) -> Path:
    target_dir = Path(__file__).resolve().parents[1] / "storage" / "ats_pdfs"
    target_dir.mkdir(parents=True, exist_ok=True)
    stem = _sanitize_filename_stem(Path(str(file_name or "")).stem)
    if not stem:
        stem = "Resume"
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
                'role': UserProfile.ROLE_ADMIN,
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
                'role': UserProfile.ROLE_ADMIN,
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
        denied = _ensure_write_allowed(request)
        if denied:
            return denied
        profile = self._get_or_create(request)
        payload = dict(request.data or {})
        if not _is_superadmin(request.user):
            payload.pop('role', None)
        location_ref_raw = str(payload.get('location_ref') or '').strip()
        if 'location_ref' in payload and not location_ref_raw:
            payload['location_ref'] = None
        if location_ref_raw:
            try:
                location = Location.objects.get(id=location_ref_raw)
                payload['location_ref'] = location.id
                payload['location'] = location.name
            except Location.DoesNotExist:
                return Response({'detail': 'Location not found.'}, status=status.HTTP_400_BAD_REQUEST)
        preferred_location_refs = payload.get('preferred_location_refs')
        if preferred_location_refs is None and hasattr(request.data, 'getlist'):
            raw_list = [str(v or '').strip() for v in request.data.getlist('preferred_location_refs') if str(v or '').strip()]
            if raw_list:
                preferred_location_refs = raw_list
        if isinstance(preferred_location_refs, str):
            preferred_location_refs = [item.strip() for item in preferred_location_refs.split(',') if item.strip()]
        if preferred_location_refs is not None:
            payload['preferred_location_refs'] = preferred_location_refs
        serializer = UserProfileSerializer(profile, data=payload, partial=True)
        if serializer.is_valid():
            updated = serializer.save()
            return Response(UserProfileSerializer(updated).data, status=status.HTTP_200_OK)
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)


class ProfilePanelListCreateView(APIView):
    permission_classes = [IsAuthenticated]
    parser_classes = [JSONParser]
    max_panels = 2

    def get(self, request):
        rows = ProfilePanel.objects.filter(profile_id__in=_accessible_profile_ids_for_user(request.user)).order_by('-updated_at', '-created_at')
        return Response(ProfilePanelSerializer(rows, many=True).data, status=status.HTTP_200_OK)

    def post(self, request):
        denied = _ensure_write_allowed(request)
        if denied:
            return denied
        profile = _workspace_profile_for_user(request.user)
        if ProfilePanel.objects.filter(profile=profile).count() >= self.max_panels:
            return Response({'detail': 'Maximum 2 profile panels allowed.'}, status=status.HTTP_400_BAD_REQUEST)
        payload = dict(request.data or {})
        location_ref_raw = str(payload.get('location_ref') or '').strip()
        if 'location_ref' in payload and not location_ref_raw:
            payload['location_ref'] = None
        if location_ref_raw:
            try:
                location = Location.objects.get(id=location_ref_raw)
                payload['location_ref'] = location.id
                payload['location'] = location.name
            except Location.DoesNotExist:
                return Response({'detail': 'Location not found.'}, status=status.HTTP_400_BAD_REQUEST)
        preferred_location_refs = payload.get('preferred_location_refs')
        if preferred_location_refs is None and hasattr(request.data, 'getlist'):
            raw_list = [str(v or '').strip() for v in request.data.getlist('preferred_location_refs') if str(v or '').strip()]
            if raw_list:
                preferred_location_refs = raw_list
        if isinstance(preferred_location_refs, str):
            preferred_location_refs = [item.strip() for item in preferred_location_refs.split(',') if item.strip()]
        if preferred_location_refs is not None:
            payload['preferred_location_refs'] = preferred_location_refs
        serializer = ProfilePanelSerializer(data=payload, context={'request': request})
        if serializer.is_valid():
            row = serializer.save(profile=profile)
            return Response(ProfilePanelSerializer(row).data, status=status.HTTP_201_CREATED)
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)


class ProfilePanelDetailView(APIView):
    permission_classes = [IsAuthenticated]
    parser_classes = [JSONParser]

    def _get_row(self, request, panel_id):
        return ProfilePanel.objects.filter(profile_id__in=_accessible_profile_ids_for_user(request.user), id=panel_id).first()

    def put(self, request, panel_id):
        denied = _ensure_write_allowed(request)
        if denied:
            return denied
        row = self._get_row(request, panel_id)
        if not row:
            return Response({'detail': 'Profile panel not found.'}, status=status.HTTP_404_NOT_FOUND)
        payload = dict(request.data or {})
        location_ref_raw = str(payload.get('location_ref') or '').strip()
        if 'location_ref' in payload and not location_ref_raw:
            payload['location_ref'] = None
        if location_ref_raw:
            try:
                location = Location.objects.get(id=location_ref_raw)
                payload['location_ref'] = location.id
                payload['location'] = location.name
            except Location.DoesNotExist:
                return Response({'detail': 'Location not found.'}, status=status.HTTP_400_BAD_REQUEST)
        preferred_location_refs = payload.get('preferred_location_refs')
        if preferred_location_refs is None and hasattr(request.data, 'getlist'):
            raw_list = [str(v or '').strip() for v in request.data.getlist('preferred_location_refs') if str(v or '').strip()]
            if raw_list:
                preferred_location_refs = raw_list
        if isinstance(preferred_location_refs, str):
            preferred_location_refs = [item.strip() for item in preferred_location_refs.split(',') if item.strip()]
        if preferred_location_refs is not None:
            payload['preferred_location_refs'] = preferred_location_refs
        serializer = ProfilePanelSerializer(row, data=payload, partial=True, context={'request': request})
        if serializer.is_valid():
            updated = serializer.save()
            return Response(ProfilePanelSerializer(updated).data, status=status.HTTP_200_OK)
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

    def delete(self, request, panel_id):
        denied = _ensure_write_allowed(request)
        if denied:
            return denied
        row = self._get_row(request, panel_id)
        if not row:
            return Response({'detail': 'Profile panel not found.'}, status=status.HTTP_404_NOT_FOUND)
        row.hard_delete()
        return Response(status=status.HTTP_204_NO_CONTENT)


class WorkspaceMemberListCreateView(APIView):
    permission_classes = [IsAuthenticated]
    parser_classes = [JSONParser]

    def get(self, request):
        owner_ids = _accessible_owner_ids_for_user(request.user)
        rows = WorkspaceMember.objects.filter(owner_id__in=owner_ids).select_related('member').order_by('-updated_at', '-created_at')
        return Response(WorkspaceMemberSerializer(rows, many=True).data, status=status.HTTP_200_OK)

    def post(self, request):
        denied = _ensure_write_allowed(request)
        if denied:
            return denied
        payload = dict(request.data or {})
        username = str(payload.get('username') or payload.get('member_username') or '').strip()
        if not username:
            return Response({'detail': 'username is required.'}, status=status.HTTP_400_BAD_REQUEST)
        if WorkspaceMember.objects.filter(owner=request.user, is_active=True).count() >= 1:
            return Response({'detail': 'Only one additional member is allowed.'}, status=status.HTTP_400_BAD_REQUEST)
        member = User.objects.filter(username__iexact=username).first()
        if not member:
            return Response({'detail': 'User not found.'}, status=status.HTTP_400_BAD_REQUEST)
        if member.id == request.user.id:
            return Response({'detail': 'Owner cannot be added as member.'}, status=status.HTTP_400_BAD_REQUEST)
        existing_member_workspace = WorkspaceMember.objects.filter(member=member, is_active=True).exclude(owner=request.user).first()
        if existing_member_workspace:
            return Response({'detail': 'This user is already linked to another owner.'}, status=status.HTTP_400_BAD_REQUEST)
        row, created = WorkspaceMember.objects.get_or_create(
            owner=request.user,
            member=member,
            defaults={'is_active': True},
        )
        if not created and not row.is_active:
            row.is_active = True
            row.save(update_fields=['is_active', 'updated_at'])
        return Response(WorkspaceMemberSerializer(row).data, status=status.HTTP_201_CREATED if created else status.HTTP_200_OK)


class WorkspaceMemberDetailView(APIView):
    permission_classes = [IsAuthenticated]
    parser_classes = [JSONParser]

    def delete(self, request, member_id):
        denied = _ensure_write_allowed(request)
        if denied:
            return denied
        row = WorkspaceMember.objects.filter(owner_id__in=_accessible_owner_ids_for_user(request.user), id=member_id).first()
        if not row:
            return Response({'detail': 'Workspace member not found.'}, status=status.HTTP_404_NOT_FOUND)
        row.hard_delete()
        return Response(status=status.HTTP_204_NO_CONTENT)


class TemplateListCreateView(APIView):
    permission_classes = [IsAuthenticated]
    parser_classes = [JSONParser]

    def get(self, request):
        rows = Template.objects.filter(profile_id__in=_accessible_profile_ids_for_user(request.user)).order_by('-created_at')
        return Response(TemplateSerializer(rows, many=True).data, status=status.HTTP_200_OK)

    def post(self, request):
        denied = _ensure_write_allowed(request)
        if denied:
            return denied
        serializer = TemplateSerializer(data=request.data, context={'request': request})
        if serializer.is_valid():
            profile = _workspace_profile_for_user(request.user)
            created = serializer.save(profile=profile)
            return Response(TemplateSerializer(created).data, status=status.HTTP_201_CREATED)
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)


class TemplateDetailView(APIView):
    permission_classes = [IsAuthenticated]
    parser_classes = [JSONParser]

    def _resolve_id(self, template_id=None, achievement_id=None):
        return template_id if template_id is not None else achievement_id

    def _get_object(self, request, template_id=None, achievement_id=None):
        return Template.objects.get(id=self._resolve_id(template_id, achievement_id), profile_id__in=_accessible_profile_ids_for_user(request.user))

    def put(self, request, template_id=None, achievement_id=None):
        denied = _ensure_write_allowed(request)
        if denied:
            return denied
        try:
            row = self._get_object(request, template_id, achievement_id)
        except Template.DoesNotExist:
            return Response({'detail': 'Template not found.'}, status=status.HTTP_404_NOT_FOUND)
        serializer = TemplateSerializer(row, data=request.data, partial=True, context={'request': request})
        if serializer.is_valid():
            updated = serializer.save()
            return Response(TemplateSerializer(updated).data, status=status.HTTP_200_OK)
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

    def delete(self, request, template_id=None, achievement_id=None):
        denied = _ensure_write_allowed(request)
        if denied:
            return denied
        try:
            row = self._get_object(request, template_id, achievement_id)
        except Template.DoesNotExist:
            return Response({'detail': 'Template not found.'}, status=status.HTTP_404_NOT_FOUND)
        row.hard_delete()
        return Response(status=status.HTTP_204_NO_CONTENT)


AchievementListCreateView = TemplateListCreateView
AchievementDetailView = TemplateDetailView


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
        rows = Interview.objects.filter(
            profile_id__in=_accessible_profile_ids_for_user(request.user),
            company_key=company_key,
            job_role_key=job_key,
        )
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
        rows = Interview.objects.filter(profile_id__in=_accessible_profile_ids_for_user(request.user)).order_by('-updated_at', '-created_at')
        return Response(InterviewSerializer(rows, many=True).data, status=status.HTTP_200_OK)

    def post(self, request):
        denied = _ensure_write_allowed(request)
        if denied:
            return denied
        payload = dict(request.data or {})
        payload['action'] = str(payload.get('action') or payload.get('section') or 'active').strip().lower() or 'active'
        raw_job_id = str(payload.get('job') or '').strip()
        selected_job = None
        if raw_job_id:
            try:
                selected_job = _accessible_jobs_for_user(request.user).get(
                    id=raw_job_id,
                    is_removed=False,
                )
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
            created = serializer.save(profile=_workspace_profile_for_user(request.user), max_round_reached=requested_round if requested_round else 0)
            self._append_milestone_event(created, created.stage, created.action)
            return Response(InterviewSerializer(created).data, status=status.HTTP_201_CREATED)
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)


class InterviewDetailView(APIView):
    permission_classes = [IsAuthenticated]
    parser_classes = [JSONParser]
    STAGE_LABELS = InterviewListCreateView.STAGE_LABELS
    ACTION_LABELS = InterviewListCreateView.ACTION_LABELS

    def _get_object(self, request, interview_id):
        return Interview.objects.get(id=interview_id, profile_id__in=_accessible_profile_ids_for_user(request.user))

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
        denied = _ensure_write_allowed(request)
        if denied:
            return denied
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
                selected_job = _accessible_jobs_for_user(request.user).get(
                    id=raw_job_id,
                    is_removed=False,
                )
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
        duplicate = Interview.objects.filter(
            profile_id__in=_accessible_profile_ids_for_user(request.user),
            company_key=company_key,
            job_role_key=job_key,
        ).exclude(id=row.id).exists()
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
        denied = _ensure_write_allowed(request)
        if denied:
            return denied
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
        denied = _ensure_write_allowed(request)
        if denied:
            return denied
        saved = _set_user_profile_config(request.user, request.data if isinstance(request.data, dict) else {})
        return Response(saved)


class LocationListView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        rows = Location.objects.all().order_by('name')
        return Response(LocationSerializer(rows, many=True).data, status=status.HTTP_200_OK)


class ResumeListCreateView(APIView):
    permission_classes = [IsAuthenticated]

    def _serializer_payload(self, request):
        data = request.data.copy() if hasattr(request.data, 'copy') else dict(request.data or {})
        if hasattr(data, 'pop'):
            data.pop('job', None)
        return data

    def _apply_default_resume(self, profile, resume):
        if not getattr(resume, 'is_default', False):
            return
        Resume.objects.filter(profile=profile).exclude(id=resume.id).update(is_default=False)

    def _resolve_job(self, request, raw_value):
        job_id = str(raw_value or '').strip()
        if not job_id:
            return None
        try:
            return _accessible_jobs_for_user(request.user).get(id=job_id, is_removed=False)
        except Job.DoesNotExist:
            raise ValidationError({'job': 'Job not found.'})

    def get(self, request):
        # Always return the latest 6 resumes (do not de-dupe by title).
        include_tailored = str(request.query_params.get('include_tailored') or '').strip().lower() in {'1', 'true', 'yes'}
        qs = Resume.objects.filter(profile_id__in=_accessible_profile_ids_for_user(request.user))
        if not include_tailored:
            qs = qs.filter(is_tailored=False)
        qs = qs.order_by('-updated_at', '-created_at')[:6]
        serializer = ResumeSerializer(qs, many=True)
        return Response(serializer.data)

    def post(self, request):
        denied = _ensure_write_allowed(request)
        if denied:
            return denied
        serializer = ResumeSerializer(data=self._serializer_payload(request))
        if serializer.is_valid():
            profile = _workspace_profile_for_user(request.user)
            title = (serializer.validated_data.get('title') or '').strip()
            if not title:
                return Response({'title': ['This field may not be blank.']}, status=status.HTTP_400_BAD_REQUEST)

            incoming_builder = serializer.validated_data.get("builder_data") or {}
            incoming_text = (serializer.validated_data.get("original_text") or "").strip()
            if not incoming_text and incoming_builder:
                incoming_text = _builder_data_to_text(incoming_builder)
            try:
                selected_job = self._resolve_job(request, serializer.validated_data.get('job') or request.data.get('job'))
            except ValidationError as exc:
                return Response(exc.detail, status=status.HTTP_400_BAD_REQUEST)

            created = serializer.save(
                profile=profile,
                is_tailored=False,
                job=selected_job,
                source_resume=None,
                ats_pdf_path='',
                file=None,
                original_text=incoming_text or serializer.validated_data.get("original_text") or "",
            )
            _remove_resume_file(created)
            created.save(update_fields=['file'])
            self._apply_default_resume(profile, created)

            return Response(ResumeSerializer(created).data, status=status.HTTP_201_CREATED)
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)


class ResumeDetailView(APIView):
    permission_classes = [IsAuthenticated]

    def _serializer_payload(self, request):
        data = request.data.copy() if hasattr(request.data, 'copy') else dict(request.data or {})
        if hasattr(data, 'pop'):
            data.pop('job', None)
        return data

    def _apply_default_resume(self, profile, resume):
        if not getattr(resume, 'is_default', False):
            return
        Resume.objects.filter(profile=profile).exclude(id=resume.id).update(is_default=False)

    def _resolve_job(self, request, raw_value):
        if raw_value in [None, '']:
            return None
        job_id = str(raw_value or '').strip()
        if not job_id:
            return None
        try:
            return _accessible_jobs_for_user(request.user).get(id=job_id, is_removed=False)
        except Job.DoesNotExist:
            raise ValidationError({'job': 'Job not found.'})

    def get_object(self, request, resume_id):
        return Resume.objects.get(id=resume_id, profile_id__in=_accessible_profile_ids_for_user(request.user))

    def get(self, request, resume_id):
        try:
            resume = self.get_object(request, resume_id)
        except Resume.DoesNotExist:
            return Response({'detail': 'Resume not found.'}, status=status.HTTP_404_NOT_FOUND)
        serializer = ResumeSerializer(resume)
        return Response(serializer.data)

    def put(self, request, resume_id):
        denied = _ensure_write_allowed(request)
        if denied:
            return denied
        try:
            resume = self.get_object(request, resume_id)
        except Resume.DoesNotExist:
            return Response({'detail': 'Resume not found.'}, status=status.HTTP_404_NOT_FOUND)

        serializer = ResumeSerializer(resume, data=self._serializer_payload(request), partial=True)
        if serializer.is_valid():
            builder_changed = 'builder_data' in serializer.validated_data
            title_changed = 'title' in serializer.validated_data
            save_kwargs = {
                'ats_pdf_path': '' if (builder_changed or title_changed) else resume.ats_pdf_path,
                'file': None,
            }
            if 'job' in request.data or 'job' in serializer.validated_data:
                try:
                    save_kwargs['job'] = self._resolve_job(request, serializer.validated_data.get('job') if 'job' in serializer.validated_data else request.data.get('job'))
                except ValidationError as exc:
                    return Response(exc.detail, status=status.HTTP_400_BAD_REQUEST)
            updated = serializer.save(**save_kwargs)
            _remove_resume_file(updated)
            updated.save(update_fields=['file'])
            self._apply_default_resume(_workspace_profile_for_user(request.user), updated)
            return Response(serializer.data)
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

    def delete(self, request, resume_id):
        denied = _ensure_write_allowed(request)
        if denied:
            return denied
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
            Resume.objects
            .filter(profile_id__in=_accessible_profile_ids_for_user(request.user), is_tailored=True)
            .select_related('job', 'source_resume')
            .order_by('-updated_at', '-created_at')
        )
        job_id = str(request.query_params.get('job_id') or '').strip()
        if job_id:
            rows = rows.filter(job_id=job_id)
        q = str(request.query_params.get('q') or '').strip()
        if q:
            rows = rows.filter(Q(title__icontains=q) | Q(job__job_id__icontains=q) | Q(job__role__icontains=q))
        return Response(TailoredResumeSerializer(rows, many=True).data, status=status.HTTP_200_OK)

    def post(self, request):
        denied = _ensure_write_allowed(request)
        if denied:
            return denied
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
                job = _accessible_jobs_for_user(request.user).get(id=raw_job)
            except Job.DoesNotExist:
                return Response({'job': ['Job not found.']}, status=status.HTTP_400_BAD_REQUEST)
        if raw_resume:
            try:
                resume = Resume.objects.get(id=raw_resume, profile_id__in=_accessible_profile_ids_for_user(request.user))
            except Resume.DoesNotExist:
                return Response({'resume': ['Resume not found.']}, status=status.HTTP_400_BAD_REQUEST)
        else:
            return Response({'resume': ['Original resume reference is required.']}, status=status.HTTP_400_BAD_REQUEST)

        created = Resume.objects.create(
            profile=_workspace_profile_for_user(request.user),
            title=name,
            builder_data=sanitize_builder_data(builder_data),
            is_tailored=True,
            job=job,
            source_resume=resume,
            status='optimized',
            file=None,
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

    def _enforce_resume_limit(self, profile):
        keep_ids = list(
            Resume.objects.filter(profile=profile)
            .order_by('-updated_at', '-created_at')
            .values_list('id', flat=True)[:6]
        )
        default_id = (
            Resume.objects.filter(profile=profile, is_default=True)
            .order_by('-updated_at', '-created_at')
            .values_list('id', flat=True)
            .first()
        )
        if default_id and default_id not in keep_ids and keep_ids:
            keep_ids = keep_ids[:-1] + [default_id]
        Resume.objects.filter(profile=profile).exclude(id__in=keep_ids).delete()

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
                reference_resume = Resume.objects.get(id=int(reference_resume_id), profile_id__in=_accessible_profile_ids_for_user(request.user))
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

        resumes = list(Resume.objects.filter(profile_id__in=_accessible_profile_ids_for_user(request.user), is_tailored=False).order_by('-updated_at', '-created_at')) if is_authenticated else []
        best = find_best_resume_match(keywords, resumes)
        latest_resume = resumes[0] if resumes else None
        selected_job = None
        if is_authenticated and job_id:
            selected_job = _accessible_jobs_for_user(request.user).filter(job_id__iexact=job_id, is_removed=False).order_by('-updated_at', '-created_at').first()

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
        if _is_read_only_user(request.user):
            return Response({'detail': 'Read only users cannot create, update, or delete data.'}, status=status.HTTP_403_FORBIDDEN)

        created = Resume.objects.create(
            profile=_workspace_profile_for_user(request.user),
            title=title,
            original_text=plain_text,
            builder_data=tailored_builder,
            is_tailored=True,
            job=selected_job,
            source_resume=reference_resume or best.resume or latest_resume,
            status='optimized',
            file=None,
        )
        self._enforce_resume_limit(_workspace_profile_for_user(request.user))

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
        denied = _ensure_write_allowed(request)
        if denied:
            return denied
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
        denied = _ensure_write_allowed(request)
        if denied:
            return denied
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

        resume = None
        resume_id = str(request.data.get("resume_id") or "").strip()
        if resume_id:
            try:
                resume = Resume.objects.get(id=resume_id, profile_id__in=_accessible_profile_ids_for_user(request.user))
            except Resume.DoesNotExist:
                return Response({"detail": "Resume not found for PDF export."}, status=status.HTTP_404_NOT_FOUND)

        file_name = _default_pdf_filename(builder_data, resume=resume)
        output_path = _pick_local_pdf_path(file_name, resume.id if resume else None)

        ok, note = _render_pdf_from_html(html_text, output_path)
        if not ok:
            return Response(
                {"detail": f"Could not generate local PDF. {note}"},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )

        if resume:
            resume.ats_pdf_path = str(output_path)
            resume.save(update_fields=["ats_pdf_path", "updated_at"])

        return Response(
            {
                "saved_path": str(output_path),
                "file_name": output_path.name,
                "resume_id": resume.id if resume else None,
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
                dt = timezone.make_aware(dt, APP_UI_TIME_ZONE)
            return dt
        except Exception:
            return None

    def _resolve_company(self, request, payload):
        profile_ids = _accessible_profile_ids_for_user(request.user)
        company_id = payload.get('company')
        if company_id:
            try:
                return Company.objects.get(
                    id=company_id,
                    profile_id__in=profile_ids,
                )
            except Company.DoesNotExist:
                return None

        company_name = str(payload.get('company_name') or '').strip()
        if not company_name:
            company_name = 'New Company'
        company, _ = Company.objects.get_or_create(
            profile=_workspace_profile_for_user(request.user),
            name=company_name,
        )
        return company

    def _resolve_job(self, request, company, payload):
        explicit_job_id = payload.get('job')
        if explicit_job_id:
            try:
                return _accessible_jobs_for_user(request.user).get(
                    id=explicit_job_id,
                    is_removed=False,
                )
            except Job.DoesNotExist:
                return None

        job_code = str(payload.get('job_id') or '').strip()
        workspace_owner = _workspace_owner_for_user(request.user)
        if job_code:
            job = _workspace_owner_jobs_for_user(request.user).filter(
                company=company,
                job_id__iexact=job_code,
                is_removed=False,
            ).first()
            if not job:
                job = Job.objects.create(
                    company=company,
                    job_id=job_code,
                    role=str(payload.get('role') or 'Software Developer').strip() or 'Software Developer',
                    job_link=str(payload.get('job_url') or '').strip(),
                )
        else:
            job = Job.objects.create(
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
            return Resume.objects.get(id=raw, profile_id__in=_accessible_profile_ids_for_user(request.user))
        except Resume.DoesNotExist:
            return None

    def _sync_selected_hrs(self, request, tracking, payload):
        targets = self._resolve_selected_hrs(request, tracking.job.company_id if tracking.job_id and tracking.job and tracking.job.company_id else None, payload)
        if targets is not None:
            tracking.selected_hrs.set(targets)

    def _resolve_selected_hrs(self, request, company_id, payload):
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
            targets = Employee.objects.filter(
                owner_profile_id__in=_accessible_profile_ids_for_user(request.user),
                id__in=selected_ids,
                working_mail=True,
            )
        elif isinstance(selected_names, list) and selected_names and company_id:
            targets = Employee.objects.filter(
                owner_profile_id__in=_accessible_profile_ids_for_user(request.user),
                company_id=company_id,
                working_mail=True,
                name__in=[str(name or '').strip() for name in selected_names if str(name or '').strip()],
            )
        if selected_ids is not None or selected_names is not None:
            return targets
        return None

    def _append_action(self, tracking, payload):
        action = payload.get('append_action')
        if not isinstance(action, dict):
            return None

        action_type = str(action.get('type') or '').strip().lower()
        if action_type not in {'fresh', 'followup'}:
            return 'Invalid action type.'

        send_mode = str(action.get('send_mode') or 'now').strip().lower()
        mapped_send_mode = 'sent' if send_mode == 'now' else 'scheduled'
        action_at = self._to_datetime(action.get('action_at')) or timezone.now()
        existing_actions = tracking.actions.all()
        has_any_action = existing_actions.exists()
        has_fresh_action = existing_actions.filter(action_type='fresh').exists()
        selected_employee_ids = sorted([emp.id for emp in tracking.selected_hrs.all() if emp.id])
        if not has_any_action:
            action_type = 'fresh'
        elif action_type == 'followup' and not has_fresh_action:
            return 'First milestone must be Fresh before any Follow Up.'

        notes = _build_tracking_action_notes(employee_ids=selected_employee_ids)
        last_action = existing_actions.order_by('-created_at').first()
        if last_action and str(last_action.action_type or '') == action_type:
            last_day = timezone.localdate(last_action.action_at) if last_action.action_at else None
            current_day = timezone.localdate(action_at)
            last_meta = _tracking_action_note_meta(last_action.notes)
            last_employee_ids = sorted(last_meta.get('employee_ids') or [])
            if last_day == current_day and (not last_employee_ids or last_employee_ids == selected_employee_ids):
                next_count = int(last_meta.get('count') or 1) + 1
                last_action.notes = _build_tracking_action_notes(
                    label=last_meta.get('label') or '',
                    employee_ids=selected_employee_ids,
                    count=next_count,
                )
                last_action.action_at = action_at
                last_action.save(update_fields=['notes', 'action_at', 'updated_at'])
                tracking.mail_type = 'followed_up' if action_type == 'followup' else 'fresh'
                if action_type == 'fresh':
                    tracking.mailed = True
                    tracking.save(update_fields=['mail_type', 'mailed', 'updated_at'])
                else:
                    tracking.save(update_fields=['mail_type', 'updated_at'])
                return None
        if action_type == 'fresh':
            selected_employees = list(tracking.selected_hrs.all())
            action_history_today = _fresh_action_employee_map_for_day(
                tracking,
                action_at,
                employee_ids=selected_employee_ids,
            )
            overlap = [action_history_today.get(emp.id) or str(emp.name or '').strip() or f'Employee #{emp.id}' for emp in selected_employees if emp.id in action_history_today]
            if overlap:
                return f'Fresh mail already used these employees earlier today in this tracking: {", ".join(overlap)}. Choose fully different employees, use Follow Up, or send tomorrow.'
            same_job_fresh_today = _job_fresh_tracking_employee_map_for_day(
                tracking.user,
                tracking.job,
                exclude_tracking_id=tracking.id,
                day=timezone.localdate(action_at),
            )
            cross_sent_today = _user_sent_employee_map_for_day(
                tracking.user,
                'fresh',
                action_at,
                employee_ids=selected_employee_ids,
                exclude_tracking_id=tracking.id,
            )
            overlap = [cross_sent_today.get(emp.id) or str(emp.name or '').strip() or f'Employee #{emp.id}' for emp in selected_employees if emp.id in cross_sent_today]
            if overlap:
                return f'Already sent Fresh mail today to: {", ".join(overlap)}. Use follow up, choose different employees, or send tomorrow.'
            sent_today = _tracking_sent_employee_map_for_day(tracking, 'fresh', action_at)
            overlap = [sent_today.get(emp.id) or str(emp.name or '').strip() or f'Employee #{emp.id}' for emp in selected_employees if emp.id in sent_today]
            if overlap:
                return f'Already sent Fresh mail today to: {", ".join(overlap)}. Use different employees today or send tomorrow.'
            if sent_today and selected_employees:
                notes = _build_tracking_action_notes(label='FD', employee_ids=selected_employee_ids)
            elif last_action and str(last_action.action_type or '') == 'fresh':
                last_day = timezone.localdate(last_action.action_at) if last_action.action_at else None
                current_day = timezone.localdate(action_at)
                last_meta = _tracking_action_note_meta(last_action.notes)
                last_employee_ids = sorted(last_meta.get('employee_ids') or [])
                if last_day == current_day and last_employee_ids and last_employee_ids != selected_employee_ids:
                    notes = _build_tracking_action_notes(label='FD', employee_ids=selected_employee_ids)
            elif same_job_fresh_today and selected_employees:
                notes = _build_tracking_action_notes(label='FD', employee_ids=selected_employee_ids)
        elif action_type == 'followup':
            if last_action and str(last_action.action_type or '') == 'followup':
                last_day = timezone.localdate(last_action.action_at) if last_action.action_at else None
                current_day = timezone.localdate(action_at)
                last_meta = _tracking_action_note_meta(last_action.notes)
                last_employee_ids = sorted(last_meta.get('employee_ids') or [])
                if last_day == current_day and last_employee_ids and last_employee_ids != selected_employee_ids:
                    notes = _build_tracking_action_notes(label='FUD', employee_ids=selected_employee_ids)

        TrackingAction.objects.create(
            tracking=tracking,
            action_type=action_type,
            send_mode=mapped_send_mode,
            action_at=action_at,
            notes=notes,
        )
        tracking.mail_type = 'followed_up' if action_type == 'followup' else 'fresh'
        if action_type == 'fresh':
            tracking.mailed = True
        tracking.save(update_fields=['mail_type', 'mailed', 'updated_at'])
        return None

    def _serialize_tracking_row(self, tracking, available_hr_map):
        job = tracking.job
        resume = tracking.resume
        tailored_resume = tracking.resume if tracking.resume_id and tracking.resume and bool(getattr(tracking.resume, 'is_tailored', False)) else None
        company = job.company if job and job.company_id else None
        mail_tracking = _mail_tracking_for_row(tracking)
        mailed_at_value = _mail_tracking_sent_at(mail_tracking)
        replied_at_value = _mail_tracking_replied_at(mail_tracking)
        got_replied_value = _mail_tracking_got_replied(mail_tracking)
        action_delivery_fallback = _tracking_action_delivery_fallback(tracking)
        force_pending_display = _should_force_pending_display(tracking)
        is_currently_scheduled = bool(tracking.schedule_time)
        available = available_hr_map.get(company.id if company else None, [])
        selected = list(tracking.selected_hrs.all())
        tailored_rows = []
        oldest_tailored = None
        if job:
            related_tailored = list(job.resumes.filter(is_tailored=True).order_by('created_at', 'id'))
            tailored_rows = [
                {
                    'id': item.id,
                    'name': str(item.title or '').strip() or f'Tailored Resume #{item.id}',
                    'created_at': item.created_at.isoformat() if item.created_at else None,
                }
                for item in related_tailored
            ]
            if related_tailored:
                oldest = related_tailored[0]
                oldest_tailored = {
                    'id': oldest.id,
                    'name': str(oldest.title or '').strip() or f'Tailored Resume #{oldest.id}',
                    'created_at': oldest.created_at.isoformat() if oldest.created_at else None,
                    'builder_data': oldest.builder_data or {},
                }
        resume_preview = None
        if resume and not bool(getattr(resume, 'is_tailored', False)):
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
                    'title': str(tailored_resume.title or '').strip() or f'Tailored Resume #{tailored_resume.id}',
                    'builder_data': tailored_builder,
                }
        milestones = [
            {
                'type': item.action_type,
                'mode': item.send_mode,
                'at': item.action_at.isoformat() if item.action_at else '',
                'notes': _tracking_action_note_meta(item.notes).get('label') or '',
                'count': _tracking_action_note_meta(item.notes).get('count') or 1,
                'employee_ids': _tracking_action_note_meta(item.notes).get('employee_ids') or [],
            }
            for item in tracking.actions.all().order_by('created_at')[:20]
        ]
        events_query = Q(tracking=tracking)
        mail_tracking = _mail_tracking_for_row(tracking)
        if mail_tracking:
            events_query = events_query | Q(tracking__isnull=True, mail_tracking_id=mail_tracking.id)
        delivery_events = list(
            MailTrackingEvent.objects
            .filter(events_query)
            .order_by('action_at', 'created_at')
        )
        template_choice = 'follow_up_applied' if str(tracking.mail_type or 'fresh').strip() == 'followed_up' else 'cold_applied'
        compose_mode = 'template_based'
        mailed_at_value = _mail_tracking_sent_at(mail_tracking)
        replied_at_value = _mail_tracking_replied_at(mail_tracking)
        got_replied_value = _mail_tracking_got_replied(mail_tracking)
        delivery_summary = _build_tracking_delivery_summary(delivery_events)
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
            'tailored_resume_name': str(tailored_resume.title or '').strip() if tailored_resume else '',
            'is_closed': bool(job.is_closed) if job else False,
            'is_removed': bool(job.is_removed) if job else False,
            'mailed': False if is_currently_scheduled else (False if force_pending_display else bool(tracking.mailed)),
            'mail_delivery_status': _resolve_tracking_delivery_status_from_events(
                [] if (is_currently_scheduled or force_pending_display) else delivery_events,
                fallback_status='pending' if (is_currently_scheduled or force_pending_display) else (
                    (str(tracking.mail_delivery_status or '').strip().lower() or 'pending')
                ),
            ),
            'applied_date': job.applied_at.isoformat() if job and job.applied_at else None,
            'posting_date': job.date_of_posting.isoformat() if job and job.date_of_posting else None,
            'is_open': bool(not bool(job.is_closed) if job else True),
            'available_hrs': [emp.name for emp in available],
            'available_hr_ids': [emp.id for emp in available],
            'selected_hrs': [emp.name for emp in selected],
            'selected_hr_ids': [emp.id for emp in selected],
            'template_id': tracking.template_id,
            'template_name': str(tracking.template.name or '').strip() if tracking.template_id and tracking.template else '',
            'template_text': str(tracking.template.achievement or '').strip() if tracking.template_id and tracking.template else '',
            'template_ids_ordered': list(tracking.template_ids_ordered or []),
            'personalized_template_id': tracking.personalized_template_id,
            'use_hardcoded_personalized_intro': bool(tracking.use_hardcoded_personalized_intro),
            'achievement_id': tracking.template_id,
            'achievement_name': str(tracking.template.name or '').strip() if tracking.template_id and tracking.template else '',
            'achievement_text': str(tracking.template.achievement or '').strip() if tracking.template_id and tracking.template else '',
            'achievement_ids_ordered': list(tracking.template_ids_ordered or []),
            'selected_achievements': [
                {
                    'id': item.id,
                    'name': str(item.name or '').strip(),
                    'achievement': str(item.achievement or '').strip(),
                    'paragraph': str(item.achievement or '').strip(),
                    'category': str(item.category or 'general').strip(),
                }
                for item in _resolve_tracking_templates(
                    tracking.user,
                    tracking.template_ids_ordered if isinstance(tracking.template_ids_ordered, list) else [],
                )
            ],
            'selected_templates': [
                {
                    'id': item.id,
                    'name': str(item.name or '').strip(),
                    'paragraph': str(item.achievement or '').strip(),
                    'category': str(item.category or 'general').strip(),
                }
                for item in _resolve_tracking_templates(
                    tracking.user,
                    tracking.template_ids_ordered if isinstance(tracking.template_ids_ordered, list) else [],
                )
            ],
            'selected_personalized_template': (
                {
                    'id': tracking.personalized_template.id,
                    'name': str(tracking.personalized_template.name or '').strip(),
                    'paragraph': str(tracking.personalized_template.achievement or '').strip(),
                    'category': str(tracking.personalized_template.category or 'personalized').strip(),
                }
                if tracking.personalized_template_id and tracking.personalized_template else None
            ),
            'template_choice': template_choice,
            'template_subject': str(tracking.mail_subject or '').strip(),
            'template_message': '',
            'compose_mode': compose_mode,
            'hardcoded_follow_up': True,
            'schedule_time': tracking.schedule_time.isoformat() if tracking.schedule_time else None,
            'template_name': template_choice,
            'delivery_summary': delivery_summary,
            'mail_type': str(tracking.mail_type or 'fresh'),
            'action': str(tracking.mail_type or 'fresh'),
            'got_replied': got_replied_value,
            'needs_tailored': False,
            'tailoring_scope': '',
            'is_freezed': bool(tracking.is_freezed),
            'freezed_at': tracking.freezed_at.isoformat() if tracking.freezed_at else None,
            'mail_tracking_id': mail_tracking.id if mail_tracking else None,
            'maild_at': mailed_at_value.isoformat() if mailed_at_value else None,
            'mailed_at': mailed_at_value.isoformat() if mailed_at_value else None,
            'replied_at': replied_at_value.isoformat() if replied_at_value else None,
            'milestones': milestones,
            'created_at': tracking.created_at.isoformat() if tracking.created_at else '',
            'updated_at': tracking.updated_at.isoformat() if tracking.updated_at else '',
        }

    def _has_company_mail_pattern(self, company):
        return bool(company and str(getattr(company, 'mail_format', '') or '').strip())

    def get(self, request):
        visible_profile_ids = _accessible_profile_ids_for_user(request.user)
        queryset = (
            Tracking.objects.filter(profile_id__in=visible_profile_ids)
            .select_related('job__company', 'resume', 'mail_tracking_record', 'template')
            .prefetch_related('selected_hrs', 'actions', 'job__resumes')
        )
        company_name = str(request.query_params.get('company_name') or '').strip()
        if company_name:
            queryset = queryset.filter(job__company__name__icontains=company_name)

        job_id = str(request.query_params.get('job_id') or '').strip()
        if job_id:
            queryset = queryset.filter(job__job_id__icontains=job_id)

        applied_date = str(request.query_params.get('applied_date') or '').strip()
        if applied_date:
            queryset = queryset.filter(job__applied_at=applied_date)

        mailed = str(request.query_params.get('mailed') or '').strip().lower()
        if mailed == 'yes':
            queryset = queryset.filter(mailed=True)
        elif mailed == 'no':
            queryset = queryset.filter(mailed=False)

        last_action = str(request.query_params.get('last_action') or '').strip().lower()
        if last_action == 'fresh':
            queryset = queryset.filter(mail_type='fresh')
        elif last_action in {'followup', 'followed_up'}:
            queryset = queryset.filter(mail_type='followed_up')

        ordering = str(request.query_params.get('ordering') or '-created_at').strip()
        ordering_map = {
            'applied_at': ['job__applied_at', 'id'],
            '-applied_at': ['-job__applied_at', '-id'],
            'created_at': ['created_at', 'id'],
            '-created_at': ['-created_at', '-id'],
            'company_name': ['job__company__name', 'id'],
            '-company_name': ['-job__company__name', '-id'],
            'job_id': ['job__job_id', 'id'],
            '-job_id': ['-job__job_id', '-id'],
            'role': ['job__role', 'id'],
            '-role': ['-job__role', '-id'],
        }
        queryset = queryset.order_by(*(ordering_map.get(ordering) or ordering_map['-created_at']))
        rows, meta = _paginate_queryset(queryset, request, default_page_size=10, max_page_size=100)
        company_ids = {
            row.job.company_id
            for row in rows
            if row.job_id and row.job and row.job.company_id
        }
        employees = Employee.objects.filter(
            owner_profile_id__in=visible_profile_ids,
            company_id__in=company_ids,
            working_mail=True,
        ).order_by('name')
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
        denied = _ensure_write_allowed(request)
        if denied:
            return denied
        payload = request.data or {}
        schedule_time = self._to_datetime(payload.get('schedule_time'))
        mail_type = str(payload.get('mail_type') or payload.get('action') or 'fresh').strip().lower()
        if mail_type not in {'fresh', 'followed_up'}:
            mail_type = 'fresh'
        template_choice = 'follow_up_applied' if mail_type == 'followed_up' else 'cold_applied'
        if mail_type == 'followed_up' and not schedule_time:
            schedule_time = timezone.now()
        company = self._resolve_company(request, payload)
        if not company:
            return Response({'detail': 'Company not found.'}, status=status.HTTP_400_BAD_REQUEST)
        job = self._resolve_job(request, company, payload)
        if not job:
            return Response({'detail': 'Job not found.'}, status=status.HTTP_400_BAD_REQUEST)
        resume = self._resolve_resume(request, payload)
        if payload.get('resume') not in [None, '', 'null'] and not resume:
            return Response({'detail': 'Resume not found.'}, status=status.HTTP_400_BAD_REQUEST)
        tailored_resume = None
        tailored_resume_id = str(payload.get('tailored_resume') or '').strip()
        if tailored_resume_id:
            tailored_resume = Resume.objects.filter(
                id=tailored_resume_id,
                profile_id__in=_accessible_profile_ids_for_user(request.user),
                is_tailored=True,
            ).first()
            if not tailored_resume and job:
                tailored_resume = job.resumes.filter(
                    profile_id__in=_accessible_profile_ids_for_user(request.user),
                    is_tailored=True,
                ).order_by('created_at', 'id').first()
            if not tailored_resume:
                return Response({'detail': 'Tailored resume not found.'}, status=status.HTTP_400_BAD_REQUEST)
        template_ids_ordered = _normalize_tracking_template_ids(payload, request.data)
        if not template_ids_ordered:
            legacy_template_raw = str(payload.get('template') or payload.get('template_id') or payload.get('achievement') or payload.get('achievement_id') or '').strip()
            if legacy_template_raw:
                template_ids_ordered = [legacy_template_raw]
        templates = _resolve_tracking_templates(_workspace_owner_for_user(request.user), template_ids_ordered)
        if template_ids_ordered and len(templates) != len(template_ids_ordered):
            return Response({'detail': 'One or more templates were not found.'}, status=status.HTTP_400_BAD_REQUEST)
        template_error = _validate_tracking_templates(templates, mail_type)
        if template_error:
            return Response({'detail': template_error}, status=status.HTTP_400_BAD_REQUEST)
        template = templates[0] if templates else None
        personalized_template = None
        personalized_template_id = str(payload.get('personalized_template') or '').strip()
        if personalized_template_id:
            intro_category = _selected_intro_template_category(mail_type)
            personalized_template = Template.objects.filter(
                id=personalized_template_id,
                profile=_workspace_profile_for_user(request.user),
                category=intro_category,
            ).first()
            if not personalized_template:
                personalized_template = Template.objects.filter(
                    id=personalized_template_id,
                    profile_id__in=_accessible_profile_ids_for_user(request.user),
                    category=intro_category,
                ).first()
            if not personalized_template:
                return Response({'detail': f'{intro_category.replace("_", " ").title()} template not found.'}, status=status.HTTP_400_BAD_REQUEST)
        selected_targets = self._resolve_selected_hrs(
            request,
            job.company_id if job and job.company_id else None,
            payload,
        )
        selected_employees = list(selected_targets) if selected_targets is not None else []
        selected_employee_ids = sorted([emp.id for emp in selected_employees if emp.id])

        reuse_existing_row = None
        if mail_type == 'fresh':
            reuse_existing_row = _same_day_job_tracking_row(_workspace_owner_for_user(request.user), job, timezone.localdate())
            if reuse_existing_row:
                existing_selected_ids = sorted(list(reuse_existing_row.selected_hrs.values_list('id', flat=True)))
                overlap = [
                    str(emp.name or '').strip() or f'Employee #{emp.id}'
                    for emp in selected_employees
                    if emp.id in existing_selected_ids
                ]
                if overlap:
                    return Response(
                        {'detail': f'Fresh tracking already exists today for this job and: {", ".join(overlap)}. Choose different employees or use Follow Up.'},
                        status=status.HTTP_400_BAD_REQUEST,
                    )

        tracking = reuse_existing_row or Tracking.objects.create(
            profile=_workspace_profile_for_user(request.user),
            job=job,
            template=template,
            template_ids_ordered=[item.id for item in templates],
            personalized_template=personalized_template,
            resume=resume,
            use_hardcoded_personalized_intro=self._to_bool(payload.get('use_hardcoded_personalized_intro'), default=False),
            schedule_time=schedule_time,
            mail_delivery_status='pending',
            mailed=self._to_bool(payload.get('mailed'), default=False),
            mail_type=mail_type,
            mail_subject=str(payload.get('template_subject') or payload.get('mail_subject') or payload.get('subject') or '').strip(),
        )
        tracking.job = job
        tracking.template = template
        tracking.template_ids_ordered = [item.id for item in templates]
        tracking.personalized_template = personalized_template
        tracking.resume = tailored_resume or resume
        tracking.use_hardcoded_personalized_intro = self._to_bool(payload.get('use_hardcoded_personalized_intro'), default=False)
        tracking.schedule_time = schedule_time
        tracking.mail_type = mail_type
        tracking.mail_subject = str(payload.get('template_subject') or payload.get('mail_subject') or payload.get('subject') or tracking.mail_subject or '').strip()
        tracking.mailed = self._to_bool(payload.get('mailed'), default=tracking.mailed if reuse_existing_row else False)
        tracking.save()
        if selected_targets is not None:
            tracking.selected_hrs.set(selected_targets)
        if mail_type == 'followed_up':
            eligible_follow_up_ids = {emp.id for emp in _follow_up_eligible_employees(tracking) if emp and emp.id}
            if not eligible_follow_up_ids:
                if not reuse_existing_row:
                    tracking.hard_delete()
                return Response(
                    {'detail': 'No contacted employee is available for follow up yet. Send Fresh mail first.'},
                    status=status.HTTP_400_BAD_REQUEST,
                )
            invalid_follow_up = [
                str(emp.name or '').strip() or f'Employee #{emp.id}'
                for emp in tracking.selected_hrs.all()
                if emp.id not in eligible_follow_up_ids
            ]
            if invalid_follow_up:
                if not reuse_existing_row:
                    tracking.hard_delete()
                return Response(
                    {'detail': f'Follow Up can only be sent to employees already contacted in this tracking row: {", ".join(invalid_follow_up)}.'},
                    status=status.HTTP_400_BAD_REQUEST,
                )
        if mail_type == 'fresh':
            selected_employees = list(tracking.selected_hrs.all())
            selected_employee_ids = sorted([emp.id for emp in selected_employees if emp.id])
            existing_fresh_today = _user_fresh_tracking_employee_map_for_day(
                tracking.user,
                employee_ids=selected_employee_ids,
                exclude_tracking_id=tracking.id,
                day=timezone.localdate(),
            )
            overlap = [existing_fresh_today.get(emp.id) or str(emp.name or '').strip() or f'Employee #{emp.id}' for emp in selected_employees if emp.id in existing_fresh_today]
            if overlap:
                if not reuse_existing_row:
                    tracking.hard_delete()
                return Response(
                    {'detail': f'Fresh tracking already exists today for: {", ".join(overlap)}. Use Follow Up, choose different employees, or try tomorrow.'},
                    status=status.HTTP_400_BAD_REQUEST,
                )
            same_tracking_fresh_today = _fresh_action_employee_map_for_day(
                tracking,
                timezone.now(),
                employee_ids=selected_employee_ids,
            )
            overlap = [same_tracking_fresh_today.get(emp.id) or str(emp.name or '').strip() or f'Employee #{emp.id}' for emp in selected_employees if emp.id in same_tracking_fresh_today]
            if overlap:
                if not reuse_existing_row:
                    tracking.hard_delete()
                return Response(
                    {'detail': f'Fresh mail already used these employees earlier today in this tracking: {", ".join(overlap)}. Choose fully different employees, use Follow Up, or send tomorrow.'},
                    status=status.HTTP_400_BAD_REQUEST,
                )
        if not self._has_company_mail_pattern(company):
            if not reuse_existing_row:
                tracking.hard_delete()
            return Response(
                {'detail': 'Company mail pattern is required to create tracking.'},
                status=status.HTTP_400_BAD_REQUEST,
            )
        action_error = self._append_action(tracking, payload)
        if action_error:
            return Response({'detail': action_error}, status=status.HTTP_400_BAD_REQUEST)

        available = Employee.objects.filter(
            owner_profile_id__in=_accessible_profile_ids_for_user(request.user),
            company_id=company.id,
            working_mail=True,
        ).order_by('name')
        available_hr_map = {company.id: list(available)}
        return Response(
            self._serialize_tracking_row(
                Tracking.objects.filter(id=tracking.id).prefetch_related('selected_hrs', 'actions', 'job__resumes').select_related('job__company', 'resume', 'mail_tracking_record', 'template').first(),
                available_hr_map,
            ),
            status=status.HTTP_200_OK if reuse_existing_row else status.HTTP_201_CREATED,
        )


class ApplicationTrackingDetailView(APIView):
    permission_classes = [IsAuthenticated]
    parser_classes = [JSONParser, MultiPartParser, FormParser]

    def _get_object(self, request, tracking_id):
        return Tracking.objects.get(id=tracking_id, profile_id__in=_accessible_profile_ids_for_user(request.user))

    def _get_object_any(self, request, tracking_id):
        return Tracking.objects.get(id=tracking_id, profile_id__in=_accessible_profile_ids_for_user(request.user))

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
                dt = timezone.make_aware(dt, APP_UI_TIME_ZONE)
            return dt
        except Exception:
            return None

    def _serialize_tracking_row(self, row):
        company = row.job.company if row.job_id and row.job and row.job.company_id else None
        resume = row.resume if row.resume_id else None
        tailored_resume = row.resume if row.resume_id and row.resume and bool(getattr(row.resume, 'is_tailored', False)) else None
        available = []
        if company:
            available = list(Employee.objects.filter(owner_profile=row.profile, company_id=company.id, working_mail=True).order_by('name'))
        selected = list(row.selected_hrs.all())
        tailored_rows = []
        oldest_tailored = None
        if row.job_id and row.job:
            related_tailored = list(row.job.resumes.filter(is_tailored=True).order_by('created_at', 'id'))
            tailored_rows = [
                {
                    'id': item.id,
                    'name': str(item.title or '').strip() or f'Tailored Resume #{item.id}',
                    'created_at': item.created_at.isoformat() if item.created_at else None,
                }
                for item in related_tailored
            ]
            if related_tailored:
                oldest = related_tailored[0]
                oldest_tailored = {
                    'id': oldest.id,
                    'name': str(oldest.title or '').strip() or f'Tailored Resume #{oldest.id}',
                    'created_at': oldest.created_at.isoformat() if oldest.created_at else None,
                    'builder_data': oldest.builder_data or {},
                }
        resume_preview = None
        if resume and not bool(getattr(resume, 'is_tailored', False)):
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
                    'title': str(tailored_resume.title or '').strip() or f'Tailored Resume #{tailored_resume.id}',
                    'builder_data': tailored_builder,
                }
        milestones = [
            {
                'type': item.action_type,
                'mode': item.send_mode,
                'at': item.action_at.isoformat() if item.action_at else '',
                'notes': _tracking_action_note_meta(item.notes).get('label') or '',
                'count': _tracking_action_note_meta(item.notes).get('count') or 1,
                'employee_ids': _tracking_action_note_meta(item.notes).get('employee_ids') or [],
            }
            for item in row.actions.all().order_by('created_at')[:20]
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
        mail_tracking = _mail_tracking_for_row(row)
        if mail_tracking:
            events_query = events_query | Q(tracking__isnull=True, mail_tracking_id=mail_tracking.id)
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
            sender = str(payload.get('from_email') or '').strip()
            event_status = str(item.status or '').strip().lower()
            payload_status = str(payload.get('status') or '').strip().lower()
            direction = 'incoming' if ((payload_status == 'replied') or (_event_got_replied(item) and sender)) else 'outgoing'
            mail_events.append(
                {
                    'id': item.id,
                    'employee_id': item.employee_id,
                    'employee_name': str(item.employee.name or '').strip() if item.employee_id and item.employee else '',
                    'mail_type': str(item.mail_type or '').strip(),
                    'send_mode': str(item.send_mode or '').strip(),
                    'status': str(item.status or '').strip(),
                    'action_at': item.action_at.isoformat() if item.action_at else '',
                    'got_replied': _event_got_replied(item),
                    'notes': str(item.notes or '').strip(),
                    'subject': subject,
                    'message': message,
                    'from_email': sender,
                    'to_email': receiver,
                    'direction': direction,
                    'message_id': str(payload.get('message_id') or item.source_message_id or '').strip(),
                    'thread_message_ids': [
                        str(value or '').strip()
                        for value in (payload.get('thread_message_ids') or payload.get('references') or [])
                        if str(value or '').strip()
                    ],
                }
            )
        template_choice = 'follow_up_applied' if str(row.mail_type or 'fresh').strip() == 'followed_up' else 'cold_applied'
        compose_mode = 'template_based'
        mailed_at_value = _mail_tracking_sent_at(mail_tracking)
        replied_at_value = _mail_tracking_replied_at(mail_tracking)
        got_replied_value = _mail_tracking_got_replied(mail_tracking)
        action_delivery_fallback = _tracking_action_delivery_fallback(row)
        force_pending_display = _should_force_pending_display(row)
        is_currently_scheduled = bool(row.schedule_time)
        delivery_summary = _build_tracking_delivery_summary(event_rows)
        employee_delivery_overview = _build_tracking_employee_delivery_overview(selected_employees, mail_tracking)
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
            'tailored_resume_name': str(tailored_resume.title or '').strip() if tailored_resume else '',
            'is_closed': bool(row.job.is_closed) if row.job_id and row.job else False,
            'is_removed': bool(row.job.is_removed) if row.job_id and row.job else False,
            'mailed': False if is_currently_scheduled else (False if force_pending_display else bool(row.mailed)),
            'mail_delivery_status': _resolve_tracking_delivery_status_from_events(
                [] if (is_currently_scheduled or force_pending_display) else event_rows,
                fallback_status='pending' if (is_currently_scheduled or force_pending_display) else (
                    (str(row.mail_delivery_status or '').strip().lower() or 'pending')
                ),
            ),
            'applied_date': row.job.applied_at.isoformat() if row.job_id and row.job and row.job.applied_at else None,
            'posting_date': row.job.date_of_posting.isoformat() if row.job_id and row.job and row.job.date_of_posting else None,
            'is_open': bool(not row.job.is_closed) if row.job_id and row.job else True,
            'available_hrs': [emp.name for emp in available],
            'available_hr_ids': [emp.id for emp in available],
            'selected_hrs': [emp.name for emp in selected],
            'selected_hr_ids': [emp.id for emp in selected],
            'template_id': row.template_id,
            'template_name': str(row.template.name or '').strip() if row.template_id and row.template else '',
            'template_text': str(row.template.achievement or '').strip() if row.template_id and row.template else '',
            'template_ids_ordered': list(row.template_ids_ordered or []),
            'personalized_template_id': row.personalized_template_id,
            'use_hardcoded_personalized_intro': bool(row.use_hardcoded_personalized_intro),
            'achievement_id': row.template_id,
            'achievement_name': str(row.template.name or '').strip() if row.template_id and row.template else '',
            'achievement_text': str(row.template.achievement or '').strip() if row.template_id and row.template else '',
            'achievement_ids_ordered': list(row.template_ids_ordered or []),
            'selected_achievements': [
                {
                    'id': item.id,
                    'name': str(item.name or '').strip(),
                    'achievement': str(item.achievement or '').strip(),
                    'paragraph': str(item.achievement or '').strip(),
                    'category': str(item.category or 'general').strip(),
                }
                for item in _resolve_tracking_templates(
                    row.user,
                    row.template_ids_ordered if isinstance(row.template_ids_ordered, list) else [],
                )
            ],
            'selected_templates': [
                {
                    'id': item.id,
                    'name': str(item.name or '').strip(),
                    'paragraph': str(item.achievement or '').strip(),
                    'category': str(item.category or 'general').strip(),
                }
                for item in _resolve_tracking_templates(
                    row.user,
                    row.template_ids_ordered if isinstance(row.template_ids_ordered, list) else [],
                )
            ],
            'selected_personalized_template': (
                {
                    'id': row.personalized_template.id,
                    'name': str(row.personalized_template.name or '').strip(),
                    'paragraph': str(row.personalized_template.achievement or '').strip(),
                    'category': str(row.personalized_template.category or 'personalized').strip(),
                }
                if row.personalized_template_id and row.personalized_template else None
            ),
            'selected_employees': selected_employees,
            'template_choice': template_choice,
            'template_subject': str(row.mail_subject or '').strip(),
            'template_message': '',
            'compose_mode': compose_mode,
            'hardcoded_follow_up': True,
            'schedule_time': row.schedule_time.isoformat() if row.schedule_time else None,
            'template_name': template_choice,
            'mail_events': mail_events,
            'delivery_summary': delivery_summary,
            'employee_delivery_overview': employee_delivery_overview,
            'mail_type': str(row.mail_type or 'fresh'),
            'action': str(row.mail_type or 'fresh'),
            'got_replied': got_replied_value,
            'needs_tailored': False,
            'tailoring_scope': '',
            'is_freezed': bool(row.is_freezed),
            'freezed_at': row.freezed_at.isoformat() if row.freezed_at else None,
            'mail_tracking_id': mail_tracking.id if mail_tracking else None,
            'maild_at': mailed_at_value.isoformat() if mailed_at_value else None,
            'mailed_at': mailed_at_value.isoformat() if mailed_at_value else None,
            'replied_at': replied_at_value.isoformat() if replied_at_value else None,
            'milestones': milestones,
            'created_at': row.created_at.isoformat() if row.created_at else '',
            'updated_at': row.updated_at.isoformat() if row.updated_at else '',
        }

    def get(self, request, tracking_id):
        try:
            row = (
                Tracking.objects
                .filter(id=tracking_id, profile_id__in=_accessible_profile_ids_for_user(request.user))
                .select_related('job__company', 'mail_tracking_record', 'resume', 'template', 'personalized_template')
                .prefetch_related('selected_hrs', 'actions', 'job__resumes')
                .first()
            )
            if not row:
                raise Tracking.DoesNotExist
        except Tracking.DoesNotExist:
            return Response({'detail': 'Tracking row not found.'}, status=status.HTTP_404_NOT_FOUND)
        return Response(self._serialize_tracking_row(row), status=status.HTTP_200_OK)

    @transaction.atomic
    def put(self, request, tracking_id):
        denied = _ensure_write_allowed(request)
        if denied:
            return denied
        try:
            row = self._get_object(request, tracking_id)
        except Tracking.DoesNotExist:
            return Response({'detail': 'Tracking row not found.'}, status=status.HTTP_404_NOT_FOUND)

        payload = request.data or {}
        send_now = self._to_bool(payload.get('send_now'), default=False)
        job = row.job

        def rollback_detail(detail, status_code=status.HTTP_400_BAD_REQUEST):
            transaction.set_rollback(True)
            return Response({'detail': detail}, status=status_code)

        company_id = payload.get('company')
        company_name = str(payload.get('company_name') or '').strip()
        company = job.company if job and job.company_id else None
        if company_id:
            try:
                company = Company.objects.get(id=company_id, profile_id__in=_accessible_profile_ids_for_user(request.user))
            except Company.DoesNotExist:
                return Response({'detail': 'Company not found.'}, status=status.HTTP_400_BAD_REQUEST)
        elif company_name:
            company, _ = Company.objects.get_or_create(profile=row.profile, name=company_name)

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
        if 'mail_delivery_status' in payload:
            status_value = str(payload.get('mail_delivery_status') or '').strip().lower()
            if status_value in {'pending', 'sent_via_cron', 'successful_sent', 'mail_bounced', 'failed', 'partial_sent'}:
                row.mail_delivery_status = status_value
        if 'resume' in payload:
            raw_resume_id = str(payload.get('resume') or '').strip()
            if not raw_resume_id:
                row.resume = None
            else:
                try:
                    row.resume = Resume.objects.get(id=raw_resume_id, profile_id__in=_accessible_profile_ids_for_user(request.user))
                except Resume.DoesNotExist:
                    return rollback_detail('Resume not found.')
        if 'tailored_resume' in payload:
            raw_tailored_id = str(payload.get('tailored_resume') or '').strip()
            if not raw_tailored_id:
                if row.resume_id and row.resume and bool(getattr(row.resume, 'is_tailored', False)):
                    row.resume = None
            else:
                tailored = Resume.objects.filter(
                    id=raw_tailored_id,
                    profile_id__in=_accessible_profile_ids_for_user(request.user),
                    is_tailored=True,
                ).first()
                if not tailored and row.job_id and row.job:
                    tailored = row.job.resumes.filter(
                        profile_id__in=_accessible_profile_ids_for_user(request.user),
                        is_tailored=True,
                    ).order_by('created_at', 'id').first()
                if not tailored:
                    return rollback_detail('Tailored resume not found.')
                row.resume = tailored
        if 'template' in payload or 'template_id' in payload or 'template_ids_ordered' in payload or 'achievement' in payload or 'achievement_id' in payload or 'achievement_ids_ordered' in payload:
            template_ids_ordered = _normalize_tracking_template_ids(payload, request.data)
            if not template_ids_ordered:
                legacy_template_raw = str(payload.get('template') or payload.get('template_id') or payload.get('achievement') or payload.get('achievement_id') or '').strip()
                if legacy_template_raw:
                    template_ids_ordered = [legacy_template_raw]
            templates = _resolve_tracking_templates(row.user, template_ids_ordered)
            if template_ids_ordered and len(templates) != len(template_ids_ordered):
                return rollback_detail('One or more templates were not found.')
            template_error = _validate_tracking_templates(
                templates,
                str(payload.get('mail_type') or row.mail_type or 'fresh'),
            )
            if template_error:
                return rollback_detail(template_error)
            row.template_ids_ordered = [item.id for item in templates]
            row.template = templates[0] if templates else None
        if 'personalized_template' in payload:
            raw_personalized_id = str(payload.get('personalized_template') or '').strip()
            if not raw_personalized_id:
                row.personalized_template = None
            else:
                intro_category = _selected_intro_template_category(
                    payload.get('mail_type') or payload.get('action') or row.mail_type or 'fresh'
                )
                selected_personalized = Template.objects.filter(
                    id=raw_personalized_id,
                    profile_id__in=_accessible_profile_ids_for_user(request.user),
                    category=intro_category,
                ).first()
                if not selected_personalized:
                    return rollback_detail(f'{intro_category.replace("_", " ").title()} template not found.')
                row.personalized_template = selected_personalized
        if 'mail_type' in payload or 'action' in payload:
            action_text = str(payload.get('mail_type') or payload.get('action') or '').strip()
            if action_text in {'fresh', 'followed_up'}:
                row.mail_type = action_text
        if 'template_subject' in payload or 'mail_subject' in payload or 'subject' in payload:
            row.mail_subject = str(payload.get('template_subject') or payload.get('mail_subject') or payload.get('subject') or '').strip()
        if 'use_hardcoded_personalized_intro' in payload:
            row.use_hardcoded_personalized_intro = self._to_bool(
                payload.get('use_hardcoded_personalized_intro'),
                default=row.use_hardcoded_personalized_intro,
            )
        if not any(key in payload for key in ['template', 'template_id', 'template_ids_ordered', 'achievement', 'achievement_id', 'achievement_ids_ordered']):
            template_error = _validate_tracking_templates(
                _resolve_tracking_templates(
                    row.user,
                    row.template_ids_ordered if isinstance(row.template_ids_ordered, list) else (
                        [str(row.template_id)] if row.template_id else []
                    ),
                ),
                row.mail_type,
            )
            if template_error:
                return rollback_detail(template_error)
        if 'schedule_time' in payload:
            row.schedule_time = self._to_datetime(payload.get('schedule_time'))
            if row.schedule_time:
                row.mailed = False
                row.mail_delivery_status = 'pending'
        elif send_now:
            row.schedule_time = None
        if 'is_freezed' in payload:
            next_freezed = self._to_bool(payload.get('is_freezed'), default=row.is_freezed)
            row.is_freezed = next_freezed
            row.freezed_at = timezone.now() if next_freezed else None
        if any(key in payload for key in ['maild_at', 'mailed_at', 'replied_at', 'mailed']):
            mail_tracking = _mail_tracking_for_row(row)
            if not mail_tracking:
                mail_tracking = MailTracking.objects.create(profile=row.profile, tracking=row, resume=row.resume)

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

        next_selected = None
        if isinstance(selected_hr_ids, list):
            next_selected = Employee.objects.filter(
                owner_profile_id__in=_accessible_profile_ids_for_user(request.user),
                id__in=selected_hr_ids,
                working_mail=True,
            )
        elif isinstance(selected_hrs, list):
            target_names = [str(name or '').strip() for name in selected_hrs if str(name or '').strip()]
            company_id_ref = row.job.company_id if row.job_id and row.job and row.job.company_id else None
            next_selected = Employee.objects.filter(
                owner_profile_id__in=_accessible_profile_ids_for_user(request.user),
                company_id=company_id_ref,
                working_mail=True,
                name__in=target_names,
            )

        if next_selected is not None:
            row.selected_hrs.set(next_selected)

        if row.mail_type == 'followed_up':
            eligible_follow_up_ids = {emp.id for emp in _follow_up_eligible_employees(row) if emp and emp.id}
            if not eligible_follow_up_ids:
                return rollback_detail('No contacted employee is available for follow up yet. Send Fresh mail first.')
            invalid_follow_up = [
                str(emp.name or '').strip() or f'Employee #{emp.id}'
                for emp in row.selected_hrs.all()
                if emp.id not in eligible_follow_up_ids
            ]
            if invalid_follow_up:
                return rollback_detail(f'Follow Up can only be sent to employees already contacted in this tracking row: {", ".join(invalid_follow_up)}.')

        if row.mail_type == 'fresh':
            selected_employees = list(row.selected_hrs.all())
            selected_employee_ids = sorted([emp.id for emp in selected_employees if emp.id])
            existing_fresh_today = _user_fresh_tracking_employee_map_for_day(
                request.user,
                employee_ids=selected_employee_ids,
                exclude_tracking_id=row.id,
                day=timezone.localdate(),
            )
            overlap = [existing_fresh_today.get(emp.id) or str(emp.name or '').strip() or f'Employee #{emp.id}' for emp in selected_employees if emp.id in existing_fresh_today]
            if overlap:
                return rollback_detail(f'Fresh tracking already exists today for: {", ".join(overlap)}. Use Follow Up, choose different employees, or try tomorrow.')
            same_tracking_fresh_today = _fresh_action_employee_map_for_day(
                row,
                timezone.now(),
                employee_ids=selected_employee_ids,
            )
            overlap = [same_tracking_fresh_today.get(emp.id) or str(emp.name or '').strip() or f'Employee #{emp.id}' for emp in selected_employees if emp.id in same_tracking_fresh_today]
            if overlap:
                return rollback_detail(f'Fresh mail already used these employees earlier today in this tracking: {", ".join(overlap)}. Choose fully different employees, use Follow Up, or send tomorrow.')

        row.save()

        company_ref = row.job.company if row.job_id and row.job and row.job.company_id else None
        if not self._has_company_mail_pattern(company_ref):
            return rollback_detail('Company mail pattern is required for this tracking row.')

        append_action = payload.get('append_action')
        if not send_now and not isinstance(append_action, dict):
            row.mailed = False
            row.mail_delivery_status = 'pending'
            row.save(update_fields=['mailed', 'mail_delivery_status', 'updated_at'])
        if send_now:
            row.mailed = False
            row.mail_delivery_status = 'pending'
            row.save()
            command = SendTrackingMailsCommand()
            command._process_tracking_row(
                row,
                include_mailed=False,
                dry_run=False,
                test_mode=False,
                use_ai=False,
                sleep_seconds=0.0,
                clear_schedule=True,
                append_tracking_action=True,
                force_resend=True,
            )
            fresh = Tracking.objects.filter(id=row.id).select_related('job__company', 'resume', 'mail_tracking_record', 'template', 'personalized_template').prefetch_related('selected_hrs', 'actions', 'job__resumes').first()
            return Response(self._serialize_tracking_row(fresh), status=status.HTTP_200_OK)
        if isinstance(append_action, dict):
            action_type = str(append_action.get('type') or '').strip().lower()
            if action_type not in {'fresh', 'followup'}:
                return rollback_detail('Invalid action type.')
            send_mode = str(append_action.get('send_mode') or 'now').strip().lower()
            mode = 'sent' if send_mode == 'now' else 'scheduled'
            action_at = self._to_datetime(append_action.get('action_at')) or timezone.now()
            existing_actions = row.actions.all()
            has_any_action = existing_actions.exists()
            has_fresh_action = existing_actions.filter(action_type='fresh').exists()
            selected_employee_ids = sorted([emp.id for emp in row.selected_hrs.all() if emp.id])
            if not has_any_action:
                action_type = 'fresh'
            elif action_type == 'followup' and not has_fresh_action:
                return rollback_detail('First milestone must be Fresh before any Follow Up.')

            notes = _build_tracking_action_notes(employee_ids=selected_employee_ids)
            last_action = existing_actions.order_by('-created_at').first()
            if last_action and str(last_action.action_type or '') == action_type:
                last_day = timezone.localdate(last_action.action_at) if last_action.action_at else None
                current_day = timezone.localdate(action_at)
                last_meta = _tracking_action_note_meta(last_action.notes)
                last_employee_ids = sorted(last_meta.get('employee_ids') or [])
                if last_day == current_day and (not last_employee_ids or last_employee_ids == selected_employee_ids):
                    next_count = int(last_meta.get('count') or 1) + 1
                    last_action.notes = _build_tracking_action_notes(
                        label=last_meta.get('label') or '',
                        employee_ids=selected_employee_ids,
                        count=next_count,
                    )
                    last_action.action_at = action_at
                    last_action.save(update_fields=['notes', 'action_at', 'updated_at'])
                    row.mail_type = 'followed_up' if action_type == 'followup' else 'fresh'
                    if action_type == 'fresh':
                        row.mailed = True
                        row.save(update_fields=['mail_type', 'mailed', 'updated_at'])
                    else:
                        row.save(update_fields=['mail_type', 'updated_at'])
                    fresh = Tracking.objects.filter(id=row.id).select_related('job__company', 'resume', 'mail_tracking_record', 'template', 'personalized_template').prefetch_related('selected_hrs', 'actions', 'job__resumes').first()
                    return Response(self._serialize_tracking_row(fresh), status=status.HTTP_200_OK)
            if action_type == 'fresh':
                selected_employees = list(row.selected_hrs.all())
                action_history_today = _fresh_action_employee_map_for_day(
                    row,
                    action_at,
                    employee_ids=selected_employee_ids,
                )
                overlap = [action_history_today.get(emp.id) or str(emp.name or '').strip() or f'Employee #{emp.id}' for emp in selected_employees if emp.id in action_history_today]
                if overlap:
                    return rollback_detail(f'Fresh mail already used these employees earlier today in this tracking: {", ".join(overlap)}. Choose fully different employees, use Follow Up, or send tomorrow.')
                same_job_fresh_today = _job_fresh_tracking_employee_map_for_day(
                    row.user,
                    row.job,
                    exclude_tracking_id=row.id,
                    day=timezone.localdate(action_at),
                )
                cross_sent_today = _user_sent_employee_map_for_day(
                    row.user,
                    'fresh',
                    action_at,
                    employee_ids=selected_employee_ids,
                    exclude_tracking_id=row.id,
                )
                overlap = [cross_sent_today.get(emp.id) or str(emp.name or '').strip() or f'Employee #{emp.id}' for emp in selected_employees if emp.id in cross_sent_today]
                if overlap:
                    return rollback_detail(f'Already sent Fresh mail today to: {", ".join(overlap)}. Use follow up, choose different employees, or send tomorrow.')
                sent_today = _tracking_sent_employee_map_for_day(row, 'fresh', action_at)
                overlap = [sent_today.get(emp.id) or str(emp.name or '').strip() or f'Employee #{emp.id}' for emp in selected_employees if emp.id in sent_today]
                if overlap:
                    return rollback_detail(f'Already sent Fresh mail today to: {", ".join(overlap)}. Use different employees today or send tomorrow.')
                if sent_today and selected_employees:
                    notes = _build_tracking_action_notes(label='FD', employee_ids=selected_employee_ids)
                elif last_action and str(last_action.action_type or '') == 'fresh':
                    last_day = timezone.localdate(last_action.action_at) if last_action.action_at else None
                    current_day = timezone.localdate(action_at)
                    last_meta = _tracking_action_note_meta(last_action.notes)
                    last_employee_ids = sorted(last_meta.get('employee_ids') or [])
                    if last_day == current_day and last_employee_ids and last_employee_ids != selected_employee_ids:
                        notes = _build_tracking_action_notes(label='FD', employee_ids=selected_employee_ids)
                elif same_job_fresh_today and selected_employees:
                    notes = _build_tracking_action_notes(label='FD', employee_ids=selected_employee_ids)
            elif action_type == 'followup':
                if last_action and str(last_action.action_type or '') == 'followup':
                    last_day = timezone.localdate(last_action.action_at) if last_action.action_at else None
                    current_day = timezone.localdate(action_at)
                    last_meta = _tracking_action_note_meta(last_action.notes)
                    last_employee_ids = sorted(last_meta.get('employee_ids') or [])
                    if last_day == current_day and last_employee_ids and last_employee_ids != selected_employee_ids:
                        notes = _build_tracking_action_notes(label='FUD', employee_ids=selected_employee_ids)
            TrackingAction.objects.create(
                tracking=row,
                action_type=action_type,
                send_mode=mode,
                action_at=action_at,
                notes=notes,
            )
            row.mail_type = 'followed_up' if action_type == 'followup' else 'fresh'
            if action_type == 'fresh':
                row.mailed = True
            row.save(update_fields=['mail_type', 'mailed', 'updated_at'])

        fresh = Tracking.objects.filter(id=row.id).select_related('job__company', 'resume', 'mail_tracking_record', 'template', 'personalized_template').prefetch_related('selected_hrs', 'actions', 'job__resumes').first()
        return Response(self._serialize_tracking_row(fresh), status=status.HTTP_200_OK)

    def delete(self, request, tracking_id):
        denied = _ensure_write_allowed(request)
        if denied:
            return denied
        try:
            row = self._get_object_any(request, tracking_id)
        except Tracking.DoesNotExist:
            return Response({'detail': 'Tracking row not found.'}, status=status.HTTP_404_NOT_FOUND)
        row.hard_delete()
        return Response(status=status.HTTP_204_NO_CONTENT)


class ApplicationTrackingMailTestView(APIView):
    permission_classes = [IsAuthenticated]

    def _get_row(self, request, tracking_id):
        return (
            Tracking.objects
            .filter(id=tracking_id, profile_id__in=_accessible_profile_ids_for_user(request.user))
            .select_related('job__company', 'resume', 'template', 'personalized_template', 'profile__user')
            .prefetch_related('selected_hrs')
            .first()
        )

    def _generate_previews(self, row, regenerate_options=None):
        command = SendTrackingMailsCommand()
        profile = command._get_profile(row.user_id)
        achievements = command._get_achievements(row)
        company = row.job.company if row.job_id and row.job and row.job.company_id else None
        pattern = str(getattr(company, 'mail_format', '') or '').strip()
        effective_use_ai = command._should_use_ai_for_row(row)
        compose_mode = 'complete_ai' if effective_use_ai else 'template_based'
        employees = [emp for emp in row.selected_hrs.all()]
        previews = []
        for employee in employees:
            to_email = command._resolve_employee_email(employee, pattern)
            subject, body = command._build_mail(
                row,
                employee,
                profile,
                achievements,
                use_ai=effective_use_ai,
            )
            previews.append({
                'employee_id': employee.id,
                'employee_name': str(employee.name or '').strip(),
                'email': to_email,
                'subject': subject,
                'body': body,
                'compose_mode': compose_mode,
            })
        return previews, compose_mode

    def get(self, request, tracking_id):
        row = self._get_row(request, tracking_id)
        if not row:
            return Response({'detail': 'Tracking row not found.'}, status=status.HTTP_404_NOT_FOUND)
        return Response({
            'approved_test_mail_payloads': row.approved_test_mail_payloads if isinstance(row.approved_test_mail_payloads, list) else [],
        }, status=status.HTTP_200_OK)

    def post(self, request, tracking_id):
        row = self._get_row(request, tracking_id)
        if not row:
            return Response({'detail': 'Tracking row not found.'}, status=status.HTTP_404_NOT_FOUND)

        action = str(request.data.get('action') or 'generate').strip().lower()
        if action == 'generate':
            regenerate_options = request.data.get('regenerate_options')
            previews, compose_mode = self._generate_previews(row, regenerate_options=regenerate_options if isinstance(regenerate_options, dict) else None)
            return Response({
                'tracking_id': row.id,
                'previews': previews,
                'compose_mode': compose_mode,
            }, status=status.HTTP_200_OK)

        if action == 'save':
            denied = _ensure_write_allowed(request)
            if denied:
                return denied
            previews = request.data.get('previews')
            if not isinstance(previews, list) or not previews:
                return Response({'detail': 'Preview list is required.'}, status=status.HTTP_400_BAD_REQUEST)
            valid_employee_ids = {employee.id for employee in row.selected_hrs.all()}
            cleaned = []
            for item in previews:
                if not isinstance(item, dict):
                    continue
                subject = str(item.get('subject') or '').strip()
                body = str(item.get('body') or '').strip()
                employee_id = item.get('employee_id')
                try:
                    employee_id = int(employee_id)
                except Exception:
                    continue
                if employee_id not in valid_employee_ids or not subject or not body:
                    continue
                cleaned.append({
                    'employee_id': employee_id,
                    'employee_name': str(item.get('employee_name') or '').strip(),
                    'email': str(item.get('email') or '').strip(),
                    'subject': subject,
                    'body': body,
                    'saved_at': timezone.now().isoformat(),
                })
            if not cleaned:
                return Response({'detail': 'No valid preview rows to save.'}, status=status.HTTP_400_BAD_REQUEST)
            row.approved_test_mail_payloads = cleaned
            row.save(update_fields=['approved_test_mail_payloads', 'updated_at'])
            return Response({'status': 'saved', 'approved_test_mail_payloads': cleaned}, status=status.HTTP_200_OK)

        return Response({'detail': 'Unsupported action.'}, status=status.HTTP_400_BAD_REQUEST)


class CompanyListCreateView(APIView):
    permission_classes = [IsAuthenticated]
    parser_classes = [JSONParser]

    def get(self, request):
        scope = str(request.query_params.get('scope') or '').strip().lower()
        queryset = Company.objects.all() if scope == 'all' else Company.objects.filter(profile_id__in=_accessible_profile_ids_for_user(request.user))
        queryset = queryset.order_by('name')
        ready_for_tracking = str(request.query_params.get('ready_for_tracking') or '').strip().lower() in {'1', 'true', 'yes', 'y'}
        if ready_for_tracking:
            profile_ids = _accessible_profile_ids_for_user(request.user)
            if scope == 'all':
                open_job_company_ids = set(
                    Job.objects.filter(
                        is_closed=False,
                        is_removed=False,
                    ).values_list('company_id', flat=True)
                )
                employee_company_ids = set(
                    Employee.objects.filter(
                        working_mail=True,
                    ).values_list('company_id', flat=True)
                )
            else:
                open_job_company_ids = set(
                    Job.objects.filter(
                        company__profile_id__in=profile_ids,
                        is_closed=False,
                        is_removed=False,
                    ).values_list('company_id', flat=True)
                )
                employee_company_ids = set(
                    Employee.objects.filter(
                        owner_profile_id__in=profile_ids,
                        working_mail=True,
                    ).values_list('company_id', flat=True)
                )
            eligible_company_ids = open_job_company_ids & employee_company_ids
            queryset = queryset.exclude(mail_format='').filter(id__in=eligible_company_ids)
        rows, meta = _paginate_queryset(queryset, request, default_page_size=10, max_page_size=100)
        return Response(
            {
                **meta,
                'results': CompanySerializer(rows, many=True).data,
            },
            status=status.HTTP_200_OK,
        )

    def post(self, request):
        denied = _ensure_write_allowed(request)
        if denied:
            return denied
        workspace_profile = _workspace_profile_for_user(request.user)
        payload = dict(request.data or {})
        company_name = normalize_company_name(payload.get('name'))
        if not company_name:
            return Response({'name': ['Company name is required.']}, status=status.HTTP_400_BAD_REQUEST)
        exists = Company.objects.filter(profile=workspace_profile, name__iexact=company_name).exists()
        if exists:
            return Response({'name': ['This company already exists.']}, status=status.HTTP_400_BAD_REQUEST)
        payload['name'] = company_name
        serializer = CompanySerializer(data=payload)
        if serializer.is_valid():
            created = serializer.save(profile=workspace_profile)
            return Response(CompanySerializer(created).data, status=status.HTTP_201_CREATED)
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)


class CompanyDetailView(APIView):
    permission_classes = [IsAuthenticated]
    parser_classes = [JSONParser]

    def _get_object(self, request, company_id):
        return Company.objects.get(id=company_id, profile_id__in=_accessible_profile_ids_for_user(request.user))

    def put(self, request, company_id):
        if not _can_manage_workspace_fully(request.user):
            return Response({'detail': 'Only owner can update companies.'}, status=status.HTTP_403_FORBIDDEN)
        try:
            row = self._get_object(request, company_id)
        except Company.DoesNotExist:
            return Response({'detail': 'Company not found.'}, status=status.HTTP_404_NOT_FOUND)
        payload = dict(request.data or {})
        if 'name' in payload:
            company_name = normalize_company_name(payload.get('name'))
            if not company_name:
                return Response({'name': ['Company name is required.']}, status=status.HTTP_400_BAD_REQUEST)
            duplicate = Company.objects.filter(
                profile=row.profile,
                name__iexact=company_name,
            ).exclude(id=row.id).exists()
            if duplicate:
                return Response({'name': ['This company already exists.']}, status=status.HTTP_400_BAD_REQUEST)
            payload['name'] = company_name
        serializer = CompanySerializer(row, data=payload, partial=True)
        if serializer.is_valid():
            updated = serializer.save()
            return Response(CompanySerializer(updated).data, status=status.HTTP_200_OK)
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

    def delete(self, request, company_id):
        if not _can_manage_workspace_fully(request.user):
            return Response({'detail': 'Only owner can delete companies.'}, status=status.HTTP_403_FORBIDDEN)
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
        scope = str(request.query_params.get('scope') or '').strip().lower()
        rows = Employee.objects.all() if scope == 'all' else Employee.objects.filter(owner_profile_id__in=_accessible_profile_ids_for_user(request.user))
        if company_id:
            rows = rows.filter(company_id=company_id)
        rows = rows.order_by('name')
        return Response(EmployeeSerializer(rows, many=True).data, status=status.HTTP_200_OK)

    def post(self, request):
        denied = _ensure_write_allowed(request)
        if denied:
            return denied
        payload = dict(request.data or {})
        company_id = payload.get('company')
        if not company_id:
            return Response({'company': ['This field is required.']}, status=status.HTTP_400_BAD_REQUEST)
        workspace_profile = _workspace_profile_for_user(request.user)
        try:
            company = Company.objects.get(id=company_id)
        except Company.DoesNotExist:
            return Response({'company': ['Company not found.']}, status=status.HTTP_400_BAD_REQUEST)
        serializer = EmployeeSerializer(data=payload)
        if serializer.is_valid():
            created = serializer.save(owner_profile=workspace_profile, company=company)
            return Response(EmployeeSerializer(created).data, status=status.HTTP_201_CREATED)
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)


class EmployeeDetailView(APIView):
    permission_classes = [IsAuthenticated]
    parser_classes = [JSONParser]

    def _get_object(self, request, employee_id):
        return Employee.objects.get(id=employee_id)

    def put(self, request, employee_id):
        if not _can_manage_workspace_fully(request.user):
            return Response({'detail': 'Only owner can update employees.'}, status=status.HTTP_403_FORBIDDEN)
        try:
            row = self._get_object(request, employee_id)
        except Employee.DoesNotExist:
            return Response({'detail': 'Employee not found.'}, status=status.HTTP_404_NOT_FOUND)

        payload = dict(request.data or {})
        company_id = str(payload.get('company') or '').strip()
        if 'company' in payload and not company_id:
            payload.pop('company', None)
        if company_id:
            try:
                company = Company.objects.get(id=company_id)
            except Company.DoesNotExist:
                return Response({'company': ['Company not found.']}, status=status.HTTP_400_BAD_REQUEST)
            payload['company'] = company.id
        location_ref_raw = str(payload.get('location_ref') or '').strip()
        if 'location_ref' in payload and not location_ref_raw:
            payload['location_ref'] = None

        serializer = EmployeeSerializer(row, data=payload, partial=True)
        if serializer.is_valid():
            updated = serializer.save()
            return Response(EmployeeSerializer(updated).data, status=status.HTTP_200_OK)
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

    def delete(self, request, employee_id):
        if not _can_manage_workspace_fully(request.user):
            return Response({'detail': 'Only owner can delete employees.'}, status=status.HTTP_403_FORBIDDEN)
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
        scope = str(request.query_params.get('scope') or '').strip().lower()
        rows = Job.objects.all() if scope == 'all' else _accessible_jobs_for_user(request.user)
        rows = rows.select_related('company').prefetch_related('resumes')
        if not include_removed:
            rows = rows.filter(is_removed=False)
        include_closed = str(request.query_params.get('include_closed') or '').strip().lower() in {'1', 'true', 'yes', 'y'}
        if not include_closed:
            rows = rows.filter(is_closed=False)

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
        denied = _ensure_write_allowed(request)
        if denied:
            return denied
        workspace_owner = _workspace_owner_for_user(request.user)
        data = request.data.copy()
        if hasattr(data, '_mutable'):
            data._mutable = True
        company_id = data.get('company')
        new_company_name = data.get('new_company_name')
        try:
            company = resolve_company_for_job(
                workspace_owner,
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
        exists = _workspace_owner_jobs_for_user(request.user).filter(
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
            created = serializer.save(company=company)
            return Response(
                JobSerializer(created, context={'request': request}).data,
                status=status.HTTP_201_CREATED,
            )
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)


class JobDetailView(APIView):
    permission_classes = [IsAuthenticated]
    parser_classes = [JSONParser, FormParser, MultiPartParser]

    def _get_object(self, request, job_id):
        return _accessible_jobs_for_user(request.user).get(id=job_id, is_removed=False)

    def _get_object_any(self, request, job_id):
        return _accessible_jobs_for_user(request.user).get(id=job_id)

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
        if not _can_manage_workspace_fully(request.user):
            return Response({'detail': 'Only owner can update jobs.'}, status=status.HTTP_403_FORBIDDEN)
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
                        row.user,
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
        if not _can_manage_workspace_fully(request.user):
            return Response({'detail': 'Only owner can delete jobs.'}, status=status.HTTP_403_FORBIDDEN)
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


class BulkUploadJobsEmployeesView(APIView):
    permission_classes = [IsAuthenticated]
    parser_classes = [JSONParser, MultiPartParser, FormParser]

    def _extract_payload(self, request):
        uploaded = request.FILES.get('file') or request.FILES.get('json_file') or request.FILES.get('upload')
        if uploaded is not None:
            try:
                raw = uploaded.read().decode('utf-8')
            except Exception as exc:
                raise ValueError(f'Could not read uploaded file: {exc}')
            try:
                parsed = json.loads(raw)
            except Exception as exc:
                raise ValueError(f'Invalid JSON file: {exc}')
            if not isinstance(parsed, dict):
                raise ValueError('JSON file must contain an object with "employees" and/or "jobs".')
            return parsed

        payload = request.data
        if isinstance(payload, dict):
            maybe_json_text = payload.get('payload')
            if isinstance(maybe_json_text, str) and maybe_json_text.strip():
                try:
                    parsed = json.loads(maybe_json_text)
                except Exception as exc:
                    raise ValueError(f'Invalid JSON in payload field: {exc}')
                if not isinstance(parsed, dict):
                    raise ValueError('payload must be a JSON object.')
                return parsed
            return dict(payload)

        raise ValueError('Request must provide JSON body or a JSON file.')

    def _extract_list(self, payload, key):
        value = payload.get(key, [])
        if value is None:
            return []
        if isinstance(value, str):
            text = value.strip()
            if not text:
                return []
            try:
                parsed = json.loads(text)
            except Exception as exc:
                raise ValueError(f'Invalid JSON for "{key}": {exc}')
            if not isinstance(parsed, list):
                raise ValueError(f'"{key}" must be a list.')
            return parsed
        if not isinstance(value, list):
            raise ValueError(f'"{key}" must be a list.')
        return value

    def _map_department(self, value):
        text = str(value or '').strip().lower()
        if text in {'hr', 'human resource', 'human resources', 'talent acquisition', 'recruiting', 'recruiter'}:
            return 'HR'
        if text in {'engineering', 'engineer', 'software', 'developer', 'dev', 'sde', 'tech'}:
            return 'Engineering'
        return 'Other'

    def _get_or_create_company(self, user, raw_name):
        name = normalize_company_name(raw_name)
        if not name:
            raise ValueError('company is required.')
        profile = _workspace_profile_for_user(user)
        existing = Company.objects.filter(profile=profile, name__iexact=name).first()
        if existing:
            return existing, False
        created = Company.objects.create(profile=profile, name=name)
        return created, True

    def _fallback_job_id(self, company_name, role, job_link, row_index):
        base = str(job_link or '').strip() or str(role or '').strip() or f'job-{row_index}'
        slug = re.sub(r'[^a-z0-9]+', '-', base.lower()).strip('-')
        slug = slug[:48] or f'job-{row_index}'
        company_slug = re.sub(r'[^a-z0-9]+', '-', str(company_name or '').lower()).strip('-')
        prefix = company_slug[:18] or 'job'
        return f'{prefix}-{slug}'

    def _upload_employees(self, request, rows):
        summary = {
            'received': len(rows),
            'created': 0,
            'company_created': 0,
            'errors': [],
        }
        for idx, row in enumerate(rows, start=1):
            if not isinstance(row, dict):
                summary['errors'].append({'row': idx, 'error': 'Employee row must be an object.'})
                continue

            first_name = str(row.get('first_name') or row.get('firstname') or '').strip()
            middle_name = str(row.get('middle_name') or row.get('middlename') or '').strip()
            last_name = str(row.get('last_name') or row.get('lastname') or '').strip()
            role = str(row.get('JobRole') or row.get('job_role') or row.get('role') or '').strip()
            location = str(row.get('location') or '').strip()
            company_name = str(row.get('company') or row.get('company_name') or '').strip()
            department_raw = str(row.get('department') or '').strip()
            email = str(row.get('email') or '').strip()
            contact_number = str(row.get('contact_number') or row.get('phone') or '').strip()

            missing = []
            if not first_name:
                missing.append('first_name')
            if not last_name:
                missing.append('last_name')
            if not role:
                missing.append('JobRole')
            if not location:
                missing.append('location')
            if not company_name:
                missing.append('company')
            if not department_raw:
                missing.append('department')
            if missing:
                summary['errors'].append({'row': idx, 'error': f'Missing required fields: {", ".join(missing)}.'})
                continue

            try:
                company, created_company = self._get_or_create_company(request.user, company_name)
                if created_company:
                    summary['company_created'] += 1
            except ValueError as exc:
                summary['errors'].append({'row': idx, 'error': str(exc)})
                continue

            payload = {
                'company': company.id,
                'first_name': first_name,
                'middle_name': middle_name,
                'last_name': last_name,
                'role': role,
                'department': self._map_department(department_raw),
                'location': location,
                'email': email,
                'contact_number': contact_number,
            }
            serializer = EmployeeSerializer(data=payload)
            if not serializer.is_valid():
                summary['errors'].append({'row': idx, 'error': serializer.errors})
                continue
            serializer.save(owner_profile=_workspace_profile_for_user(request.user), company=company)
            summary['created'] += 1

        return summary

    def _upload_jobs(self, request, rows):
        summary = {
            'received': len(rows),
            'created': 0,
            'company_created': 0,
            'duplicate_in_file': 0,
            'duplicate_in_db': 0,
            'errors': [],
        }
        seen_company_job = set()
        for idx, row in enumerate(rows, start=1):
            if not isinstance(row, dict):
                summary['errors'].append({'row': idx, 'error': 'Job row must be an object.'})
                continue

            company_name = str(row.get('company') or row.get('company_name') or '').strip()
            job_id = str(row.get('job_id') or row.get('jobId') or '').strip()
            job_link = str(row.get('job_link') or row.get('job_url') or row.get('link') or '').strip()
            role = str(row.get('role') or '').strip() or 'Software Engineer'
            if not job_id:
                job_id = self._fallback_job_id(company_name, role, job_link, idx)

            missing = []
            if not company_name:
                missing.append('company')
            if not job_link:
                missing.append('job_link')
            if missing:
                summary['errors'].append({'row': idx, 'error': f'Missing required fields: {", ".join(missing)}.'})
                continue

            try:
                company, created_company = self._get_or_create_company(request.user, company_name)
                if created_company:
                    summary['company_created'] += 1
            except ValueError as exc:
                summary['errors'].append({'row': idx, 'error': str(exc)})
                continue

            key = (company.id, job_id.lower())
            if key in seen_company_job:
                summary['duplicate_in_file'] += 1
                summary['errors'].append(
                    {'row': idx, 'error': f'Duplicate company + job_id in file: {company.name} + {job_id}.'}
                )
                continue
            seen_company_job.add(key)

            exists = Job.objects.filter(
                company=company,
                job_id__iexact=job_id,
                is_removed=False,
            ).exists()
            if exists:
                summary['duplicate_in_db'] += 1
                summary['errors'].append(
                    {'row': idx, 'error': f'Duplicate company + job_id in DB: {company.name} + {job_id}.'}
                )
                continue

            payload = {
                'company': company.id,
                'job_id': job_id,
                'job_link': job_link,
                'role': role,
            }
            serializer = JobSerializer(data=payload, context={'request': request})
            if not serializer.is_valid():
                summary['errors'].append({'row': idx, 'error': serializer.errors})
                continue
            serializer.save(company=company)
            summary['created'] += 1
        return summary

    def post(self, request):
        denied = _ensure_write_allowed(request)
        if denied:
            return denied
        try:
            payload = self._extract_payload(request)
            employees_rows = self._extract_list(payload, 'employees')
            jobs_rows = self._extract_list(payload, 'jobs')
        except ValueError as exc:
            return Response({'detail': str(exc)}, status=status.HTTP_400_BAD_REQUEST)

        if not employees_rows and not jobs_rows:
            return Response(
                {'detail': 'Provide at least one of "employees" or "jobs".'},
                status=status.HTTP_400_BAD_REQUEST,
            )

        employees_summary = self._upload_employees(request, employees_rows) if employees_rows else {
            'received': 0,
            'created': 0,
            'company_created': 0,
            'errors': [],
        }
        jobs_summary = self._upload_jobs(request, jobs_rows) if jobs_rows else {
            'received': 0,
            'created': 0,
            'company_created': 0,
            'duplicate_in_file': 0,
            'duplicate_in_db': 0,
            'errors': [],
        }
        

        has_any_errors = bool(employees_summary.get('errors') or jobs_summary.get('errors'))
        response_status = status.HTTP_207_MULTI_STATUS if has_any_errors else status.HTTP_201_CREATED
        return Response(
            {
                'message': 'Bulk upload processed.',
                'employees': employees_summary,
                'jobs': jobs_summary,
            },
            status=response_status,
        )


class BulkUploadEmployeesView(BulkUploadJobsEmployeesView):
    permission_classes = [IsAuthenticated]
    parser_classes = [JSONParser, MultiPartParser, FormParser]

    def post(self, request):
        denied = _ensure_write_allowed(request)
        if denied:
            return denied
        try:
            payload = self._extract_payload(request)
            employees_rows = self._extract_list(payload, 'employees')
        except ValueError as exc:
            return Response({'detail': str(exc)}, status=status.HTTP_400_BAD_REQUEST)

        if not employees_rows:
            return Response(
                {'detail': 'Provide "employees" list for employee bulk upload.'},
                status=status.HTTP_400_BAD_REQUEST,
            )

        employees_summary = self._upload_employees(request, employees_rows)
        has_errors = bool(employees_summary.get('errors'))
        response_status = status.HTTP_207_MULTI_STATUS if has_errors else status.HTTP_201_CREATED
        return Response(
            {
                'message': 'Employee bulk upload processed.',
                'employees': employees_summary,
            },
            status=response_status,
        )


class BulkUploadJobsView(BulkUploadJobsEmployeesView):
    permission_classes = [IsAuthenticated]
    parser_classes = [JSONParser, MultiPartParser, FormParser]

    def post(self, request):
        denied = _ensure_write_allowed(request)
        if denied:
            return denied
        try:
            payload = self._extract_payload(request)
            jobs_rows = self._extract_list(payload, 'jobs')
        except ValueError as exc:
            return Response({'detail': str(exc)}, status=status.HTTP_400_BAD_REQUEST)

        if not jobs_rows:
            return Response(
                {'detail': 'Provide "jobs" list for job bulk upload.'},
                status=status.HTTP_400_BAD_REQUEST,
            )

        jobs_summary = self._upload_jobs(request, jobs_rows)
        has_errors = bool(jobs_summary.get('errors'))
        response_status = status.HTTP_207_MULTI_STATUS if has_errors else status.HTTP_201_CREATED
        return Response(
            {
                'message': 'Job bulk upload processed.',
                'jobs': jobs_summary,
            },
            status=response_status,
        )


class ExtensionFormMetaView(APIView):
    permission_classes = [AllowAny]
    parser_classes = [JSONParser]

    def get(self, request):
        actor = _resolve_extension_user(request)
        posted_date_options = [
            {'value': 'today', 'label': 'Today'},
            {'value': 'yesterday', 'label': 'Yesterday'},
            {'value': 'last_3_days', 'label': 'Last 3 Days'},
            {'value': 'last_7_days', 'label': 'Last 7 Days'},
            {'value': 'custom', 'label': 'Posted Date'},
        ]
        location_rows = Location.objects.all().order_by('name')[:10]
        return Response(
            {
                'department_options': [
                    {'value': 'HR', 'label': 'HR'},
                    {'value': 'Engineering', 'label': 'Engineering'},
                    {'value': 'Other', 'label': 'Other'},
                ],
                'location_options': [
                    {'value': str(row.name or '').strip(), 'label': str(row.name or '').strip()}
                    for row in location_rows
                    if str(row.name or '').strip()
                ],
                'posted_date_options': posted_date_options,
                'workspace_role': (
                    'owner'
                    if actor and _can_manage_workspace_fully(actor)
                    else 'member'
                    if actor
                    else 'guest'
                ),
            },
            status=status.HTTP_200_OK,
        )


class ExtensionCompanySearchView(APIView):
    permission_classes = [AllowAny]
    parser_classes = [JSONParser]

    def get(self, request):
        actor = _resolve_extension_user(request)
        if not actor:
            return Response({'detail': 'Please login in web app'}, status=status.HTTP_401_UNAUTHORIZED)
        q = str(request.query_params.get('q') or '').strip()
        rows = Company.objects.filter(profile_id__in=_accessible_profile_ids_for_user(actor))
        if q:
            rows = rows.filter(name__icontains=q)
        rows = rows.order_by('name')[:50]
        return Response(
            {
                'results': [
                    {
                        'id': row.id,
                        'name': row.name,
                        'mail_format': str(row.mail_format or '').strip(),
                    }
                    for row in rows
                ]
            },
            status=status.HTTP_200_OK,
        )


class ExtensionJobCreateView(APIView):
    permission_classes = [AllowAny]
    parser_classes = [JSONParser]

    def _to_date(self, value):
        raw = str(value or '').strip()
        if not raw:
            return None
        try:
            return datetime.fromisoformat(raw[:10]).date()
        except Exception:
            return None

    def _resolve_posted_date(self, payload):
        custom = self._to_date(payload.get('posted_date') or payload.get('date_of_posting'))
        if custom:
            return custom

        option = str(payload.get('posted_date_option') or '').strip().lower()
        today = timezone.localdate()
        if option == 'today':
            return today
        if option == 'yesterday':
            return today - timedelta(days=1)
        if option == 'last_3_days':
            return today - timedelta(days=3)
        if option == 'last_7_days':
            return today - timedelta(days=7)
        return None

    def _resolve_company(self, user, payload, allow_create=True):
        profile = _workspace_profile_for_user(user)
        company_id = payload.get('company_id') or payload.get('company')
        if company_id:
            try:
                return Company.objects.get(id=company_id, profile=profile), ''
            except Company.DoesNotExist:
                return None, 'Company not found.'

        company_name = normalize_company_name(payload.get('company_name') or payload.get('company'))
        if not company_name:
            return None, 'company_name is required when company_id is not provided.'
        company = Company.objects.filter(profile=profile, name__iexact=company_name).first()
        if company:
            return company, ''
        if not allow_create:
            return None, 'Limited user must choose an existing company.'
        company = Company.objects.create(profile=profile, name=company_name)
        return company, ''

    def post(self, request):
        payload = request.data or {}
        actor = _resolve_extension_user(request)
        if not actor:
            return Response({'detail': 'Please login in web app'}, status=status.HTTP_401_UNAUTHORIZED)
        if _is_read_only_user(actor):
            return Response({'detail': 'Read-only users cannot create jobs.'}, status=status.HTTP_403_FORBIDDEN)
        workspace_owner = _workspace_owner_for_user(actor)

        company, company_error = self._resolve_company(
            workspace_owner,
            payload,
            allow_create=True,
        )
        if company_error:
            return Response({'detail': company_error}, status=status.HTTP_400_BAD_REQUEST)

        mail_pattern = str(payload.get('mail_pattern') or payload.get('company_mail_pattern') or '').strip()
        if mail_pattern and str(company.mail_format or '').strip() != mail_pattern:
            company.mail_format = mail_pattern
            company.save(update_fields=['mail_format', 'updated_at'])

        job_id_value = str(payload.get('job_id') or '').strip()
        role_value = str(payload.get('role') or '').strip()
        job_link_value = str(payload.get('job_link') or '').strip()
        jd_value = str(payload.get('jd') or payload.get('jd_text') or '').strip()
        posted_date = self._resolve_posted_date(payload)
        applied_raw = str(payload.get('applied') or '').strip().lower()
        is_applied = applied_raw in {'yes', 'y', 'true', '1'}
        applied_at = timezone.localdate() if is_applied else None

        missing = []
        if not job_id_value:
            missing.append('job_id')
        if not role_value:
            missing.append('role')
        if not job_link_value:
            missing.append('job_link')
        if missing:
            return Response(
                {'detail': f'Missing required fields: {", ".join(missing)}.'},
                status=status.HTTP_400_BAD_REQUEST,
            )

        duplicate = Job.objects.filter(
            company=company,
            job_id__iexact=job_id_value,
            is_removed=False,
        ).exists()
        if duplicate:
            return Response(
                {'detail': 'This company + job_id already exists.'},
                status=status.HTTP_400_BAD_REQUEST,
            )

        created = Job.objects.create(
            company=company,
            job_id=job_id_value,
            role=role_value,
            job_link=job_link_value,
            jd_text=jd_value,
            date_of_posting=posted_date,
            applied_at=applied_at,
        )
        return Response(
            {
                'message': 'Job created.',
                'job': JobSerializer(created, context={'request': request}).data,
            },
            status=status.HTTP_201_CREATED,
        )


class ExtensionEmployeeCreateView(APIView):
    permission_classes = [AllowAny]
    parser_classes = [JSONParser]

    def _map_department(self, value):
        text = str(value or '').strip().lower()
        if text in {'hr', 'human resource', 'human resources', 'talent', 'recruiting', 'recruiter'}:
            return 'HR'
        if text in {'engineering', 'engineer', 'developer', 'sde', 'software', 'dev'}:
            return 'Engineering'
        return 'Other'

    def _normalize_profile_url(self, value):
        raw = str(value or '').strip()
        if not raw:
            return ''
        cleaned = raw.split('#', 1)[0].split('?', 1)[0].rstrip('/')
        return cleaned.lower()

    def _resolve_company(self, user, payload, allow_create=True):
        profile = _workspace_profile_for_user(user)
        company_id = payload.get('company_id') or payload.get('company')
        if company_id:
            try:
                return Company.objects.get(id=company_id, profile=profile), ''
            except Company.DoesNotExist:
                return None, 'Company not found.'

        company_name = normalize_company_name(payload.get('company_name') or payload.get('company'))
        if not company_name:
            return None, 'company_name is required when company_id is not provided.'
        company = Company.objects.filter(profile=profile, name__iexact=company_name).first()
        if company:
            return company, ''
        if not allow_create:
            return None, 'Limited user must choose an existing company.'
        company = Company.objects.create(profile=profile, name=company_name)
        return company, ''

    def post(self, request):
        payload = dict(request.data or {})
        actor = _resolve_extension_user(request)
        if not actor:
            return Response({'detail': 'Please login in web app'}, status=status.HTTP_401_UNAUTHORIZED)
        if _is_read_only_user(actor):
            return Response({'detail': 'Read-only users cannot create employees.'}, status=status.HTTP_403_FORBIDDEN)
        workspace_owner = _workspace_owner_for_user(actor)

        company, company_error = self._resolve_company(
            workspace_owner,
            payload,
            allow_create=True,
        )
        if company_error:
            return Response({'detail': company_error}, status=status.HTTP_400_BAD_REQUEST)

        first_name = str(payload.get('first_name') or '').strip()
        middle_name = str(payload.get('middle_name') or '').strip()
        last_name = str(payload.get('last_name') or '').strip()
        plain_name = str(payload.get('name') or '').strip()
        raw_department = str(payload.get('department') or '').strip()
        department = self._map_department(raw_department)
        role = str(payload.get('JobRole') or payload.get('job_role') or payload.get('role') or '').strip()
        linkedin_url = str(payload.get('linkedin_url') or payload.get('profile') or '').strip()
        contact_number = str(payload.get('contact_number') or payload.get('contact_num') or '').strip()
        email = str(payload.get('email') or '').strip()
        location = str(payload.get('location') or '').strip()
        about = str(payload.get('about') or '').strip()

        missing = []
        if not role:
            missing.append('JobRole')
        if not raw_department:
            missing.append('department')
        if not (plain_name or first_name or last_name):
            missing.append('name/first_name/last_name')
        if not linkedin_url:
            missing.append('linkedin_url')
        if not about:
            missing.append('about')
        if not location:
            missing.append('location')
        if missing:
            return Response(
                {'detail': f'Missing required fields: {", ".join(missing)}.'},
                status=status.HTTP_400_BAD_REQUEST,
            )

        linkedin_key = self._normalize_profile_url(linkedin_url)
        duplicate = False
        owner_profile = _workspace_profile_for_user(workspace_owner)
        for row in Employee.objects.filter(owner_profile=owner_profile, company=company).only('id', 'profile'):
            if self._normalize_profile_url(row.profile) == linkedin_key:
                duplicate = True
                break
        if duplicate:
            return Response(
                {'detail': 'This company + LinkedIn URL already exists.'},
                status=status.HTTP_400_BAD_REQUEST,
            )

        serializer_payload = {
            'company': company.id,
            'name': plain_name,
            'first_name': first_name,
            'middle_name': middle_name,
            'last_name': last_name,
            'department': department,
            'role': role,
            'profile': linkedin_url,
            'contact_number': contact_number,
            'email': email,
            'about': about,
            'location': location,
        }
        serializer = EmployeeSerializer(data=serializer_payload)
        if not serializer.is_valid():
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

        created = serializer.save(owner_profile=owner_profile, company=company)
        return Response(
            {
                'message': 'Employee created.',
                'employee': EmployeeSerializer(created).data,
            },
            status=status.HTTP_201_CREATED,
        )
