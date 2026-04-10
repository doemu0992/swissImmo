# rentals/urls.py
from django.urls import path
from . import views

urlpatterns = [
    path('vertraege/', views.mietvertrag_liste, name='mietvertrag_liste'),
    path('vertraege/<int:pk>/', views.mietvertrag_detail, name='mietvertrag_detail'),
]