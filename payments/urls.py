from django.urls import path
from . import views

app_name = 'payments'
urlpatterns = [
    path('orders/<str:order_number>/invoice/', views.invoice, name='invoice'),
    path('orders/<str:order_number>/receipt/', views.receipt, name='receipt'),
    path('orders/<str:order_number>/retry/', views.retry, name='retry'),
    path('<uuid:transaction_uuid>/pay/', views.pay, name='pay'),
    path('<uuid:transaction_uuid>/success/', views.esewa_success, name='esewa_success'),
    path('<uuid:transaction_uuid>/failure/', views.esewa_failure, name='esewa_failure'),
    path('<uuid:transaction_uuid>/recheck/', views.recheck, name='recheck'),
    path('<uuid:transaction_uuid>/result/', views.result, name='result'),
]
