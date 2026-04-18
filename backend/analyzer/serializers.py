from django.contrib.auth.models import Group, User
from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError as DjangoValidationError
from django.core.validators import URLValidator, validate_email
from rest_framework import serializers

from .models import (
    Resume,
    MailTracking,
    Company,
    Employee,
    Job,
    Location,
    UserProfile,
    ProfilePanel,
    Template,
    SubjectTemplate,
    Interview,
)

_url_validator = URLValidator()


def _normalize_url(value):
    raw = str(value or '').strip()
    if not raw:
        return ''
    normalized = raw if raw.lower().startswith(('http://', 'https://')) else f'https://{raw}'
    _url_validator(normalized)
    return normalized


def _normalize_email(value):
    raw = str(value or '').strip().lower()
    if not raw:
        return ''
    validate_email(raw)
    return raw


def _normalize_text(value):
    return str(value or '').strip()


class SignupSerializer(serializers.ModelSerializer):
    password = serializers.CharField(write_only=True)

    class Meta:
        model = User
        fields = ['username', 'email', 'password']

    def validate_username(self, value):
        normalized = str(value or '').strip()
        if not normalized:
            raise serializers.ValidationError('Username is required.')
        return normalized

    def validate_email(self, value):
        return str(value or '').strip().lower()

    def validate_password(self, value):
        try:
            validate_password(value)
        except DjangoValidationError as exc:
            raise serializers.ValidationError(list(exc.messages)) from exc
        return value

    def create(self, validated_data):
        user = User.objects.create_user(
            username=validated_data['username'],
            email=validated_data.get('email', ''),
            password=validated_data['password'],
        )
        admin_group = Group.objects.filter(name__iexact='admin').first()
        if admin_group is not None:
            user.groups.add(admin_group)
        return user


class ResumeSerializer(serializers.ModelSerializer):
    job_id = serializers.IntegerField(source='job.id', read_only=True)
    job_label = serializers.SerializerMethodField()
    source_resume_id = serializers.IntegerField(source='source_resume.id', read_only=True)
    source_resume_title = serializers.SerializerMethodField()
    is_tailored = serializers.BooleanField(required=False)

    def get_job_label(self, obj):
        if not getattr(obj, 'job_id', None) or not obj.job:
            return ''
        company_name = obj.job.company.name if getattr(obj.job, 'company_id', None) else ''
        parts = [str(obj.job.job_id or '').strip(), str(company_name or '').strip(), str(obj.job.role or '').strip()]
        return ' | '.join([part for part in parts if part])

    def get_source_resume_title(self, obj):
        if not getattr(obj, 'source_resume_id', None) or not obj.source_resume:
            return ''
        return str(obj.source_resume.title or '').strip()

    class Meta:
        model = Resume
        fields = [
            'id',
            'title',
            'original_text',
            'optimized_text',
            'builder_data',
            'ats_pdf_path',
            'is_default',
            'is_tailored',
            'job',
            'job_id',
            'job_label',
            'source_resume',
            'source_resume_id',
            'source_resume_title',
            'status',
            'created_at',
            'updated_at',
        ]
        read_only_fields = ['id', 'optimized_text', 'status', 'ats_pdf_path', 'job_id', 'job_label', 'source_resume_id', 'source_resume_title', 'created_at', 'updated_at']


class TailoredResumeSerializer(serializers.ModelSerializer):
    name = serializers.SerializerMethodField()
    job_id = serializers.IntegerField(source='job.id', read_only=True)
    job_label = serializers.SerializerMethodField()
    resume_id = serializers.IntegerField(source='source_resume.id', read_only=True)
    resume_title = serializers.SerializerMethodField()

    def get_name(self, obj):
        return str(obj.title or '').strip()

    def get_job_label(self, obj):
        if not obj.job_id or not obj.job:
            return ''
        return f"{obj.job.job_id} - {obj.job.role}"

    def get_resume_title(self, obj):
        if not obj.source_resume_id or not obj.source_resume:
            return ''
        return obj.source_resume.title

    class Meta:
        model = Resume
        fields = [
            'id',
            'name',
            'title',
            'builder_data',
            'ats_pdf_path',
            'job',
            'job_id',
            'job_label',
            'source_resume',
            'resume_id',
            'resume_title',
            'created_at',
            'updated_at',
        ]
        read_only_fields = ['id', 'ats_pdf_path', 'job_id', 'job_label', 'resume_id', 'resume_title', 'created_at', 'updated_at']


