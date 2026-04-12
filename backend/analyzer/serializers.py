from django.contrib.auth.models import User
from rest_framework import serializers

from .models import (
    JobRole,
    Resume,
    ResumeAnalysis,
    TailoredJobRun,
    ApplicationTracking,
    Company,
    Employee,
    Job,
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


class JobRoleSerializer(serializers.ModelSerializer):
    class Meta:
        model = JobRole
        fields = [
            'id',
            'title',
            'company',
            'description',
            'required_keywords',
            'created_at',
            'updated_at',
        ]
        read_only_fields = ['id', 'created_at', 'updated_at']


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


class ResumeAnalysisSerializer(serializers.ModelSerializer):
    resume_title = serializers.SerializerMethodField()
    job_role_title = serializers.SerializerMethodField()

    def get_resume_title(self, obj):
        if getattr(obj, 'resume', None) and getattr(obj.resume, 'title', None):
            return obj.resume.title
        return getattr(obj, 'resume_title', '') or ''

    def get_job_role_title(self, obj):
        return obj.job_role.title if obj.job_role else ''

    class Meta:
        model = ResumeAnalysis
        fields = [
            'id',
            'resume',
            'resume_title',
            'job_role',
            'job_role_title',
            'ats_score',
            'keyword_score',
            'matched_keywords',
            'missing_keywords',
            'ai_feedback',
            'created_at',
        ]
        read_only_fields = fields


class TailoredJobRunSerializer(serializers.ModelSerializer):
    resume_title = serializers.SerializerMethodField()

    def get_resume_title(self, obj):
        if getattr(obj, 'resume', None) and getattr(obj.resume, 'title', None):
            return obj.resume.title
        return ''

    class Meta:
        model = TailoredJobRun
        fields = [
            'id',
            'resume',
            'resume_title',
            'company_name',
            'job_title',
            'job_id',
            'job_url',
            'jd_text',
            'match_score',
            'keywords',
            'created_at',
        ]
        read_only_fields = fields


class ApplicationTrackingSerializer(serializers.ModelSerializer):
    class Meta:
        model = ApplicationTracking
        fields = [
            'id',
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


class EmployeeSerializer(serializers.ModelSerializer):
    company_name = serializers.SerializerMethodField()

    def get_company_name(self, obj):
        return obj.company.name if getattr(obj, 'company', None) else ''

    class Meta:
        model = Employee
        fields = [
            'id',
            'name',
            'company',
            'company_name',
            'department',
            'email',
            'about',
            'personalized_template_helpful',
            'profile',
            'location',
            'created_at',
            'updated_at',
        ]
        read_only_fields = ['id', 'company_name', 'created_at', 'updated_at']


class CompanySerializer(serializers.ModelSerializer):
    employees = EmployeeSerializer(many=True, read_only=True)

    class Meta:
        model = Company
        fields = [
            'id',
            'name',
            'mail_format',
            'career_url',
            'workday_domain_url',
            'employees',
            'created_at',
            'updated_at',
        ]
        read_only_fields = ['id', 'employees', 'created_at', 'updated_at']


class JobSerializer(serializers.ModelSerializer):
    company_name = serializers.SerializerMethodField()

    def get_company_name(self, obj):
        return obj.company.name if getattr(obj, 'company', None) else ''

    class Meta:
        model = Job
        fields = [
            'id',
            'job_id',
            'role',
            'job_link',
            'company',
            'company_name',
            'date_of_posting',
            'created_at',
            'updated_at',
        ]
        read_only_fields = ['id', 'company_name', 'created_at', 'updated_at']
