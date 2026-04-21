from .models import UserProfile


def ensure_profile_for_user(user):
    if not getattr(user, "is_authenticated", False):
        return None
    profile, _ = UserProfile.objects.get_or_create(
        user=user,
        defaults={
            "role": UserProfile.ROLE_ADMIN,
            "full_name": user.username,
            "email": user.email or "",
        },
    )
    update_fields = []
    if not profile.full_name:
        profile.full_name = user.username
        update_fields.append("full_name")
    if not profile.email:
        profile.email = user.email or ""
        update_fields.append("email")
    if update_fields:
        update_fields.append("updated_at")
        profile.save(update_fields=update_fields)
    return profile
