from django.contrib import admin

from .models import InventoryTransaction


@admin.register(InventoryTransaction)
class InventoryTransactionAdmin(admin.ModelAdmin):
    list_display = ('variant', 'transaction_type', 'quantity', 'previous_stock', 'new_stock', 'created_by', 'created_at')
    list_filter = ('transaction_type', 'created_at')
    search_fields = ('variant__sku', 'variant__product__name', 'reference', 'note')
    list_select_related = ('variant__product', 'variant__size', 'variant__color', 'created_by')
    readonly_fields = ('variant', 'transaction_type', 'quantity', 'previous_stock', 'new_stock', 'reference', 'note', 'created_by', 'created_at')
    date_hierarchy = 'created_at'

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False
