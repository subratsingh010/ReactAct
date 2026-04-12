from django.db import models
from django.contrib.auth.models import User


class JobRole(models.Model):
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='job_roles')
    title = models.CharField(max_length=120)
    company = models.CharField(max_length=120, blank=True)
    description = models.TextField()
    required_keywords = models.JSONField(default=list, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return f'{self.title} ({self.user.username})'


class Resume(models.Model):
    STATUS_CHOICES = [
        ('draft', 'Draft'),
        ('uploaded', 'Uploaded'),
        ('optimized', 'Optimized'),
    ]

    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='resumes')
    title = models.CharField(max_length=140)
    original_text = models.TextField(blank=True)
    optimized_text = models.TextField(blank=True)
    builder_data = models.JSONField(default=dict, blank=True)
    is_default = models.BooleanField(default=False)
    file = models.FileField(upload_to='resumes/', blank=True, null=True)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='draft')
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return f'{self.title} ({self.user.username})'


class ResumeAnalysis(models.Model):
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='analyses')
    resume = models.ForeignKey(
        Resume,
        on_delete=models.SET_NULL,
        blank=True,
        null=True,
        related_name='analyses',
    )
    # Snapshot so analyses remain understandable even if the resume is later deleted.
    resume_title = models.CharField(max_length=140, blank=True)
    job_role = models.ForeignKey(
        JobRole,
        on_delete=models.SET_NULL,
        blank=True,
        null=True,
        related_name='analyses',
    )
    ats_score = models.PositiveSmallIntegerField(default=0)
    keyword_score = models.PositiveSmallIntegerField(default=0)
    matched_keywords = models.JSONField(default=list, blank=True)
    missing_keywords = models.JSONField(default=list, blank=True)
    ai_feedback = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return f'Analysis #{self.id} - {self.ats_score}'


class TailoredJobRun(models.Model):
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='tailored_job_runs')
    resume = models.ForeignKey(
        Resume,
        on_delete=models.SET_NULL,
        blank=True,
        null=True,
        related_name='tailored_job_runs',
    )
    company_name = models.CharField(max_length=180, blank=True)
    job_title = models.CharField(max_length=180, blank=True)
    job_id = models.CharField(max_length=120, blank=True)
    job_url = models.URLField(blank=True, max_length=1000)
    jd_text = models.TextField(blank=True)
    match_score = models.FloatField(default=0.0)
    keywords = models.JSONField(default=list, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        title = self.job_title or 'Tailored Job'
        return f'{title} ({self.user.username})'


class Company(models.Model):
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='companies')
    name = models.CharField(max_length=180)
    career_url = models.URLField(blank=True, max_length=1000)
    workday_domain_url = models.URLField(blank=True, max_length=1000)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['name']

    def __str__(self):
        return f'{self.name} ({self.user.username})'


class Employee(models.Model):
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='employees')
    name = models.CharField(max_length=180)
    company = models.ForeignKey(
        Company,
        on_delete=models.CASCADE,
        related_name='employees',
    )
    profile = models.URLField(blank=True, max_length=1000)
    location = models.CharField(max_length=180, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['name']

    def __str__(self):
        return f'{self.name} ({self.company.name})'


class Job(models.Model):
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='jobs')
    job_id = models.CharField(max_length=120)
    role = models.CharField(max_length=180)
    job_link = models.URLField(blank=True, max_length=1000)
    company = models.ForeignKey(
        Company,
        on_delete=models.CASCADE,
        related_name='jobs',
    )
    date_of_posting = models.DateField(blank=True, null=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-date_of_posting', '-created_at']

    def __str__(self):
        return f'{self.role} ({self.company.name})'


class Tracking(models.Model):
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='tracking')
    company = models.ForeignKey(
        Company,
        on_delete=models.SET_NULL,
        blank=True,
        null=True,
        related_name='tracking_rows',
    )
    employee = models.ForeignKey(
        Employee,
        on_delete=models.SET_NULL,
        blank=True,
        null=True,
        related_name='tracking_rows',
    )
    job = models.ForeignKey(
        Job,
        on_delete=models.SET_NULL,
        blank=True,
        null=True,
        related_name='tracking_rows',
    )
    mailed = models.BooleanField(default=False)
    applied_date = models.DateField(blank=True, null=True)
    is_open = models.BooleanField(default=True)
    got_replied = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-applied_date', '-created_at']

    def __str__(self):
        company_name = self.company.name if self.company_id else 'Company'
        return f'Tracking ({company_name})'


class ApplicationTracking(models.Model):
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='tracking_rows')
    company_name = models.CharField(max_length=180)
    job_id = models.CharField(max_length=120, blank=True)
    mailed = models.BooleanField(default=False)
    applied_date = models.DateField(blank=True, null=True)
    posting_date = models.DateField(blank=True, null=True)
    is_open = models.BooleanField(default=True)
    available_hrs = models.JSONField(default=list, blank=True)
    selected_hrs = models.JSONField(default=list, blank=True)
    got_replied = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-applied_date', '-created_at']

    def __str__(self):
        return f'{self.company_name} ({self.user.username})'
