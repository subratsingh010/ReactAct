import logging

from django.conf import settings
from rest_framework import status
from rest_framework.response import Response
from rest_framework.views import exception_handler as drf_exception_handler


logger = logging.getLogger(__name__)


def _stringify(value):
    if value is None:
        return ''
    text = str(value).strip()
    return text


def _flatten_errors(payload, out=None):
    if out is None:
        out = []
    if payload is None:
        return out
    if isinstance(payload, (str, int, float, bool)):
        text = _stringify(payload)
        if text:
            out.append(text)
        return out
    if isinstance(payload, list):
        for item in payload:
            _flatten_errors(item, out)
        return out
    if isinstance(payload, dict):
        for key, value in payload.items():
            if isinstance(value, (str, int, float, bool)):
                text = _stringify(value)
                if text:
                    out.append(f'{key}: {text}')
            elif isinstance(value, list):
                for item in value:
                    text = _stringify(item)
                    if text:
                        out.append(f'{key}: {text}')
            else:
                _flatten_errors(value, out)
        return out
    return out


def custom_exception_handler(exc, context):
    response = drf_exception_handler(exc, context)

    if response is not None:
        payload = response.data
        detail = ''
        if isinstance(payload, dict):
            detail = _stringify(payload.get('detail') or payload.get('message'))
        if not detail:
            flat = _flatten_errors(payload)
            detail = ' | '.join(flat) if flat else 'Request failed.'

        warning = ''
        if isinstance(payload, dict):
            warning = _stringify(payload.get('warning') or payload.get('warnings'))

        wrapped = {
            'detail': detail,
            'message': detail,
            'status_code': response.status_code,
            'errors': payload,
        }
        if warning:
            wrapped['warning'] = warning
        response.data = wrapped
        return response

    view_name = ''
    view = context.get('view')
    if view is not None:
        view_name = view.__class__.__name__
    logger.exception('Unhandled API exception in %s: %s', view_name, exc)

    debug_mode = bool(getattr(settings, 'DEBUG', False))
    message = _stringify(exc) if debug_mode else 'Internal server error.'
    return Response(
        {
            'detail': message,
            'message': message,
            'status_code': status.HTTP_500_INTERNAL_SERVER_ERROR,
        },
        status=status.HTTP_500_INTERNAL_SERVER_ERROR,
    )
