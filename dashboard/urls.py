from django.urls import path
from . import views

app_name = 'dashboard'
urlpatterns = [
    path('', views.home, name='home'),
    path('orders/', views.order_list, name='orders'),
    path('orders/<str:order_number>/', views.order_detail, name='order_detail'),
    path('orders/<str:order_number>/status/', views.order_status, name='order_status'),
    path('orders/<str:order_number>/delivery/', views.delivery_status, name='delivery_status'),
    path('orders/<str:order_number>/payment/', views.payment_status, name='payment_status'),
    path('customers/', views.customers, name='customers'),
    path('inventory/', views.inventory, name='inventory'),
    path('inventory/adjust/', views.stock_adjustment, name='stock_adjustment'),
]
