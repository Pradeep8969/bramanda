from django.urls import path
from . import owner_views as views

app_name = 'owner'
urlpatterns = [
    path('', views.home, name='home'),
    path('reports/', views.reports, name='reports'),
    path('staff/', views.staff_list, name='staff'),
    path('staff/add/', views.staff_edit, name='staff_add'),
    path('staff/<int:pk>/edit/', views.staff_edit, name='staff_edit'),
    path('staff/<int:pk>/toggle/', views.staff_toggle, name='staff_toggle'),
    path('payments/', views.payments, name='payments'),
    path('activity/', views.activity, name='activity'),
    path('customers/', views.customers, name='customers'),
    path('inventory/', views.inventory, name='inventory'),
    path('inventory/adjust/', views.stock_adjustment, name='stock_adjustment'),
    path('orders/', views.order_list, name='orders'),
    path('orders/<str:order_number>/', views.order_detail, name='order_detail'),
    path('orders/<str:order_number>/status/', views.order_status, name='order_status'),
    path('orders/<str:order_number>/delivery/', views.delivery_status, name='delivery_status'),
    path('orders/<str:order_number>/payment/', views.payment_status, name='payment_status'),
]
for kind in views.CATALOG:
    urlpatterns += [
        path(f'{kind}/', views.catalog_list, {'kind': kind}, name=kind),
        path(f'{kind}/add/', views.catalog_edit, {'kind': kind}, name=kind + '_add'),
        path(f'{kind}/<int:pk>/edit/', views.catalog_edit, {'kind': kind}, name=kind + '_edit'),
        path(f'{kind}/<int:pk>/toggle/', views.catalog_toggle, {'kind': kind}, name=kind + '_toggle'),
    ]
