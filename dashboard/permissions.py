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
