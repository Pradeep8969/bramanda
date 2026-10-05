from django.contrib import admin
from django.contrib.auth.admin import UserAdmin

from .models import User


@admin.register(User)
class BramandaUserAdmin(UserAdmin):
    fieldsets = UserAdmin.fieldsets + (
        ('Bramanda details', {'fields': ('role', 'phone_number', 'address')}),
    )
    add_fieldsets = UserAdmin.add_fieldsets + (
        ('Bramanda details', {'fields': ('role', 'phone_number', 'address')}),
    )
    list_display = UserAdmin.list_display + ('role', 'phone_number')
    list_filter = UserAdmin.list_filter + ('role',)
