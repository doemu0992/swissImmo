# finance/urls.py
from django.urls import path
from . import views

urlpatterns = [
    path('abrechnungen/', views.abrechnung_liste, name='abrechnung_liste'),
    path('abrechnung/<int:pk>/', views.abrechnung_detail, name='abrechnung_detail'),
]