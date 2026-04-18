from django.db.models import Q

from .models import Template, UserProfile


def ensure_template_profile_for_user(user):
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


def template_queryset_for_user(user):
    if not getattr(user, "is_authenticated", False):
        return Template.objects.none()
    profile = ensure_template_profile_for_user(user)
    scope = Q(template_scope=Template.TEMPLATE_SCOPE_SYSTEM)
    if profile is not None:
        scope = scope | Q(profile=profile, template_scope=Template.TEMPLATE_SCOPE_USER_BASED)
    return Template.objects.filter(scope).select_related("profile__user")


def owned_template_queryset_for_user(user):
    profile = ensure_template_profile_for_user(user)
    if profile is None:
        return Template.objects.none()
    return Template.objects.filter(profile=profile, template_scope=Template.TEMPLATE_SCOPE_USER_BASED).select_related("profile__user")


def resolve_template_ids_for_user(user, template_ids):
    if not template_ids:
        return []
    rows = list(template_queryset_for_user(user).filter(id__in=template_ids))
    row_map = {str(item.id): item for item in rows}
    return [row_map[item_id] for item_id in template_ids if item_id in row_map]


def resolve_intro_template_for_user(user, template_id, category):
    template_id_text = str(template_id or "").strip()
    category_text = str(category or "general").strip().lower() or "general"
    if not template_id_text:
        return None
    return template_queryset_for_user(user).filter(id=template_id_text, category=category_text).first()
