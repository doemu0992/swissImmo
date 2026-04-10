# crm/urls.py
from django.urls import path
from . import views

urlpatterns = [
    path('mieter/', views.mieter_liste, name='mieter_liste'),
    # NEU: Das Mieter-Dashboard
    path('mieter/<int:pk>/', views.mieter_detail, name='mieter_detail'),
]