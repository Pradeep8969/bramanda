from django.contrib import admin

from .models import CancellationRequest, Order, OrderEvent, OrderItem


class ReadOnlyOrderAdminMixin:
    def has_add_permission(self, request):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


class OrderItemInline(admin.TabularInline):
    model = OrderItem
    extra = 0
    can_delete = False
    readonly_fields = tuple(field.name for field in OrderItem._meta.fields)

    def has_add_permission(self, request, obj=None):
        return False


@admin.register(Order)
class OrderAdmin(ReadOnlyOrderAdminMixin, admin.ModelAdmin):
    list_display = (
        "order_number",
        "customer",
        "grand_total",
        "payment_status",
        "order_status",
        "delivery_status",
        "created_at",
    )
    list_filter = (
        "order_status",
        "payment_status",
        "delivery_status",
        "payment_method",
        "created_at",
    )
    search_fields = ("order_number", "customer__username", "email", "phone_number")
    readonly_fields = tuple(field.name for field in Order._meta.fields)
    inlines = [OrderItemInline]


@admin.register(OrderItem)
class OrderItemAdmin(ReadOnlyOrderAdminMixin, admin.ModelAdmin):
    list_display = (
        "order",
        "product_name",
        "color_name",
        "size_name",
        "quantity",
        "unit_price",
        "subtotal",
    )
    search_fields = ("order__order_number", "product_name", "sku")
    readonly_fields = tuple(field.name for field in OrderItem._meta.fields)


@admin.register(CancellationRequest, OrderEvent)
class CancellationHistoryAdmin(ReadOnlyOrderAdminMixin, admin.ModelAdmin):
    def get_readonly_fields(self, request, obj=None):
        return tuple(field.name for field in self.model._meta.fields)

    def has_change_permission(self, request, obj=None):
        return False