class MailTrackingSerializer(serializers.ModelSerializer):
    tracking_id = serializers.IntegerField(source='tracking.id', read_only=True)
    employee_id = serializers.IntegerField(source='employee.id', read_only=True)
    employee_name = serializers.SerializerMethodField()
    company_name = serializers.SerializerMethodField()
    job_id = serializers.SerializerMethodField()
    applied_date = serializers.SerializerMethodField()
    posting_date = serializers.SerializerMethodField()
    is_open = serializers.SerializerMethodField()
    available_hrs = serializers.SerializerMethodField()
    selected_hrs = serializers.SerializerMethodField()

    def _compat_payload(self, obj):
        payload = obj.mail_history
        if isinstance(payload, dict):
            return payload
        return {}

    def get_company_name(self, obj):
        compat = self._compat_payload(obj)
        if compat.get('company_name'):
            return compat.get('company_name')
        if getattr(obj, 'tracking', None) and getattr(obj.tracking, 'job', None) and getattr(obj.tracking.job, 'company', None):
            return obj.tracking.job.company.name
        return ''

    def get_job_id(self, obj):
        compat = self._compat_payload(obj)
        if compat.get('job_id'):
            return compat.get('job_id')
        if getattr(obj, 'tracking', None) and getattr(obj.tracking, 'job', None):
            return obj.tracking.job.job_id
        return ''

    def get_applied_date(self, obj):
        compat = self._compat_payload(obj)
        if compat.get('applied_date'):
            return compat.get('applied_date')
        if getattr(obj, 'tracking', None) and getattr(obj.tracking, 'job', None) and obj.tracking.job.applied_at:
            return obj.tracking.job.applied_at.isoformat()
        return None

    def get_posting_date(self, obj):
        compat = self._compat_payload(obj)
        if compat.get('posting_date'):
            return compat.get('posting_date')
        if getattr(obj, 'tracking', None) and getattr(obj.tracking, 'job', None) and obj.tracking.job.date_of_posting:
            return obj.tracking.job.date_of_posting.isoformat()
        return None

    def get_is_open(self, obj):
        compat = self._compat_payload(obj)
        if 'is_open' in compat:
            return bool(compat.get('is_open'))
        if getattr(obj, 'tracking', None) and getattr(obj.tracking, 'job', None):
            return not bool(obj.tracking.job.is_closed)
        return True

    def get_available_hrs(self, obj):
        compat = self._compat_payload(obj)
        value = compat.get('available_hrs')
        return value if isinstance(value, list) else []

    def get_selected_hrs(self, obj):
        compat = self._compat_payload(obj)
        value = compat.get('selected_hrs')
        return value if isinstance(value, list) else []

    def get_employee_name(self, obj):
        if getattr(obj, 'employee', None):
            return str(obj.employee.name or '')
        compat = self._compat_payload(obj)
        return str(compat.get('employee_name') or '')

    class Meta:
        model = MailTracking
        fields = [
            'id',
            'tracking',
            'tracking_id',
            'employee_id',
            'employee_name',
            'company_name',
            'job_id',
            'applied_date',
            'posting_date',
            'is_open',
            'available_hrs',
            'selected_hrs',
            'mail_history',
            'created_at',
            'updated_at',
        ]
        read_only_fields = ['id', 'created_at', 'updated_at']

    def _extract_compat_fields(self, validated_data):
        compat_keys = ['company_name', 'job_id', 'applied_date', 'posting_date', 'is_open', 'available_hrs', 'selected_hrs']
        compat = {}
        for key in compat_keys:
            if key in self.initial_data:
                compat[key] = self.initial_data.get(key)
        return compat

    def create(self, validated_data):
        compat = self._extract_compat_fields(validated_data)
        created = super().create(validated_data)
        if compat:
            created.mail_history = compat
            created.save(update_fields=['mail_history', 'updated_at'])
        return created

    def update(self, instance, validated_data):
        compat = self._extract_compat_fields(validated_data)
        updated = super().update(instance, validated_data)
        if compat:
            existing = updated.mail_history if isinstance(updated.mail_history, dict) else {}
            existing.update(compat)
            updated.mail_history = existing
            updated.save(update_fields=['mail_history', 'updated_at'])
        return updated


