# tickets/urls.py
from django.urls import path
from . import views

urlpatterns = [
    path('dashboard/', views.ticket_liste, name='ticket_liste'),
    path('ticket/<int:pk>/', views.ticket_detail, name='ticket_detail'),
]