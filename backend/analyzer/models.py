from django.db import models
from django.contrib.auth.models import User
from django.utils import timezone
from django.db.models.functions import Lower


class BaseModel(models.Model):
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def soft_delete(self, using=None, keep_parents=False):
        update_fields = []
        if hasattr(self, 'is_removed') and not bool(getattr(self, 'is_removed', False)):
            self.is_removed = True
            update_fields.append('is_removed')
        if hasattr(self, 'removed_at') and getattr(self, 'removed_at', None) is None:
            self.removed_at = timezone.now()
            update_fields.append('removed_at')
        if update_fields:
            if hasattr(self, 'updated_at'):
                update_fields.append('updated_at')
            self.save(update_fields=update_fields)
            return
        return super().delete(using=using, keep_parents=keep_parents)

    def hard_delete(self, using=None, keep_parents=False):
        return super().delete(using=using, keep_parents=keep_parents)

    def delete(self, using=None, keep_parents=False):
        return self.soft_delete(using=using, keep_parents=keep_parents)

    class Meta:
        abstract = True


class Resume(BaseModel):
    STATUS_CHOICES = [
        ('draft', 'Draft'),
        ('uploaded', 'Uploaded'),
        ('optimized', 'Optimized'),
    ]

    profile = models.ForeignKey(
        'UserProfile',
        on_delete=models.CASCADE,
        related_name='resumes',
    )
    title = models.CharField(max_length=140)
    original_text = models.TextField(blank=True)
    optimized_text = models.TextField(blank=True)
    builder_data = models.JSONField(default=dict, blank=True)
    is_default = models.BooleanField(default=False)
    is_tailored = models.BooleanField(default=False)
    job = models.ForeignKey(
        'Job',
        on_delete=models.SET_NULL,
        blank=True,
        null=True,
        related_name='resumes',
    )
    source_resume = models.ForeignKey(
        'self',
        on_delete=models.SET_NULL,
        blank=True,
        null=True,
        related_name='tailored_versions',
    )
    file = models.FileField(upload_to='resumes/', blank=True, null=True)
    ats_pdf_path = models.CharField(max_length=1000, blank=True, default='')
    ats_pdf_builder_hash = models.CharField(max_length=64, blank=True, default='')
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='draft')
    class Meta:
        ordering = ['-created_at']

    @property
    def user(self):
        return getattr(self.profile, 'user', None)

    @property
    def user_id(self):
        return getattr(self.profile, 'user_id', None)

    def __str__(self):
        username = getattr(getattr(self.profile, 'user', None), 'username', '')
        return f'{self.title} ({username})'


class Company(BaseModel):
    profile = models.ForeignKey(
        'UserProfile',
        on_delete=models.CASCADE,
        related_name='companies',
    )
    name = models.CharField(max_length=180)
    mail_format = models.CharField(max_length=180, blank=True)
    career_url = models.URLField(blank=True, max_length=1000)
    workday_domain_url = models.URLField(blank=True, max_length=1000)
    linkedin_url = models.URLField(blank=True, max_length=1000)

    class Meta:
        ordering = ['name']
        constraints = [
            models.UniqueConstraint(
                Lower('name'),
                'profile',
                name='uniq_company_profile_name_ci',
            ),
        ]

    def save(self, *args, **kwargs):
        self.name = ' '.join(str(self.name or '').split()).lower()
        super().save(*args, **kwargs)

    @property
    def user(self):
        return getattr(self.profile, 'user', None)

    @property
    def user_id(self):
        return getattr(self.profile, 'user_id', None)

    def __str__(self):
        username = getattr(getattr(self.profile, 'user', None), 'username', '')
        return f'{self.name} ({username})'


class Location(BaseModel):
    name = models.CharField(max_length=180, unique=True)

    class Meta:
        ordering = ['name']
        constraints = [
            models.UniqueConstraint(
                Lower('name'),
                name='uniq_location_name_ci',
            ),
        ]

    def save(self, *args, **kwargs):
        self.name = ' '.join(str(self.name or '').split())
        super().save(*args, **kwargs)

    def __str__(self):
        return self.name


class Employee(BaseModel):
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

    owner_profile = models.ForeignKey(
        'UserProfile',
        on_delete=models.CASCADE,
        related_name='employees',
    )
    name = models.CharField(max_length=180)
    first_name = models.CharField(max_length=120, blank=True, default='')
    middle_name = models.CharField(max_length=120, blank=True, default='')
    last_name = models.CharField(max_length=120, blank=True, default='')
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
    working_mail = models.BooleanField(default=True)
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

    @property
    def user(self):
        return getattr(self.owner_profile, 'user', None)

    @property
    def user_id(self):
        return getattr(self.owner_profile, 'user_id', None)

    def __str__(self):
        return f'{self.name} ({self.company.name})'


