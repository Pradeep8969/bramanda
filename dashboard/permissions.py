from functools import wraps

from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied


def staff_required(view):
    """Require an authenticated, active STAFF or OWNER on every staff route."""
    @login_required
    @wraps(view)
    def wrapped(request, *args, **kwargs):
        if not request.user.is_active or request.user.role not in ('STAFF', 'OWNER'):
            raise PermissionDenied
        return view(request, *args, **kwargs)
    return wrapped


def owner_required(view):
    """Only active OWNER accounts; superuser flags never bypass the role."""
    @login_required
    @wraps(view)
    def wrapped(request, *args, **kwargs):
        if not request.user.is_active or request.user.role != 'OWNER':
            raise PermissionDenied
        return view(request, *args, **kwargs)
    return wrapped
