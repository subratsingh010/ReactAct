import logging

from django.db.models import Q
from rest_framework import status
from rest_framework.permissions import SAFE_METHODS, DjangoModelPermissions
from rest_framework.response import Response

from .models import Company, Employee, Job, Template, Tracking, UserProfile


GLOBAL_VIEW_ALL_JOB_PERMISSION = 'analyzer.view_all_job'
logger = logging.getLogger(__name__)

RESOURCE_MODEL_MAP = {
    'company': Company,
    'employee': Employee,
    'job': Job,
    'template': Template,
    'tracking': Tracking,
}
ACTION_PERMISSION_MAP = {
    'add': 'add',
    'edit': 'change',
    'delete': 'delete',
}
METHOD_ACTION_MAP = {
    'POST': 'add',
    'PUT': 'edit',
    'PATCH': 'edit',
    'DELETE': 'delete',
}


def _resource_label(resource):
    return str(resource or 'resource').strip().lower() or 'resource'


def _action_label(action):
    return str(action or 'manage').strip().lower() or 'manage'


def _user_profile_role(user):
    if not getattr(user, 'is_authenticated', False):
        return ''
    try:
        profile = user.profile_info
    except UserProfile.DoesNotExist:
        profile = None
    if profile is None:
        return UserProfile.ROLE_ADMIN
    role = str(getattr(profile, 'role', '') or '').strip().lower()
    allowed = {choice[0] for choice in UserProfile.ROLE_CHOICES}
    return role if role in allowed else UserProfile.ROLE_ADMIN


def _permission_codename_for(resource, action):
    model = RESOURCE_MODEL_MAP.get(_resource_label(resource))
    perm_action = ACTION_PERMISSION_MAP.get(_action_label(action))
    if model is None or perm_action is None:
        return ''
    return f'{model._meta.app_label}.{perm_action}_{model._meta.model_name}'


def _log_unauthorized_access(request, *, resource, action, reason):
    user = getattr(request, 'user', None)
    logger.warning(
        'RBAC denied %s on %s for user_id=%s username=%s path=%s reason=%s',
        _action_label(action),
        _resource_label(resource),
        getattr(user, 'id', None),
        getattr(user, 'username', ''),
        getattr(request, 'path', ''),
        str(reason or '').strip(),
    )


def _role_denied_message(resource, action):
    return f'Your role does not allow you to {_action_label(action)} {_resource_label(resource)} records.'


def _permission_denied_message(resource, action):
    return f'You do not have permission to {_action_label(action)} {_resource_label(resource)} records.'


def _role_grants_resource_management(user, resource):
    role = _user_profile_role(user)
    if role in {UserProfile.ROLE_ADMIN, UserProfile.ROLE_SUPERADMIN} and _resource_label(resource) == 'template':
        return True
    return False


def user_can_manage_resource(user, resource, action):
    if not getattr(user, 'is_authenticated', False):
        return False, 'Authentication required.'
    if _user_profile_role(user) == UserProfile.ROLE_READ_ONLY:
        return False, _role_denied_message(resource, action)
    if bool(getattr(user, 'is_superuser', False)):
        return True, ''
    if _role_grants_resource_management(user, resource):
        return True, ''
    codename = _permission_codename_for(resource, action)
    if codename and user.has_perm(codename):
        return True, ''
    if codename:
        return False, _permission_denied_message(resource, action)
    return False, 'Permission configuration error.'


def ensure_resource_management_allowed(request, *, resource, action):
    allowed, detail = user_can_manage_resource(getattr(request, 'user', None), resource, action)
    if allowed:
        return None
    _log_unauthorized_access(request, resource=resource, action=action, reason=detail)
    return Response({'detail': detail}, status=status.HTTP_403_FORBIDDEN)


def resource_permission_flags(user, resource):
    return {
        'can_add': user_can_manage_resource(user, resource, 'add')[0],
        'can_edit': user_can_manage_resource(user, resource, 'edit')[0],
        'can_delete': user_can_manage_resource(user, resource, 'delete')[0],
    }


