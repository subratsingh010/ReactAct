import os

from .models import UserProfile


def _profile_for_user(user):
    if not getattr(user, "is_authenticated", False):
        return None
    profile = getattr(user, "profile_info", None)
    if profile is not None:
        return profile
    return UserProfile.objects.filter(user=user).first()


def _env_text(name, default=""):
    return str(os.getenv(name, default) or "").strip()


def _env_int(name, default):
    try:
        return int(str(os.getenv(name, str(default))).strip() or default)
    except Exception:  # noqa: BLE001
        return int(default)


def _env_bool(name, default=False):
    raw = str(os.getenv(name, "true" if default else "false")).strip().lower()
    return raw in {"1", "true", "yes", "on"}


def resolve_smtp_settings(user=None):
    profile = _profile_for_user(user)
    host = str(getattr(profile, "smtp_host", "") or "").strip() if profile is not None else ""
    port = getattr(profile, "smtp_port", None) if profile is not None else None
    username = str(getattr(profile, "smtp_user", "") or "").strip() if profile is not None else ""
    password = str(getattr(profile, "smtp_password", "") or "").strip() if profile is not None else ""
    from_email = str(getattr(profile, "smtp_from_email", "") or "").strip() if profile is not None else ""
    profile_override = any([host, username, password, from_email, port is not None])
    return {
        "host": host or _env_text("SMTP_HOST"),
        "port": int(port) if port is not None else _env_int("SMTP_PORT", 587),
        "username": username or _env_text("SMTP_USER"),
        "password": password or _env_text("SMTP_PASSWORD"),
        "use_tls": bool(getattr(profile, "smtp_use_tls", True)) if profile_override and profile is not None else _env_bool("SMTP_USE_TLS", True),
        "from_email": from_email or _env_text("SMTP_FROM_EMAIL"),
    }


def resolve_imap_settings(user=None):
    profile = _profile_for_user(user)
    host = str(getattr(profile, "imap_host", "") or "").strip() if profile is not None else ""
    port = getattr(profile, "imap_port", None) if profile is not None else None
    username = str(getattr(profile, "imap_user", "") or "").strip() if profile is not None else ""
    password = str(getattr(profile, "imap_password", "") or "").strip() if profile is not None else ""
    folder = str(getattr(profile, "imap_folder", "") or "").strip() if profile is not None else ""
    return {
        "host": host or _env_text("IMAP_HOST"),
        "port": int(port) if port is not None else _env_int("IMAP_PORT", 993),
        "username": username or _env_text("IMAP_USER"),
        "password": password or _env_text("IMAP_PASSWORD"),
        "folder": folder or _env_text("IMAP_FOLDER", "INBOX") or "INBOX",
    }


def resolve_openai_settings(user=None):
    profile = _profile_for_user(user)
    api_key = str(getattr(profile, "openai_api_key", "") or "").strip() if profile is not None else ""
    model = str(getattr(profile, "openai_model", "") or "").strip() if profile is not None else ""
    task_instructions = str(getattr(profile, "ai_task_instructions", "") or "").strip() if profile is not None else ""
    return {
        "api_key": api_key or _env_text("OPENAI_API_KEY"),
        "model": model or _env_text("OPENAI_MODEL", "gpt-4o") or "gpt-4o",
        "task_instructions": task_instructions,
    }

