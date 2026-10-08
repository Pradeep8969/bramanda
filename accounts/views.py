from django.contrib import messages
from django.contrib.auth import login
from django.contrib.auth.decorators import login_required
from django.contrib.auth.views import LoginView, LogoutView
from django.shortcuts import redirect, render
from django.urls import reverse_lazy
from django.views.decorators.http import require_http_methods

from .forms import ProfileForm, RegistrationForm
from .emails import schedule_welcome_email


@require_http_methods(['GET', 'POST'])
def register(request):
    if request.user.is_authenticated:
        return redirect('accounts:profile')
    form = RegistrationForm(request.POST if request.method == 'POST' else None)
    if request.method == 'POST' and form.is_valid():
        user = form.save()
        schedule_welcome_email(user)
        login(request, user, backend='django.contrib.auth.backends.ModelBackend')
        messages.success(request, 'Welcome to BRAMANDA! Your customer account is ready.')
        return redirect('products:shop')
    return render(request, 'accounts/register.html', {'form': form})


class CustomerLoginView(LoginView):
    template_name = 'accounts/login.html'
    redirect_authenticated_user = True

    def form_valid(self, form):
        messages.success(self.request, 'Welcome back to BRAMANDA.')
        return super().form_valid(form)


class CustomerLogoutView(LogoutView):
    next_page = reverse_lazy('home')

    def post(self, request, *args, **kwargs):
        response = super().post(request, *args, **kwargs)
        messages.success(request, 'You have been logged out.')
        return response


@login_required
@require_http_methods(['GET', 'POST'])
def profile(request):
    form = ProfileForm(request.POST if request.method == 'POST' else None, instance=request.user)
    if request.method == 'POST' and form.is_valid():
        form.save()
        messages.success(request, 'Your profile has been updated.')
        return redirect('accounts:profile')
    return render(request, 'accounts/profile.html', {'form': form})

