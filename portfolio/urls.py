# portfolio/urls.py
from django.urls import path
from . import views

urlpatterns = [
    # Liste aller Liegenschaften
    path('liegenschaften/', views.liegenschaft_liste, name='liegenschaft_liste'),

    # NEU: Detailansicht einer spezifischen Liegenschaft (SaaS-Dashboard)
    path('liegenschaften/<int:pk>/', views.liegenschaft_detail, name='liegenschaft_detail'),
]