class Job(BaseModel):
    job_id = models.CharField(max_length=120)
    role = models.CharField(max_length=180)
    job_link = models.URLField(blank=True, max_length=1000)
    location = models.CharField(max_length=180, blank=True)
    created_by = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        blank=True,
        null=True,
        related_name='created_jobs',
    )
    assigned_to = models.ManyToManyField(
        User,
        blank=True,
        related_name='assigned_jobs',
    )
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
        constraints = [
            models.UniqueConstraint(
                'company',
                Lower('job_id'),
                Lower('location'),
                condition=models.Q(is_removed=False) & ~models.Q(job_id=''),
                name='uniq_active_job_company_jobid_location_ci',
            ),
        ]
        permissions = [
            ('view_all_job', 'Can view all job records'),
        ]

    @property
    def user(self):
        if getattr(self, 'created_by_id', None):
            return self.created_by
        company = getattr(self, 'company', None)
        profile = getattr(company, 'profile', None) if company is not None else None
        return getattr(profile, 'user', None)

    @property
    def user_id(self):
        if getattr(self, 'created_by_id', None):
            return self.created_by_id
        company = getattr(self, 'company', None)
        profile = getattr(company, 'profile', None) if company is not None else None
        return getattr(profile, 'user_id', None)

    def __str__(self):
        return f'{self.role} ({self.company.name})'


class MailTracking(BaseModel):
    profile = models.ForeignKey(
        'UserProfile',
        on_delete=models.CASCADE,
        related_name='mail_tracking',
    )
    employee = models.ForeignKey(
        Employee,
        on_delete=models.SET_NULL,
        blank=True,
        null=True,
        related_name='mail_tracking_refs',
    )
    resume = models.ForeignKey(
        Resume,
        on_delete=models.SET_NULL,
        blank=True,
        null=True,
        related_name='mail_tracking_refs',
    )
    tracking = models.OneToOneField(
        'Tracking',
        on_delete=models.CASCADE,
        blank=True,
        null=True,
        related_name='mail_tracking_record',
    )
    mail_history = models.JSONField(default=list, blank=True)

    class Meta:
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['profile', '-created_at']),
            models.Index(fields=['tracking', '-created_at']),
        ]

    @property
    def user(self):
        return getattr(self.profile, 'user', None)

    @property
    def user_id(self):
        return getattr(self.profile, 'user_id', None)

    def __str__(self):
        tracking = getattr(self, 'tracking', None)
        company_name = tracking.job.company.name if tracking and tracking.job_id and tracking.job and tracking.job.company_id else 'Company'
        return f'Tracking ({company_name})'


class Tracking(BaseModel):
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
    profile = models.ForeignKey(
        'UserProfile',
        on_delete=models.CASCADE,
        related_name='tracking_rows',
    )
    template = models.ForeignKey(
        'Template',
        on_delete=models.SET_NULL,
        blank=True,
        null=True,
        related_name='tracking_rows',
    )
    template_ids_ordered = models.JSONField(default=list, blank=True)
    personalized_template = models.ForeignKey(
        'Template',
        on_delete=models.SET_NULL,
        blank=True,
        null=True,
        related_name='tracking_personalized_rows',
    )
    resume = models.ForeignKey(
        Resume,
        on_delete=models.SET_NULL,
        blank=True,
        null=True,
        related_name='tracking_rows',
    )
    schedule_time = models.DateTimeField(blank=True, null=True)
    use_hardcoded_personalized_intro = models.BooleanField(default=False)
    mail_delivery_status = models.CharField(
        max_length=20,
        choices=[
            ('pending', 'Pending'),
            ('sent_via_cron', 'Sent Via Cron'),
            ('successful_sent', 'Successful Sent'),
            ('mail_bounced', 'Mail Bounced'),
            ('failed', 'Failed'),
            ('partial_sent', 'Partial Sent'),
        ],
        default='pending',
    )
    mailed = models.BooleanField(default=False)
    selected_hrs = models.ManyToManyField(Employee, blank=True, related_name='selected_in_tracking_rows')
    mail_type = models.CharField(
        max_length=20,
        choices=actions_choices,
        default='fresh',
    )
    approved_test_mail_payloads = models.JSONField(default=list, blank=True)
    mail_subject = models.CharField(max_length=255, blank=True, default='')
    interaction_time = models.CharField(max_length=120, blank=True, default='')
    interview_round = models.CharField(max_length=120, blank=True, default='')
    is_freezed = models.BooleanField(default=False)
    freezed_at = models.DateTimeField(blank=True, null=True)
    class Meta:
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['profile', '-created_at']),
            models.Index(fields=['job', '-created_at']),
        ]

    @property
    def user(self):
        return getattr(self.profile, 'user', None)

    @property
    def user_id(self):
        return getattr(self.profile, 'user_id', None)

    def __str__(self):
        job_name = self.job.role if self.job_id and getattr(self.job, 'role', None) else 'Tracking'
        username = getattr(getattr(self.profile, 'user', None), 'username', '')
        return f'{job_name} ({username})'

    @property
    def achievement(self):
        return self.template

    @achievement.setter
    def achievement(self, value):
        self.template = value

    @property
    def achievement_id(self):
        return self.template_id

    @achievement_id.setter
    def achievement_id(self, value):
        self.template_id = value

    @property
    def achievement_ids_ordered(self):
        return self.template_ids_ordered

    @achievement_ids_ordered.setter
    def achievement_ids_ordered(self, value):
        self.template_ids_ordered = value


