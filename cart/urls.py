from django.urls import path
from . import views

app_name = 'cart'
urlpatterns = [
    path('', views.cart_detail, name='detail'),
    path('add/<slug:slug>/', views.add_item, name='add'),
    path('update/<int:item_id>/', views.update_item, name='update'),
    path('remove/<int:item_id>/', views.remove_item, name='remove'),
]

