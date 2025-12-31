from django.contrib import admin
from django.urls import path
from django.conf import settings
from django.conf.urls.static import static

# Views importieren
from core.views import generate_pdf_view, schaden_melden_public, schaden_erfolg

urlpatterns = [
    path('admin/', admin.site.urls),
    
    # PDF Drucken
    path('drucken/<uuid:vertrag_id>/', generate_pdf_view, name='pdf_download'),
    
    # Öffentliche Schadensmeldung
    path('melden/', schaden_melden_public, name='schaden_melden'),
    path('melden/danke/', schaden_erfolg, name='schaden_erfolg'),
]

# Medien im Entwicklungsmodus ausliefern
if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
    urlpatterns += static(settings.STATIC_URL, document_root=settings.STATIC_ROOT)
