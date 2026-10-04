from django.urls import path

from stweg import portal as p

urlpatterns = [
    path('', p.portal_stweg, name='portal_stweg'),
    path('einladung/<int:pk>/', p.portal_stweg_einladung, name='portal_stweg_einladung'),
    path('protokoll/<int:pk>/', p.portal_stweg_protokoll, name='portal_stweg_protokoll'),
    path('abrechnung/<int:pk>/', p.portal_stweg_abrechnung, name='portal_stweg_abrechnung'),
    path('anfrage/<int:stweg_id>/', p.portal_stweg_anfrage, name='portal_stweg_anfrage'),
]