class EmployeeSerializer(serializers.ModelSerializer):
    company_name = serializers.SerializerMethodField()
    location_name = serializers.SerializerMethodField()
    # Backward-compatible API keys for existing frontend payload/response shape.
    role = serializers.CharField(source='JobRole', required=True, allow_blank=False)
    personalized_template_helpful = serializers.CharField(source='helpful', required=False, allow_blank=True)
    name = serializers.CharField(required=False, allow_blank=True)
    first_name = serializers.CharField(required=False, allow_blank=True)
    middle_name = serializers.CharField(required=False, allow_blank=True)
    last_name = serializers.CharField(required=False, allow_blank=True)

    def to_internal_value(self, data):
        payload = data.copy() if hasattr(data, 'copy') else dict(data or {})
        if 'company' in payload and str(payload.get('company') or '').strip() == '':
            if self.instance is not None:
                payload.pop('company', None)
            else:
                payload['company'] = None
        if 'location_ref' in payload and str(payload.get('location_ref') or '').strip() == '':
            payload['location_ref'] = None
        return super().to_internal_value(payload)

    def get_company_name(self, obj):
        return obj.company.name if getattr(obj, 'company', None) else ''

    def get_location_name(self, obj):
        if getattr(obj, 'location_ref_id', None) and getattr(obj, 'location_ref', None):
            return obj.location_ref.name
        return str(getattr(obj, 'location', '') or '')

    def validate_email(self, value):
        return _normalize_email(value)

    def validate(self, attrs):
        first_name = str(attrs.get('first_name') or '').strip()
        middle_name = str(attrs.get('middle_name') or '').strip()
        last_name = str(attrs.get('last_name') or '').strip()
        name = str(attrs.get('name') or '').strip()

        if first_name or middle_name or last_name:
            merged = ' '.join(part for part in [first_name, middle_name, last_name] if part).strip()
            attrs['name'] = merged
            attrs['first_name'] = first_name
            attrs['middle_name'] = middle_name
            attrs['last_name'] = last_name
        elif name:
            attrs['name'] = name
        elif not (self.instance and str(getattr(self.instance, 'name', '') or '').strip()):
            raise serializers.ValidationError({'name': ['Provide name or first/middle/last name.']})

        role_value = str(attrs.get('JobRole') or getattr(self.instance, 'JobRole', '') or '').strip()
        if not role_value:
            raise serializers.ValidationError({'role': ['This field is required.']})
        attrs['JobRole'] = role_value

        department_value = str(attrs.get('department') or getattr(self.instance, 'department', '') or '').strip()
        if not department_value:
            raise serializers.ValidationError({'department': ['This field is required.']})
        attrs['department'] = department_value

        company = attrs.get('company') or getattr(self.instance, 'company', None)
        normalized_name = str(attrs.get('name') or getattr(self.instance, 'name', '') or '').strip()
        normalized_email = str(attrs.get('email') or getattr(self.instance, 'email', '') or '').strip().lower()
        if company is not None and normalized_name and normalized_email:
            duplicate_rows = Employee.objects.filter(
                company=company,
                name__iexact=normalized_name,
                email__iexact=normalized_email,
            )
            if self.instance is not None:
                duplicate_rows = duplicate_rows.exclude(id=self.instance.id)
            if duplicate_rows.exists():
                raise serializers.ValidationError({
                    'email': ['An employee with this name and email already exists for this company.']
                })

        return attrs

    class Meta:
        model = Employee
        fields = [
            'id',
            'name',
            'first_name',
            'middle_name',
            'last_name',
            'company',
            'company_name',
            'role',
            'department',
            'email',
            'working_mail',
            'contact_number',
            'about',
            'personalized_template_helpful',
            'personalized_template',
            'profile',
            'location',
            'location_ref',
            'location_name',
            'created_at',
            'updated_at',
        ]
        read_only_fields = ['id', 'company_name', 'created_at', 'updated_at']


