"""Helpers for normalizing company names and resolving companies per user."""

from __future__ import annotations

from django.db import transaction

from .models import Company


def normalize_company_name(raw: str | None) -> str:
    """Strip edges, collapse internal whitespace, and lowercase for canonical compare/store."""
    return ' '.join(str(raw or '').split()).lower()


def find_company_by_normalized_name(user, normalized: str) -> Company | None:
    key = normalize_company_name(normalized)
    if not key:
        return None
    for company in Company.objects.filter(user=user).only('id', 'name'):
        if normalize_company_name(company.name) == key:
            return company
    return None


@transaction.atomic
def get_or_create_company_normalized(user, raw_name: str) -> tuple[Company, bool]:
    """
    Return (company, created). Name stored normalized (strip + collapse spaces + lowercase).
    Matches existing rows using the same canonical normalization.
    """
    norm = normalize_company_name(raw_name)
    if not norm:
        raise ValueError('Company name is empty.')
    existing = find_company_by_normalized_name(user, norm)
    if existing:
        # Keep DB canonical form if we only differed by spacing
        if existing.name != norm:
            existing.name = norm
            existing.save(update_fields=['name', 'updated_at'])
        return existing, False
    company = Company.objects.create(user=user, name=norm)
    return company, True


def resolve_company_for_job(user, *, company_id=None, new_company_name=None) -> Company:
    """
    Prefer new_company_name (non-empty after normalize): find or create.
    Otherwise require company_id for an existing company owned by user.
    """
    norm_new = normalize_company_name(new_company_name)
    if norm_new:
        company, _created = get_or_create_company_normalized(user, norm_new)
        return company

    cid = company_id
    if cid is None or str(cid).strip() == '':
        raise ValueError('Select a company or enter a new company name.')

    try:
        cid_int = int(cid)
    except (TypeError, ValueError):
        raise ValueError('Invalid company.') from None

    return Company.objects.get(id=cid_int, user=user)