class TrackingAction(BaseModel):
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


class MailTrackingEvent(BaseModel):
    MAIL_TYPE_CHOICES = [
        ('fresh', 'Fresh'),
        ('followup', 'Follow Up'),
    ]
    SEND_MODE_CHOICES = [
        ('sent', 'Sent Now'),
        ('scheduled', 'Scheduled'),
    ]
    STATUS_CHOICES = [
        ('pending', 'Pending'),
        ('sent', 'Sent'),
        ('failed', 'Failed'),
        ('bounced', 'Bounced'),
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
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='pending')
    action_at = models.DateTimeField()
    notes = models.TextField(blank=True)
    source_uid = models.CharField(max_length=255, blank=True, default='')
    source_message_id = models.CharField(max_length=1000, blank=True, default='')
    raw_payload = models.JSONField(default=dict, blank=True)

    class Meta:
        ordering = ['created_at']
        indexes = [
            models.Index(fields=['mail_tracking', '-created_at']),
            models.Index(fields=['tracking', '-created_at']),
            models.Index(fields=['employee', '-created_at']),
            models.Index(fields=['mail_tracking', 'status', '-created_at'], name='analyzer_ma_mail_tr_9ddbce_idx'),
            models.Index(fields=['source_uid'], name='analyzer_ma_source_uid_idx'),
            models.Index(fields=['source_message_id'], name='analyzer_ma_source_msg_idx'),
        ]

    def __str__(self):
        return f'{self.mail_type} ({self.mail_tracking_id})'


class UserProfile(BaseModel):
    ROLE_SUPERADMIN = 'superadmin'
    ROLE_ADMIN = 'admin'
    ROLE_READ_ONLY = 'read_only'
    ROLE_CHOICES = [
        (ROLE_SUPERADMIN, 'Super Admin'),
        (ROLE_ADMIN, 'Admin'),
        (ROLE_READ_ONLY, 'Read Only'),
    ]

    user = models.OneToOneField(User, on_delete=models.CASCADE, related_name='profile_info')
    role = models.CharField(max_length=20, choices=ROLE_CHOICES, default=ROLE_ADMIN)
    full_name = models.CharField(max_length=180, blank=True)
    email = models.EmailField(blank=True, max_length=320)
    contact_number = models.CharField(max_length=32, blank=True)
    linkedin_url = models.URLField(blank=True, max_length=1000)
    github_url = models.URLField(blank=True, max_length=1000)
    portfolio_url = models.URLField(blank=True, max_length=1000)
    resume_link = models.URLField(blank=True, max_length=1000)
    current_employer = models.CharField(max_length=180, blank=True)
    years_of_experience = models.CharField(max_length=60, blank=True)
    address_line_1 = models.CharField(max_length=220, blank=True)
    address_line_2 = models.CharField(max_length=220, blank=True)
    state = models.CharField(max_length=120, blank=True)
    country = models.CharField(max_length=120, blank=True)
    country_code = models.CharField(max_length=16, blank=True)
    location = models.CharField(max_length=180, blank=True)
    preferred_locations = models.ManyToManyField(
        Location,
        blank=True,
        related_name='preferred_by_profiles',
    )
    summary = models.TextField(blank=True)
    smtp_host = models.CharField(max_length=255, blank=True)
    smtp_port = models.PositiveIntegerField(blank=True, null=True)
    smtp_user = models.CharField(max_length=320, blank=True)
    smtp_password = models.CharField(max_length=500, blank=True)
    smtp_use_tls = models.BooleanField(default=True)
    smtp_from_email = models.EmailField(blank=True, max_length=320)
    imap_host = models.CharField(max_length=255, blank=True)
    imap_port = models.PositiveIntegerField(blank=True, null=True)
    imap_user = models.CharField(max_length=320, blank=True)
    imap_password = models.CharField(max_length=500, blank=True)
    imap_folder = models.CharField(max_length=255, blank=True)
    openai_api_key = models.CharField(max_length=500, blank=True)
    openai_model = models.CharField(max_length=120, blank=True)
    ai_task_instructions = models.TextField(blank=True)

    class Meta:
        ordering = ['-updated_at', '-created_at']

    def __str__(self):
        return f'Profile ({self.user.username})'


