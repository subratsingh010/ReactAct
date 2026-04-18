from django.contrib import admin

from .models import Resume, UserProfile


@admin.register(Resume)
class ResumeAdmin(admin.ModelAdmin):
    list_display = ("id", "title", "user", "is_default", "is_tailored", "status", "updated_at")
    list_filter = ("is_default", "is_tailored", "status")
    search_fields = ("title", "user__username", "user__email")


@admin.register(UserProfile)
class UserProfileAdmin(admin.ModelAdmin):
    list_display = ("id", "user", "role", "full_name", "email", "current_employer", "updated_at")
    list_filter = ("role",)
    search_fields = ("user__username", "user__email", "full_name", "email", "current_employer")
    autocomplete_fields = ("user",)
