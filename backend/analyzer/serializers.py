from django.contrib.auth.models import User
from rest_framework import serializers

from .models import (
    Resume,
    TailoredResume,
    MailTracking,
    Company,
    Employee,
    Job,
    Location,
    UserProfile,
    Achievement,
    Interview,
)


class SignupSerializer(serializers.ModelSerializer):
    password = serializers.CharField(write_only=True)

    class Meta:
        model = User
        fields = ['username', 'email', 'password']

    def create(self, validated_data):
        return User.objects.create_user(
            username=validated_data['username'],
            email=validated_data.get('email', ''),
            password=validated_data['password'],
        )


class ResumeSerializer(serializers.ModelSerializer):
    class Meta:
        model = Resume
        fields = [
            'id',
            'title',
            'original_text',
            'optimized_text',
            'builder_data',
            'is_default',
            'status',
            'created_at',
            'updated_at',
        ]
        read_only_fields = ['id', 'optimized_text', 'status', 'created_at', 'updated_at']


class TailoredResumeSerializer(serializers.ModelSerializer):
    job_id = serializers.IntegerField(source='job.id', read_only=True)
    job_label = serializers.SerializerMethodField()
    resume_id = serializers.IntegerField(source='resume.id', read_only=True)
    resume_title = serializers.SerializerMethodField()

    def get_job_label(self, obj):
        if not obj.job_id or not obj.job:
            return ''
        return f"{obj.job.job_id} - {obj.job.role}"

    def get_resume_title(self, obj):
        if not obj.resume_id or not obj.resume:
            return ''
        return obj.resume.title

    class Meta:
        model = TailoredResume
        fields = [
            'id',
            'name',
            'builder_data',
            'job',
            'job_id',
            'job_label',
            'resume',
            'resume_id',
            'resume_title',
            'created_at',
            'updated_at',
        ]
        read_only_fields = ['id', 'job_id', 'job_label', 'resume_id', 'resume_title', 'created_at', 'updated_at']


class MailTrackingSerializer(serializers.ModelSerializer):
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
        if getattr(obj, 'company', None):
            return obj.company.name
        return ''

    def get_job_id(self, obj):
        compat = self._compat_payload(obj)
        if compat.get('job_id'):
            return compat.get('job_id')
        if getattr(obj, 'job', None):
            return obj.job.job_id
        return ''

    def get_applied_date(self, obj):
        compat = self._compat_payload(obj)
        if compat.get('applied_date'):
            return compat.get('applied_date')
        if getattr(obj, 'job', None) and obj.job.applied_at:
            return obj.job.applied_at.isoformat()
        return None

    def get_posting_date(self, obj):
        compat = self._compat_payload(obj)
        if compat.get('posting_date'):
            return compat.get('posting_date')
        if getattr(obj, 'job', None) and obj.job.date_of_posting:
            return obj.job.date_of_posting.isoformat()
        return None

    def get_is_open(self, obj):
        compat = self._compat_payload(obj)
        if 'is_open' in compat:
            return bool(compat.get('is_open'))
        if getattr(obj, 'job', None):
            return not bool(obj.job.is_closed)
        return True

    def get_available_hrs(self, obj):
        compat = self._compat_payload(obj)
        value = compat.get('available_hrs')
        return value if isinstance(value, list) else []

    def get_selected_hrs(self, obj):
        compat = self._compat_payload(obj)
        value = compat.get('selected_hrs')
        return value if isinstance(value, list) else []

    class Meta:
        model = MailTracking
        fields = [
            'id',
            'company',
            'employee',
            'job',
            'company_name',
            'job_id',
            'mailed',
            'applied_date',
            'posting_date',
            'is_open',
            'available_hrs',
            'selected_hrs',
            'got_replied',
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
    role = serializers.CharField(source='JobRole', required=False, allow_blank=True)
    personalized_template_helpful = serializers.CharField(source='helpful', required=False, allow_blank=True)

    def get_company_name(self, obj):
        return obj.company.name if getattr(obj, 'company', None) else ''

    def get_location_name(self, obj):
        if getattr(obj, 'location_ref_id', None) and getattr(obj, 'location_ref', None):
            return obj.location_ref.name
        return str(getattr(obj, 'location', '') or '')

    class Meta:
        model = Employee
        fields = [
            'id',
            'name',
            'company',
            'company_name',
            'role',
            'department',
            'email',
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
    company_name = serializers.SerializerMethodField()
    has_tailored_resume = serializers.SerializerMethodField()
    tailored_resumes = serializers.SerializerMethodField()
    resume_preview = serializers.SerializerMethodField()
    applied = serializers.SerializerMethodField()

    def get_company_name(self, obj):
        return obj.company.name if getattr(obj, 'company', None) else ''

    def get_has_tailored_resume(self, obj):
        return obj.tailored_resumes.exists()

    def get_tailored_resumes(self, obj):
        rows = obj.tailored_resumes.all().order_by('created_at', 'id')
        return [
            {
                'id': item.id,
                'name': str(item.name or '').strip() or f'Tailored Resume #{item.id}',
            }
            for item in rows
        ]

    def get_resume_preview(self, obj):
        first = obj.tailored_resumes.all().order_by('created_at', 'id').first()
        if not first:
            return None
        data = first.builder_data or {}
        if not isinstance(data, dict) or not data:
            return None
        return {
            'id': first.id,
            'title': str(first.name or '').strip() or f'Tailored Resume #{first.id}',
            'builder_data': data,
        }

    def get_applied(self, obj):
        return obj.applied_at is not None

    class Meta:
        model = Job
        fields = [
            'id',
            'job_id',
            'role',
            'job_link',
            'has_tailored_resume',
            'tailored_resumes',
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
    location_name = serializers.SerializerMethodField()

    def get_location_name(self, obj):
        if getattr(obj, 'location_ref_id', None) and getattr(obj, 'location_ref', None):
            return obj.location_ref.name
        return str(getattr(obj, 'location', '') or '')

    class Meta:
        model = UserProfile
        fields = [
            'id',
            'full_name',
            'email',
            'contact_number',
            'linkedin_url',
            'github_url',
            'portfolio_url',
            'current_employer',
            'years_of_experience',
            'location',
            'location_ref',
            'location_name',
            'summary',
            'created_at',
            'updated_at',
        ]
        read_only_fields = ['id', 'created_at', 'updated_at']


class AchievementSerializer(serializers.ModelSerializer):
    class Meta:
        model = Achievement
        fields = [
            'id',
            'name',
            'achievement',
            'skills',
            'created_at',
            'updated_at',
        ]
        read_only_fields = ['id', 'created_at', 'updated_at']


class InterviewSerializer(serializers.ModelSerializer):
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