class CompanySerializer(serializers.ModelSerializer):
    career_url = serializers.CharField(required=False, allow_blank=True)
    workday_domain_url = serializers.CharField(required=False, allow_blank=True)

    def validate_name(self, value):
        text = str(value or '').strip()
        if not text:
            raise serializers.ValidationError('Company name is required.')
        return text

    def validate_mail_format(self, value):
        return str(value or '').strip()

    def validate_career_url(self, value):
        return _normalize_url(value)

    def validate_workday_domain_url(self, value):
        return _normalize_url(value)

    class Meta:
        model = Company
        fields = [
            'id',
            'name',
            'mail_format',
            'career_url',
            'workday_domain_url',
            'created_at',
            'updated_at',
        ]
        read_only_fields = ['id', 'created_at', 'updated_at']


class JobSerializer(serializers.ModelSerializer):
    job_link = serializers.CharField(required=False, allow_blank=True)
    company_name = serializers.SerializerMethodField()
    has_tailored_resume = serializers.SerializerMethodField()
    tailored_resumes = serializers.SerializerMethodField()
    associated_resumes = serializers.SerializerMethodField()
    resume_preview = serializers.SerializerMethodField()
    applied = serializers.SerializerMethodField()

    def get_company_name(self, obj):
        return obj.company.name if getattr(obj, 'company', None) else ''

    def get_has_tailored_resume(self, obj):
        return obj.resumes.filter(is_tailored=True).exists()

    def get_tailored_resumes(self, obj):
        rows = obj.resumes.filter(is_tailored=True).order_by('created_at', 'id')
        return [
            {
                'id': item.id,
                'name': str(item.title or '').strip() or f'Tailored Resume #{item.id}',
            }
            for item in rows
        ]

    def get_associated_resumes(self, obj):
        rows = obj.resumes.order_by('-updated_at', '-created_at', '-id')
        return [
            {
                'id': item.id,
                'title': str(item.title or '').strip() or f'Resume #{item.id}',
                'is_tailored': bool(item.is_tailored),
            }
            for item in rows
        ]

    def get_resume_preview(self, obj):
        preview_resume = (
            obj.resumes
            .order_by('-is_tailored', '-updated_at', '-created_at', '-id')
            .first()
        )
        if not preview_resume:
            return None
        data = preview_resume.builder_data or {}
        if not isinstance(data, dict) or not data:
            return None
        return {
            'id': preview_resume.id,
            'title': str(preview_resume.title or '').strip() or f'Resume #{preview_resume.id}',
            'builder_data': data,
        }

    def get_applied(self, obj):
        return obj.applied_at is not None

    def validate_job_id(self, value):
        text = str(value or '').strip()
        if not text:
            raise serializers.ValidationError('Job ID is required.')
        return text

    def validate_role(self, value):
        text = str(value or '').strip()
        if not text:
            raise serializers.ValidationError('Role is required.')
        return text

    def validate_job_link(self, value):
        return _normalize_url(value)

    class Meta:
        model = Job
        fields = [
            'id',
            'job_id',
            'role',
            'job_link',
            'has_tailored_resume',
            'tailored_resumes',
            'associated_resumes',
            'resume_preview',
            'company',
            'company_name',
            'jd_text',
            'date_of_posting',
            'applied_at',
            'applied',
            'is_closed',
            'is_removed',
            'created_at',
            'updated_at',
        ]
        read_only_fields = [
            'id',
            'company_name',
            'has_tailored_resume',
            'applied',
            'created_at',
            'updated_at',
        ]


# Backward-compatible alias used by existing views/endpoints.
ApplicationTrackingSerializer = MailTrackingSerializer


