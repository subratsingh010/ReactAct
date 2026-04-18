from django.contrib import admin

from .models import Job, Resume, Template, SubjectTemplate, UserProfile


@admin.register(Resume)
class ResumeAdmin(admin.ModelAdmin):
    list_display = ("id", "title", "user", "is_default", "is_tailored", "status", "updated_at")
    list_filter = ("is_default", "is_tailored", "status")
    search_fields = ("title", "user__username", "user__email")


@admin.register(UserProfile)
class UserProfileAdmin(admin.ModelAdmin):
    list_display = ("id", "user", "role", "full_name", "email", "current_employer", "updated_at")
    list_filter = ("role",)
    search_fields = ("user__username", "user__email", "full_name", "email", "current_employer", "smtp_host", "imap_host", "openai_model")
    autocomplete_fields = ("user",)
    fieldsets = (
        (None, {"fields": ("user", "role", "full_name", "email", "contact_number")}),
        ("Profile", {"fields": ("linkedin_url", "github_url", "portfolio_url", "resume_link", "current_employer", "years_of_experience", "summary")}),
        ("Location", {"fields": ("address_line_1", "address_line_2", "state", "country", "country_code", "location", "location_ref", "preferred_locations")}),
        ("SMTP", {"fields": ("smtp_host", "smtp_port", "smtp_user", "smtp_password", "smtp_use_tls", "smtp_from_email")}),
        ("IMAP", {"fields": ("imap_host", "imap_port", "imap_user", "imap_password", "imap_folder")}),
        ("OpenAI", {"fields": ("openai_api_key", "openai_model", "ai_task_instructions")}),
    )
    filter_horizontal = ("preferred_locations",)


@admin.register(Job)
class JobAdmin(admin.ModelAdmin):
    list_display = ("id", "job_id", "role", "company", "created_by", "is_closed", "is_removed", "updated_at")
    list_filter = ("is_closed", "is_removed")
    search_fields = ("job_id", "role", "company__name", "created_by__username", "assigned_to__username")
    filter_horizontal = ("assigned_to",)


@admin.register(Template)
class TemplateAdmin(admin.ModelAdmin):
    list_display = ("id", "name", "template_scope", "category", "profile", "template_owner", "updated_at")
    list_filter = ("template_scope", "category")
    search_fields = ("name", "achievement", "profile__user__username", "profile__user__email")
    autocomplete_fields = ("profile",)

    def template_owner(self, obj):
        return getattr(getattr(obj.profile, "user", None), "username", "") or "system"

    template_owner.short_description = "Owner"


@admin.register(SubjectTemplate)
class SubjectTemplateAdmin(admin.ModelAdmin):
    list_display = ("id", "name", "category", "profile", "subject_owner", "updated_at")
    list_filter = ("category",)
    search_fields = ("name", "subject", "profile__user__username", "profile__user__email")
    autocomplete_fields = ("profile",)

    def subject_owner(self, obj):
        return getattr(getattr(obj.profile, "user", None), "username", "")

    subject_owner.short_description = "Owner"
