from django.db import models
from django.contrib.auth.models import User


class TimeStampedModel(models.Model):
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        abstract = True


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


class Company(TimeStampedModel):
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='companies')
    name = models.CharField(max_length=180)
    mail_format = models.CharField(max_length=180, blank=True)
    career_url = models.URLField(blank=True, max_length=1000)
    workday_domain_url = models.URLField(blank=True, max_length=1000)
    linkedin_url = models.URLField(blank=True, max_length=1000)

    class Meta:
        ordering = ['name']

    def __str__(self):
        return f'{self.name} ({self.user.username})'


class Employee(TimeStampedModel):
    TEMPLATE_HELPFUL_CHOICES = [
        ('good', 'Good'),
        ('partial_somewhat', 'Partial / Somewhat'),
        ('never', 'Never'),
    ]
    department_choices = [
        ('Engineering', 'Engineering'),
        ('HR', 'HR'),
        ('Other', 'Other'),
    ]

    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='employees')
    name = models.CharField(max_length=180)
    company = models.ForeignKey(
        Company,
        on_delete=models.CASCADE,
        related_name='employees',
    )
    JobRole = models.CharField(max_length=120, blank=True)
    department = models.CharField(
        max_length=120,
        choices=department_choices,
        blank=True
    )
    email = models.EmailField(blank=True, max_length=320)
    contact_number = models.CharField(max_length=32, blank=True)
    about = models.TextField(blank=True)
    helpful = models.CharField(
        max_length=20,
        choices=TEMPLATE_HELPFUL_CHOICES,
        default='partial_somewhat',
    )
    personalized_template = models.TextField(blank=True)
    profile = models.URLField(blank=True, max_length=1000)
    location = models.CharField(max_length=180, blank=True)


    class Meta:
        ordering = ['name']

    def __str__(self):
        return f'{self.name} ({self.company.name})'


class Job(TimeStampedModel):
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='jobs')
    job_id = models.CharField(max_length=120)
    role = models.CharField(max_length=180)
    job_link = models.URLField(blank=True, max_length=1000)
    tailored_resume_file = models.FileField(upload_to='tailored_resumes/', blank=True, null=True)
    tailored_resume_builder_data = models.JSONField(default=dict, blank=True)
    company = models.ForeignKey(
        Company,
        on_delete=models.CASCADE,
        related_name='jobs',
    )
    jd_text = models.TextField(blank=True)
    date_of_posting = models.DateField(blank=True, null=True)
    applied_at  = models.DateField(blank=True, null=True)
    is_closed = models.BooleanField(default=False)
    is_removed = models.BooleanField(default=False)
    class Meta:
        ordering = ['-date_of_posting', '-created_at']

    def __str__(self):
        return f'{self.role} ({self.company.name})'


class MailTracking(TimeStampedModel):
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
    got_replied = models.BooleanField(default=False)
    mail_history = models.JSONField(default=list, blank=True)
    mailed_at = models.DateTimeField(blank=True, null=True)
    replied_at = models.DateTimeField(blank=True, null=True)

    class Meta:
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['user', '-created_at']),
            models.Index(fields=['job', '-created_at']),
        ]

    def __str__(self):
        company_name = self.company.name if self.company_id else 'Company'
        return f'Tracking ({company_name})'


class Tracking(TimeStampedModel):
    actions_choices = [
        ('fresh', 'Fresh'),
        ('followed_up', 'Followed Up'),
    ]
    job = models.ForeignKey(
        Job,
        on_delete=models.SET_NULL,
        blank=True,
        null=True,
        related_name='application_tracking_rows',
    )
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='tracking_rows')
    resume = models.ForeignKey(
        Resume,
        on_delete=models.SET_NULL,
        blank=True,
        null=True,
        related_name='tracking_rows',
    )
    schedule_time = models.DateTimeField(blank=True, null=True)
    needs_tailored = models.BooleanField(default=False)
    tailoring_scope = models.CharField(max_length=60, blank=True)
    selected_department = models.CharField(max_length=120, blank=True)
    selected_role = models.CharField(max_length=120, blank=True)
    mailed = models.BooleanField(default=False)
    got_replied = models.BooleanField(default=False)
    is_open = models.BooleanField(default=True)
    selected_hrs = models.ManyToManyField(Employee, blank=True, related_name='selected_in_tracking_rows')
    action = models.CharField(
        max_length=20,
        choices=actions_choices,
        default='fresh',
    )
    is_freezed = models.BooleanField(default=False)
    freezed_at = models.DateTimeField(blank=True, null=True)
    is_removed = models.BooleanField(default=False)
    mail_tracking = models.ForeignKey(
        MailTracking,
        on_delete=models.SET_NULL,
        blank=True,
        null=True,
        related_name='tracking_rows',
    )
    class Meta:
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['user', '-created_at']),
            models.Index(fields=['job', '-created_at']),
            models.Index(fields=['mail_tracking', '-created_at']),
            models.Index(fields=['user', 'is_removed', '-created_at']),
        ]

    def __str__(self):
        job_name = self.job.role if self.job_id and getattr(self.job, 'role', None) else 'Tracking'
        return f'{job_name} ({self.user.username})'


class TrackingAction(TimeStampedModel):
    ACTION_TYPE_CHOICES = [
        ('fresh', 'Fresh'),
        ('followup', 'Follow Up'),
    ]
    SEND_MODE_CHOICES = [
        ('sent', 'Sent Now'),
        ('scheduled', 'Scheduled'),
    ]

    tracking = models.ForeignKey(Tracking, on_delete=models.CASCADE, related_name='actions')
    action_type = models.CharField(max_length=20, choices=ACTION_TYPE_CHOICES)
    send_mode = models.CharField(max_length=20, choices=SEND_MODE_CHOICES, default='sent')
    action_at = models.DateTimeField()
    notes = models.TextField(blank=True)

    class Meta:
        ordering = ['created_at']

    def __str__(self):
        return f'{self.action_type} ({self.tracking_id})'


class MailTrackingEvent(TimeStampedModel):
    MAIL_TYPE_CHOICES = [
        ('fresh', 'Fresh'),
        ('followup', 'Follow Up'),
    ]
    SEND_MODE_CHOICES = [
        ('sent', 'Sent Now'),
        ('scheduled', 'Scheduled'),
    ]

    mail_tracking = models.ForeignKey(MailTracking, on_delete=models.CASCADE, related_name='events')
    tracking = models.ForeignKey(
        Tracking,
        on_delete=models.SET_NULL,
        blank=True,
        null=True,
        related_name='mail_events',
    )
    employee = models.ForeignKey(
        Employee,
        on_delete=models.SET_NULL,
        blank=True,
        null=True,
        related_name='mail_tracking_events',
    )
    mail_type = models.CharField(max_length=20, choices=MAIL_TYPE_CHOICES)
    send_mode = models.CharField(max_length=20, choices=SEND_MODE_CHOICES, default='sent')
    action_at = models.DateTimeField()
    got_replied = models.BooleanField(default=False)
    notes = models.TextField(blank=True)
    raw_payload = models.JSONField(default=dict, blank=True)

    class Meta:
        ordering = ['created_at']
        indexes = [
            models.Index(fields=['mail_tracking', '-created_at']),
            models.Index(fields=['tracking', '-created_at']),
            models.Index(fields=['employee', '-created_at']),
        ]

    def __str__(self):
        return f'{self.mail_type} ({self.mail_tracking_id})'