class UserProfileSerializer(serializers.ModelSerializer):
    email = serializers.CharField(required=False, allow_blank=True)
    linkedin_url = serializers.CharField(required=False, allow_blank=True)
    github_url = serializers.CharField(required=False, allow_blank=True)
    portfolio_url = serializers.CharField(required=False, allow_blank=True)
    resume_link = serializers.CharField(required=False, allow_blank=True)
    smtp_host = serializers.CharField(required=False, allow_blank=True)
    smtp_port = serializers.IntegerField(required=False, allow_null=True, min_value=1, max_value=65535)
    smtp_user = serializers.CharField(required=False, allow_blank=True)
    smtp_password = serializers.CharField(required=False, allow_blank=True)
    smtp_use_tls = serializers.BooleanField(required=False)
    smtp_from_email = serializers.CharField(required=False, allow_blank=True)
    imap_host = serializers.CharField(required=False, allow_blank=True)
    imap_port = serializers.IntegerField(required=False, allow_null=True, min_value=1, max_value=65535)
    imap_user = serializers.CharField(required=False, allow_blank=True)
    imap_password = serializers.CharField(required=False, allow_blank=True)
    imap_folder = serializers.CharField(required=False, allow_blank=True)
    openai_api_key = serializers.CharField(required=False, allow_blank=True)
    openai_model = serializers.CharField(required=False, allow_blank=True)
    ai_task_instructions = serializers.CharField(required=False, allow_blank=True)
    location_name = serializers.SerializerMethodField()
    preferred_location_refs = serializers.PrimaryKeyRelatedField(
        source='preferred_locations',
        many=True,
        queryset=Location.objects.all(),
        required=False,
    )
    preferred_location_names = serializers.SerializerMethodField()

    def get_location_name(self, obj):
        if getattr(obj, 'location_ref_id', None) and getattr(obj, 'location_ref', None):
            return obj.location_ref.name
        return str(getattr(obj, 'location', '') or '')

    def get_preferred_location_names(self, obj):
        return [str(item.name or '') for item in obj.preferred_locations.all().order_by('name')]

    def validate_email(self, value):
        return _normalize_email(value)

    def validate_linkedin_url(self, value):
        return _normalize_url(value)

    def validate_github_url(self, value):
        return _normalize_url(value)

    def validate_portfolio_url(self, value):
        return _normalize_url(value)

    def validate_resume_link(self, value):
        return _normalize_url(value)

    def validate_full_name(self, value):
        return _normalize_text(value)

    def validate_contact_number(self, value):
        return _normalize_text(value)

    def validate_current_employer(self, value):
        return _normalize_text(value)

    def validate_years_of_experience(self, value):
        return _normalize_text(value)

    def validate_location(self, value):
        return _normalize_text(value)

    def validate_summary(self, value):
        return _normalize_text(value)

    def validate_smtp_host(self, value):
        return _normalize_text(value)

    def validate_smtp_user(self, value):
        return _normalize_text(value)

    def validate_smtp_password(self, value):
        return str(value or '').strip()

    def validate_smtp_from_email(self, value):
        return _normalize_email(value)

    def validate_imap_host(self, value):
        return _normalize_text(value)

    def validate_imap_user(self, value):
        return _normalize_text(value)

    def validate_imap_password(self, value):
        return str(value or '').strip()

    def validate_imap_folder(self, value):
        return _normalize_text(value)

    def validate_openai_api_key(self, value):
        return str(value or '').strip()

    def validate_openai_model(self, value):
        return _normalize_text(value)

    def validate_ai_task_instructions(self, value):
        return str(value or '').strip()

    def validate_role(self, value):
        text = _normalize_text(value).lower()
        allowed = {choice[0] for choice in UserProfile.ROLE_CHOICES}
        if text not in allowed:
            raise serializers.ValidationError('Role must be superadmin, admin, or read_only.')
        return text

    class Meta:
        model = UserProfile
        fields = [
            'id',
            'role',
            'full_name',
            'email',
            'contact_number',
            'linkedin_url',
            'github_url',
            'portfolio_url',
            'resume_link',
            'current_employer',
            'years_of_experience',
            'address_line_1',
            'address_line_2',
            'state',
            'country',
            'country_code',
            'location',
            'location_ref',
            'location_name',
            'preferred_location_refs',
            'preferred_location_names',
            'summary',
            'smtp_host',
            'smtp_port',
            'smtp_user',
            'smtp_password',
            'smtp_use_tls',
            'smtp_from_email',
            'imap_host',
            'imap_port',
            'imap_user',
            'imap_password',
            'imap_folder',
            'openai_api_key',
            'openai_model',
            'ai_task_instructions',
            'created_at',
            'updated_at',
        ]
        read_only_fields = ['id', 'created_at', 'updated_at']


