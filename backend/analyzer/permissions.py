from django.db.models import Q
from rest_framework.permissions import SAFE_METHODS, DjangoModelPermissions

from .models import Company, Employee, Job


GLOBAL_VIEW_ALL_JOB_PERMISSION = 'analyzer.view_all_job'


def build_owned_or_assigned_q(
    user,
    *,
    created_by_field='created_by_id',
    assigned_to_field='assigned_to__id',
    owner_user_field=None,
):
    if not getattr(user, 'is_authenticated', False):
        return Q(pk__in=[])

    query = Q(pk__in=[])
    if created_by_field:
        query |= Q(**{created_by_field: user.id})
    if assigned_to_field:
        query |= Q(**{assigned_to_field: user.id})
    if owner_user_field:
        query |= Q(**{owner_user_field: user.id})
    return query


def filter_queryset_by_access(user, queryset, *, access_q, global_view_perm=''):
    rows = queryset
    if not getattr(user, 'is_authenticated', False):
        return rows.none()
    if bool(getattr(user, 'is_superuser', False)):
        return rows.distinct()
    if global_view_perm and user.has_perm(global_view_perm):
        return rows.distinct()
    return rows.filter(access_q).distinct()


def object_matches_access(user, obj, *, created_by_attr='created_by_id', assigned_to_attr='assigned_to', owner_user_attr='user_id'):
    if not getattr(user, 'is_authenticated', False):
        return False
    if bool(getattr(user, 'is_superuser', False)):
        return True
    if created_by_attr and getattr(obj, created_by_attr, None) == user.id:
        return True
    if owner_user_attr and getattr(obj, owner_user_attr, None) == user.id:
        return True
    assigned_manager = getattr(obj, assigned_to_attr, None) if assigned_to_attr else None
    if assigned_manager is None:
        return False
    filter_method = getattr(assigned_manager, 'filter', None)
    if callable(filter_method):
        return assigned_manager.filter(id=user.id).exists()
    return False


class OwnershipModelPermissions(DjangoModelPermissions):
    perms_map = DjangoModelPermissions.perms_map.copy()
    perms_map['GET'] = ['%(app_label)s.view_%(model_name)s']
    perms_map['OPTIONS'] = []
    perms_map['HEAD'] = []

    global_view_perm = ''

    def has_global_read_access(self, request, view, obj=None):
        user = request.user
        if bool(getattr(user, 'is_superuser', False)):
            return True
        return bool(self.global_view_perm) and user.has_perm(self.global_view_perm)

    def has_object_permission(self, request, view, obj):
        if request.method in SAFE_METHODS and self.has_global_read_access(request, view, obj=obj):
            return True
        return self.user_can_access_object(request.user, obj, for_write=request.method not in SAFE_METHODS)

    def user_can_access_object(self, user, obj, *, for_write=False):
        raise NotImplementedError

    def filter_queryset_for_user(self, user, queryset, *, for_write=False):
        raise NotImplementedError


def is_job_owner_or_assignee(job, user):
    return object_matches_access(
        user,
        job,
        created_by_attr='created_by_id',
        assigned_to_attr='assigned_to',
        owner_user_attr='user_id',
    )


def filter_jobs_for_user(user, queryset=None, *, for_write=False):
    rows = queryset if queryset is not None else Job.objects.all()
    access_q = build_owned_or_assigned_q(
        user,
        created_by_field='created_by_id',
        assigned_to_field='assigned_to__id',
        owner_user_field='company__profile__user_id',
    )
    return filter_queryset_by_access(
        user,
        rows,
        access_q=access_q,
        global_view_perm='' if for_write else GLOBAL_VIEW_ALL_JOB_PERMISSION,
    )


class JobAccessPermission(OwnershipModelPermissions):
    global_view_perm = GLOBAL_VIEW_ALL_JOB_PERMISSION

    def user_can_access_object(self, user, obj, *, for_write=False):
        return is_job_owner_or_assignee(obj, user)

    def filter_queryset_for_user(self, user, queryset, *, for_write=False):
        return filter_jobs_for_user(user, queryset, for_write=for_write)


def is_company_owner(company, user):
    return object_matches_access(
        user,
        company,
        created_by_attr=None,
        assigned_to_attr=None,
        owner_user_attr='user_id',
    )


def filter_companies_for_user(user, queryset=None, *, for_write=False):
    rows = queryset if queryset is not None else Company.objects.all()
    access_q = build_owned_or_assigned_q(
        user,
        created_by_field=None,
        assigned_to_field=None,
        owner_user_field='profile__user_id',
    )
    return filter_queryset_by_access(
        user,
        rows,
        access_q=access_q,
    )


class CompanyAccessPermission(OwnershipModelPermissions):
    def user_can_access_object(self, user, obj, *, for_write=False):
        return is_company_owner(obj, user)

    def filter_queryset_for_user(self, user, queryset, *, for_write=False):
        return filter_companies_for_user(user, queryset, for_write=for_write)


def is_employee_owner(employee, user):
    return object_matches_access(
        user,
        employee,
        created_by_attr=None,
        assigned_to_attr=None,
        owner_user_attr='user_id',
    )


def filter_employees_for_user(user, queryset=None, *, for_write=False):
    rows = queryset if queryset is not None else Employee.objects.all()
    access_q = build_owned_or_assigned_q(
        user,
        created_by_field=None,
        assigned_to_field=None,
        owner_user_field='owner_profile__user_id',
    )
    return filter_queryset_by_access(
        user,
        rows,
        access_q=access_q,
    )


class EmployeeAccessPermission(OwnershipModelPermissions):
    def user_can_access_object(self, user, obj, *, for_write=False):
        return is_employee_owner(obj, user)

    def filter_queryset_for_user(self, user, queryset, *, for_write=False):
        return filter_employees_for_user(user, queryset, for_write=for_write)
