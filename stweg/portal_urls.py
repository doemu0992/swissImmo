from django.urls import path

from stweg import portal as p

urlpatterns = [
    path('', p.portal_stweg, name='portal_stweg'),
    path('einladung/<int:pk>/', p.portal_stweg_einladung, name='portal_stweg_einladung'),
    path('protokoll/<int:pk>/', p.portal_stweg_protokoll, name='portal_stweg_protokoll'),
    path('abrechnung/<int:pk>/', p.portal_stweg_abrechnung, name='portal_stweg_abrechnung'),
    path('vollmacht/<int:pk>/erteilen/', p.portal_stweg_vollmacht, name='portal_stweg_vollmacht'),
    path('vollmacht/<int:pk>/widerrufen/', p.portal_stweg_vollmacht_widerruf, name='portal_stweg_vollmacht_widerruf'),
    path('abstimmen/<int:pk>/', p.portal_stweg_abstimmen, name='portal_stweg_abstimmen'),
    path('zirkular/<int:pk>/', p.portal_stweg_zirkular, name='portal_stweg_zirkular'),
    path('anfrage/<int:stweg_id>/', p.portal_stweg_anfrage, name='portal_stweg_anfrage'),
    path('dokument/<int:pk>/', p.portal_stweg_dokument, name='portal_stweg_dokument'),
    path('akonto/<int:pk>/', p.portal_stweg_akonto, name='portal_stweg_akonto'),
    path('teilnehmen/<int:pk>/', p.portal_stweg_teilnehmen, name='portal_stweg_teilnehmen'),
    path('evoting/<int:pk>/', p.portal_stweg_evoting, name='portal_stweg_evoting'),
]