def build_owned_or_assigned_q(
    user,
    *,
    created_by_field='created_by_id',
    assigned_to_field='assigned_to__id',
    owner_user_field=None,
    extra_owner_ids=None,
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
        for owner_id in extra_owner_ids or []:
            query |= Q(**{owner_user_field: owner_id})
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


def object_matches_access(
    user,
    obj,
    *,
    created_by_attr='created_by_id',
    assigned_to_attr='assigned_to',
    owner_user_attr='user_id',
    extra_owner_ids=None,
):
    if not getattr(user, 'is_authenticated', False):
        return False
    if bool(getattr(user, 'is_superuser', False)):
        return True
    if created_by_attr and getattr(obj, created_by_attr, None) == user.id:
        return True
    if owner_user_attr and getattr(obj, owner_user_attr, None) == user.id:
        return True
    if owner_user_attr and getattr(obj, owner_user_attr, None) in set(extra_owner_ids or []):
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
    managed_resource = ''

    def has_global_read_access(self, request, view, obj=None):
        user = request.user
        if bool(getattr(user, 'is_superuser', False)):
            return True
        return bool(self.global_view_perm) and user.has_perm(self.global_view_perm)

    def has_permission(self, request, view):
        if request.method not in SAFE_METHODS and self.managed_resource:
            role = _user_profile_role(request.user)
            if role == UserProfile.ROLE_READ_ONLY:
                detail = _role_denied_message(self.managed_resource, METHOD_ACTION_MAP.get(request.method, 'edit'))
                self.message = detail
                _log_unauthorized_access(
                    request,
                    resource=self.managed_resource,
                    action=METHOD_ACTION_MAP.get(request.method, 'edit'),
                    reason=detail,
                )
                return False
        allowed = super().has_permission(request, view)
        if not allowed and request.method not in SAFE_METHODS and self.managed_resource:
            detail = _permission_denied_message(self.managed_resource, METHOD_ACTION_MAP.get(request.method, 'edit'))
            self.message = detail
            _log_unauthorized_access(
                request,
                resource=self.managed_resource,
                action=METHOD_ACTION_MAP.get(request.method, 'edit'),
                reason=detail,
            )
        return allowed

    def has_object_permission(self, request, view, obj):
        if request.method in SAFE_METHODS and self.has_global_read_access(request, view, obj=obj):
            return True
        return self.user_can_access_object(request.user, obj, for_write=request.method not in SAFE_METHODS)

    def user_can_access_object(self, user, obj, *, for_write=False):
        raise NotImplementedError

    def filter_queryset_for_user(self, user, queryset, *, for_write=False):
        raise NotImplementedError


def is_job_owner_or_assignee(job, user, *, for_write=False):
    return object_matches_access(
        user,
        job,
        created_by_attr='created_by_id',
        assigned_to_attr='assigned_to',
        owner_user_attr='user_id',
        extra_owner_ids=[],
    )


def filter_jobs_for_user(user, queryset=None, *, for_write=False):
    rows = queryset if queryset is not None else Job.objects.all()
    access_q = build_owned_or_assigned_q(
        user,
        created_by_field='created_by_id',
        assigned_to_field='assigned_to__id',
        owner_user_field='company__profile__user_id',
        extra_owner_ids=[],
    )
    return filter_queryset_by_access(
        user,
        rows,
        access_q=access_q,
        global_view_perm='' if for_write else GLOBAL_VIEW_ALL_JOB_PERMISSION,
    )


class JobAccessPermission(OwnershipModelPermissions):
    global_view_perm = GLOBAL_VIEW_ALL_JOB_PERMISSION
    managed_resource = 'job'

    def user_can_access_object(self, user, obj, *, for_write=False):
        return is_job_owner_or_assignee(obj, user, for_write=for_write)

    def filter_queryset_for_user(self, user, queryset, *, for_write=False):
        return filter_jobs_for_user(user, queryset, for_write=for_write)


def is_company_owner(company, user, *, for_write=False):
    return object_matches_access(
        user,
        company,
        created_by_attr=None,
        assigned_to_attr=None,
        owner_user_attr='user_id',
        extra_owner_ids=[],
    )


def filter_companies_for_user(user, queryset=None, *, for_write=False):
    rows = queryset if queryset is not None else Company.objects.all()
    access_q = build_owned_or_assigned_q(
        user,
        created_by_field=None,
        assigned_to_field=None,
        owner_user_field='profile__user_id',
        extra_owner_ids=[],
    )
    return filter_queryset_by_access(
        user,
        rows,
        access_q=access_q,
    )


class CompanyAccessPermission(OwnershipModelPermissions):
    managed_resource = 'company'

    def user_can_access_object(self, user, obj, *, for_write=False):
        return is_company_owner(obj, user, for_write=for_write)

    def filter_queryset_for_user(self, user, queryset, *, for_write=False):
        return filter_companies_for_user(user, queryset, for_write=for_write)


def is_employee_owner(employee, user, *, for_write=False):
    return object_matches_access(
        user,
        employee,
        created_by_attr=None,
        assigned_to_attr=None,
        owner_user_attr='user_id',
        extra_owner_ids=[],
    )


def filter_employees_for_user(user, queryset=None, *, for_write=False):
    rows = queryset if queryset is not None else Employee.objects.all()
    access_q = build_owned_or_assigned_q(
        user,
        created_by_field=None,
        assigned_to_field=None,
        owner_user_field='owner_profile__user_id',
        extra_owner_ids=[],
    )
    return filter_queryset_by_access(
        user,
        rows,
        access_q=access_q,
    )


class EmployeeAccessPermission(OwnershipModelPermissions):
    managed_resource = 'employee'

    def user_can_access_object(self, user, obj, *, for_write=False):
        return is_employee_owner(obj, user, for_write=for_write)

    def filter_queryset_for_user(self, user, queryset, *, for_write=False):
        return filter_employees_for_user(user, queryset, for_write=for_write)
