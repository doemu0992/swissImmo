# crm/urls.py
from django.urls import path
from . import views

urlpatterns = [
    path('mieter/', views.mieter_liste, name='mieter_liste'),
    path('mieter/<int:pk>/', views.mieter_detail, name='mieter_detail'),
    # NEU: Das Einstellungs-Zentrum
    path('settings/', views.settings_view, name='settings'),
]