class ProfilePanel(BaseModel):
    profile = models.ForeignKey(
        'UserProfile',
        on_delete=models.CASCADE,
        related_name='profile_panels',
    )
    title = models.CharField(max_length=120, blank=True)
    full_name = models.CharField(max_length=180, blank=True)
    email = models.EmailField(blank=True, max_length=320)
    contact_number = models.CharField(max_length=32, blank=True)
    linkedin_url = models.URLField(blank=True, max_length=1000)
    github_url = models.URLField(blank=True, max_length=1000)
    portfolio_url = models.URLField(blank=True, max_length=1000)
    resume_link = models.URLField(blank=True, max_length=1000)
    current_employer = models.CharField(max_length=180, blank=True)
    years_of_experience = models.CharField(max_length=60, blank=True)
    address_line_1 = models.CharField(max_length=220, blank=True)
    address_line_2 = models.CharField(max_length=220, blank=True)
    state = models.CharField(max_length=120, blank=True)
    country = models.CharField(max_length=120, blank=True)
    country_code = models.CharField(max_length=16, blank=True)
    location = models.CharField(max_length=180, blank=True)
    preferred_locations = models.ManyToManyField(
        Location,
        blank=True,
        related_name='preferred_by_profile_panels',
    )
    summary = models.TextField(blank=True)

    class Meta:
        ordering = ['-updated_at', '-created_at']

    @property
    def user(self):
        return getattr(self.profile, 'user', None)

    @property
    def user_id(self):
        return getattr(self.profile, 'user_id', None)

    def __str__(self):
        label = str(self.title or self.full_name or f'Panel {self.pk or ""}').strip()
        username = getattr(getattr(self.profile, 'user', None), 'username', '')
        return f'{label} ({username})'

class Template(BaseModel):
    TEMPLATE_SCOPE_SYSTEM = 'system'
    TEMPLATE_SCOPE_USER_BASED = 'user_based'
    CATEGORY_CHOICES = [
        ('personalized', 'Personalized'),
        ('follow_up', 'Follow Up'),
        ('opening', 'Opening'),
        ('experience', 'Experience'),
        ('closing', 'Closing'),
        ('general', 'General'),
    ]
    TEMPLATE_SCOPE_CHOICES = [
        (TEMPLATE_SCOPE_SYSTEM, 'System'),
        (TEMPLATE_SCOPE_USER_BASED, 'User Based'),
    ]

    profile = models.ForeignKey(
        UserProfile,
        on_delete=models.CASCADE,
        related_name='templates',
        null=True,
        blank=True,
    )
    name = models.CharField(max_length=220)
    template_scope = models.CharField(max_length=20, choices=TEMPLATE_SCOPE_CHOICES, default=TEMPLATE_SCOPE_USER_BASED)
    category = models.CharField(max_length=20, choices=CATEGORY_CHOICES, default='general')
    achievement = models.TextField(blank=True)
    skills = models.TextField(blank=True)

    class Meta:
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['profile', '-created_at']),
        ]
        constraints = [
            models.UniqueConstraint(
                Lower('name'),
                'profile',
                name='uniq_template_profile_name_ci',
            ),
        ]

    @property
    def user(self):
        return getattr(self.profile, 'user', None)

    @property
    def user_id(self):
        return getattr(self.profile, 'user_id', None)

    @property
    def is_system_template(self):
        return str(self.template_scope or '').strip().lower() == self.TEMPLATE_SCOPE_SYSTEM

    def __str__(self):
        username = getattr(getattr(self.profile, 'user', None), 'username', '') or 'system'
        return f'{self.name} ({username})'


