"""Expose allauth account/social routes without password recovery endpoints."""
from allauth.urls import urlpatterns as allauth_urlpatterns
from django.urls import URLPattern, URLResolver


def without_password_recovery(patterns):
    result = []
    for pattern in patterns:
        if isinstance(pattern, URLPattern):
            if 'password/reset' in str(pattern.pattern):
                continue
            result.append(pattern)
        elif isinstance(pattern, URLResolver):
            # Construct a separate resolver; never mutate allauth's URL modules.
            result.append(URLResolver(
                pattern.pattern, without_password_recovery(pattern.url_patterns),
                default_kwargs=pattern.default_kwargs,
                app_name=pattern.app_name, namespace=pattern.namespace,
            ))
    return result


urlpatterns = without_password_recovery(allauth_urlpatterns)
