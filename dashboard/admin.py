from django.contrib import admin
from .models import StaffActivity


@admin.register(StaffActivity)
class StaffActivityAdmin(admin.ModelAdmin):
    list_display = ('staff', 'action', 'reference', 'created_at')
    list_filter = ('action', 'created_at')
    search_fields = ('staff__username', 'reference', 'description')
    readonly_fields = ('staff', 'action', 'description', 'reference', 'created_at')

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False
