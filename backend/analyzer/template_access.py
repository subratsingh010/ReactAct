from .profile_utils import ensure_profile_for_user
from .default_mail_templates import ensure_default_mail_templates_for_profile
from .models import SubjectTemplate, Template


def ensure_template_profile_for_user(user):
    profile = ensure_profile_for_user(user)
    ensure_default_mail_templates_for_profile(profile)
    return profile


def template_queryset_for_user(user):
    return owned_template_queryset_for_user(user)


def owned_template_queryset_for_user(user):
    profile = ensure_template_profile_for_user(user)
    if profile is None:
        return Template.objects.none()
    return Template.objects.filter(profile=profile, template_scope=Template.TEMPLATE_SCOPE_USER_BASED).select_related("profile__user")


def resolve_template_ids_for_user(user, template_ids):
    if not template_ids:
        return []
    rows = list(template_queryset_for_user(user).filter(id__in=template_ids))
    missing_ids = [item_id for item_id in template_ids if item_id not in {str(row.id) for row in rows}]
    if missing_ids:
        # Compatibility safety: older tracking rows may still reference legacy shared templates.
        rows.extend(
            list(
                Template.objects.filter(
                    id__in=missing_ids,
                    template_scope=Template.TEMPLATE_SCOPE_SYSTEM,
                ).select_related("profile__user")
            )
        )
    row_map = {str(item.id): item for item in rows}
    return [row_map[item_id] for item_id in template_ids if item_id in row_map]


def resolve_intro_template_for_user(user, template_id, category):
    template_id_text = str(template_id or "").strip()
    category_text = str(category or "general").strip().lower() or "general"
    if not template_id_text:
        return None
    return template_queryset_for_user(user).filter(id=template_id_text, category=category_text).first()


def subject_template_queryset_for_user(user):
    profile = ensure_template_profile_for_user(user)
    if profile is None:
        return SubjectTemplate.objects.none()
    return SubjectTemplate.objects.filter(profile=profile).select_related("profile__user")


def owned_subject_template_queryset_for_user(user):
    profile = ensure_template_profile_for_user(user)
    if profile is None:
        return SubjectTemplate.objects.none()
    return SubjectTemplate.objects.filter(profile=profile).select_related("profile__user")
