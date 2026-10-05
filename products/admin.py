from django.contrib import admin

from .models import Category, Color, Product, ProductImage, ProductVariant, Size


@admin.register(Category)
class CategoryAdmin(admin.ModelAdmin):
    list_display = ('name', 'slug', 'is_active')
    search_fields = ('name',)
    list_filter = ('is_active',)
    prepopulated_fields = {'slug': ('name',)}


@admin.register(Size)
class SizeAdmin(admin.ModelAdmin):
    list_display = ('name', 'display_order', 'is_active')
    search_fields = ('name',)
    list_filter = ('is_active',)


@admin.register(Color)
class ColorAdmin(admin.ModelAdmin):
    list_display = ('name', 'hex_code', 'is_active')
    search_fields = ('name',)
    list_filter = ('is_active',)


class ProductImageInline(admin.TabularInline):
    model = ProductImage
    extra = 1


class ProductVariantInline(admin.TabularInline):
    model = ProductVariant
    extra = 0
    readonly_fields = ('stock_quantity',)


@admin.register(Product)
class ProductAdmin(admin.ModelAdmin):
    list_display = ('name', 'category', 'price', 'is_active', 'featured')
    search_fields = ('name', 'description')
    list_filter = ('category', 'is_active', 'featured')
    list_select_related = ('category',)
    prepopulated_fields = {'slug': ('name',)}
    inlines = (ProductImageInline, ProductVariantInline)


@admin.register(ProductImage)
class ProductImageAdmin(admin.ModelAdmin):
    list_display = ('product', 'alt_text', 'display_order')
    search_fields = ('product__name', 'alt_text')
    list_select_related = ('product',)


@admin.register(ProductVariant)
class ProductVariantAdmin(admin.ModelAdmin):
    list_display = ('sku', 'product', 'size', 'color', 'stock_quantity', 'is_active')
    search_fields = ('sku', 'product__name')
    list_filter = ('is_active', 'size', 'color')
    list_select_related = ('product', 'size', 'color')
    readonly_fields = ('stock_quantity', 'created_at', 'updated_at')