Achievement = Template


class SubjectTemplate(BaseModel):
    CATEGORY_CHOICES = [
        ('fresh', 'Fresh'),
        ('follow_up', 'Follow Up'),
    ]

    profile = models.ForeignKey(
        'UserProfile',
        on_delete=models.CASCADE,
        related_name='subject_templates',
    )
    name = models.CharField(max_length=220)
    category = models.CharField(max_length=20, choices=CATEGORY_CHOICES, default='fresh')
    subject = models.CharField(max_length=255)

    class Meta:
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['profile', '-created_at']),
        ]
        constraints = [
            models.UniqueConstraint(
                Lower('name'),
                'profile',
                name='uniq_subject_template_profile_name_ci',
            ),
        ]

    @property
    def user(self):
        return getattr(self.profile, 'user', None)

    @property
    def user_id(self):
        return getattr(self.profile, 'user_id', None)

    def __str__(self):
        username = getattr(getattr(self.profile, 'user', None), 'username', '')
        return f'{self.name} ({username})'


class Interview(BaseModel):
    STAGE_CHOICES = [
        ('received_call', 'Received Call'),
        ('assignment', 'Assignment'),
        ('round_1', 'Round 1'),
        ('round_2', 'Round 2'),
        ('round_3', 'Round 3'),
        ('round_4', 'Round 4'),
        ('round_5', 'Round 5'),
        ('round_6', 'Round 6'),
        ('round_7', 'Round 7'),
        ('round_8', 'Round 8'),
        ('landed_job', 'Landed Job'),
    ]
    ACTION_CHOICES = [
        ('active', 'Active'),
        ('landed_job', 'Landed Job'),
        ('rejected', 'Rejected'),
        ('hold', 'Hold'),
        ('no_response', 'No Response'),
        ('no_feedback', 'No Feedback'),
        ('ghosted', 'Ghosted'),
        ('skipped', 'Skipped'),
    ]

    profile = models.ForeignKey(
        UserProfile,
        on_delete=models.CASCADE,
        related_name='interviews',
    )
    job = models.ForeignKey(
        Job,
        on_delete=models.SET_NULL,
        blank=True,
        null=True,
        related_name='interviews',
    )
    location = models.CharField(max_length=180, blank=True, default='')
    company_name = models.CharField(max_length=180)
    job_role = models.CharField(max_length=180)
    job_code = models.CharField(max_length=120, blank=True, default='')
    company_key = models.CharField(max_length=180, editable=False)
    job_role_key = models.CharField(max_length=180, editable=False)
    stage = models.CharField(max_length=40, choices=STAGE_CHOICES, default='received_call')
    action = models.CharField(max_length=40, choices=ACTION_CHOICES, default='active')
    max_round_reached = models.PositiveSmallIntegerField(default=0)
    milestone_events = models.JSONField(default=list, blank=True)
    interview_at = models.DateTimeField(blank=True, null=True)
    notes = models.TextField(blank=True)

    class Meta:
        ordering = ['-updated_at', '-created_at']
        constraints = [
            models.UniqueConstraint(fields=['profile', 'company_key', 'job_role_key'], name='uniq_interview_company_role_per_profile'),
        ]
        indexes = [
            models.Index(fields=['profile', '-updated_at']),
            models.Index(fields=['profile', 'company_key', 'job_role_key']),
        ]

    def save(self, *args, **kwargs):
        if self.job:
            if not str(self.company_name or '').strip() and self.job.company_id:
                self.company_name = str(self.job.company.name or '').strip()
            if not str(self.job_role or '').strip():
                self.job_role = str(self.job.role or '').strip() or self.job_role
            if not str(self.job_code or '').strip():
                self.job_code = str(self.job.job_id or '').strip() or self.job_code
        self.company_name = str(self.company_name or '').strip()
        self.job_role = str(self.job_role or '').strip()
        self.job_code = str(self.job_code or '').strip()
        self.company_key = self.company_name.lower()
        self.job_role_key = self.job_role.lower()
        super().save(*args, **kwargs)

    @property
    def user(self):
        return getattr(self.profile, 'user', None)

    @property
    def user_id(self):
        return getattr(self.profile, 'user_id', None)

    def __str__(self):
        return f'{self.company_name} - {self.job_role}'
