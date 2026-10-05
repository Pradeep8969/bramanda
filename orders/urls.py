from django.urls import path
from . import views

app_name = 'orders'
urlpatterns = [
    path('', views.order_list, name='list'),
    path('<str:order_number>/success/', views.order_success, name='success'),
    path('<str:order_number>/', views.order_detail, name='detail'),
]