class ProfilePanelSerializer(serializers.ModelSerializer):
    email = serializers.CharField(required=False, allow_blank=True)
    linkedin_url = serializers.CharField(required=False, allow_blank=True)
    github_url = serializers.CharField(required=False, allow_blank=True)
    portfolio_url = serializers.CharField(required=False, allow_blank=True)
    resume_link = serializers.CharField(required=False, allow_blank=True)
    location_name = serializers.SerializerMethodField()
    preferred_location_refs = serializers.PrimaryKeyRelatedField(
        source='preferred_locations',
        many=True,
        queryset=Location.objects.all(),
        required=False,
    )
    preferred_location_names = serializers.SerializerMethodField()

    def get_location_name(self, obj):
        if getattr(obj, 'location_ref_id', None) and getattr(obj, 'location_ref', None):
            return obj.location_ref.name
        return str(getattr(obj, 'location', '') or '')

    def get_preferred_location_names(self, obj):
        return [str(item.name or '') for item in obj.preferred_locations.all().order_by('name')]

    def validate_title(self, value):
        return _normalize_text(value)

    def validate_full_name(self, value):
        return _normalize_text(value)

    def validate_email(self, value):
        return _normalize_email(value)

    def validate_contact_number(self, value):
        return _normalize_text(value)

    def validate_linkedin_url(self, value):
        return _normalize_url(value)

    def validate_github_url(self, value):
        return _normalize_url(value)

    def validate_portfolio_url(self, value):
        return _normalize_url(value)

    def validate_resume_link(self, value):
        return _normalize_url(value)

    def validate_current_employer(self, value):
        return _normalize_text(value)

    def validate_years_of_experience(self, value):
        return _normalize_text(value)

    def validate_location(self, value):
        return _normalize_text(value)

    def validate_summary(self, value):
        return _normalize_text(value)

    class Meta:
        model = ProfilePanel
        fields = [
            'id',
            'title',
            'full_name',
            'email',
            'contact_number',
            'linkedin_url',
            'github_url',
            'portfolio_url',
            'resume_link',
            'current_employer',
            'years_of_experience',
            'address_line_1',
            'address_line_2',
            'state',
            'country',
            'country_code',
            'location',
            'location_ref',
            'location_name',
            'preferred_location_refs',
            'preferred_location_names',
            'summary',
            'created_at',
            'updated_at',
        ]
        read_only_fields = ['id', 'created_at', 'updated_at']


class TemplateSerializer(serializers.ModelSerializer):
    paragraph = serializers.CharField(source='achievement')
    template_scope = serializers.CharField(required=False)
    owner_name = serializers.SerializerMethodField()
    owner_label = serializers.SerializerMethodField()
    is_system = serializers.SerializerMethodField()
    is_editable = serializers.SerializerMethodField()

    def validate_name(self, value):
        text = str(value or '').strip()
        if not text:
            raise serializers.ValidationError('Template name is required.')
        request = self.context.get('request') if isinstance(self.context, dict) else None
        user = getattr(request, 'user', None)
        if getattr(user, 'is_authenticated', False):
            profile = getattr(user, 'profile_info', None)
            if profile is not None:
                rows = Template.objects.filter(profile=profile, name__iexact=text)
            else:
                rows = Template.objects.none()
            if self.instance is not None:
                rows = rows.exclude(id=self.instance.id)
            if rows.exists():
                raise serializers.ValidationError('Template name already exists.')
        return text

    def validate_category(self, value):
        text = str(value or '').strip().lower()
        if text not in {'fresh', 'follow_up'}:
            raise serializers.ValidationError('Category must be Fresh or Follow Up.')
        return text

    def validate_paragraph(self, value):
        text = str(value or '').strip()
        if not text:
            raise serializers.ValidationError('Paragraph is required.')
        return text

    def get_owner_name(self, obj):
        return str(getattr(getattr(obj.profile, 'user', None), 'username', '') or '').strip()

    def get_owner_label(self, obj):
        owner_name = self.get_owner_name(obj)
        return owner_name or 'system'

    def get_is_system(self, obj):
        return bool(getattr(obj, 'is_system_template', False))

    def get_is_editable(self, obj):
        request = self.context.get('request') if isinstance(self.context, dict) else None
        user = getattr(request, 'user', None)
        if not getattr(user, 'is_authenticated', False):
            return False
        return getattr(obj, 'user_id', None) == user.id

    class Meta:
        model = Template
        fields = [
            'id',
            'profile',
            'name',
            'template_scope',
            'category',
            'paragraph',
            'owner_name',
            'owner_label',
            'is_system',
            'is_editable',
            'created_at',
            'updated_at',
        ]
        read_only_fields = ['id', 'profile', 'created_at', 'updated_at']


AchievementSerializer = TemplateSerializer


class SubjectTemplateSerializer(serializers.ModelSerializer):
    def validate_name(self, value):
        text = str(value or '').strip()
        if not text:
            raise serializers.ValidationError('Subject template name is required.')
        request = self.context.get('request') if isinstance(self.context, dict) else None
        user = getattr(request, 'user', None)
        if getattr(user, 'is_authenticated', False):
            profile = getattr(user, 'profile_info', None)
            if profile is not None:
                rows = SubjectTemplate.objects.filter(profile=profile, name__iexact=text)
            else:
                rows = SubjectTemplate.objects.none()
            if self.instance is not None:
                rows = rows.exclude(id=self.instance.id)
            if rows.exists():
                raise serializers.ValidationError('Subject template name already exists.')
        return text

    def validate_category(self, value):
        text = str(value or '').strip().lower()
        if text not in {'personalized', 'follow_up', 'opening', 'experience', 'closing', 'general'}:
            raise serializers.ValidationError('Category must be Personalized, Follow Up, Opening, Experience, Closing, or General.')
        return text

    def validate_subject(self, value):
        text = str(value or '').strip()
        if not text:
            raise serializers.ValidationError('Subject is required.')
        return text

    class Meta:
        model = SubjectTemplate
        fields = [
            'id',
            'profile',
            'name',
            'category',
            'subject',
            'created_at',
            'updated_at',
        ]
        read_only_fields = ['id', 'profile', 'created_at', 'updated_at']


class InterviewSerializer(serializers.ModelSerializer):
    stage = serializers.CharField(required=False, allow_blank=False)
    action = serializers.CharField(required=False, allow_blank=False)
    job_label = serializers.SerializerMethodField()
    location_name = serializers.SerializerMethodField()

    def get_job_label(self, obj):
        if not getattr(obj, 'job_id', None) or not obj.job:
            return ''
        company_name = obj.job.company.name if obj.job.company_id else ''
        return f"{obj.job.job_id} | {company_name} | {obj.job.role}"

    def get_location_name(self, obj):
        if getattr(obj, 'location_ref_id', None) and getattr(obj, 'location_ref', None):
            return obj.location_ref.name
        return ''

    def validate_company_name(self, value):
        return _normalize_text(value)

    def validate_job_role(self, value):
        return _normalize_text(value)

    def validate_job_code(self, value):
        return _normalize_text(value)

    def validate_stage(self, value):
        return _normalize_text(value).lower()

    def validate_action(self, value):
        return _normalize_text(value).lower()

    def validate_notes(self, value):
        return _normalize_text(value)

    class Meta:
        model = Interview
        fields = [
            'id',
            'job',
            'job_label',
            'location_ref',
            'location_name',
            'company_name',
            'job_role',
            'job_code',
            'stage',
            'action',
            'max_round_reached',
            'milestone_events',
            'interview_at',
            'notes',
            'created_at',
            'updated_at',
        ]
        read_only_fields = ['id', 'max_round_reached', 'milestone_events', 'created_at', 'updated_at']


class LocationSerializer(serializers.ModelSerializer):
    class Meta:
        model = Location
        fields = ['id', 'name']
