from django.urls import path
from . import views

urlpatterns = [
    # --- DEINE BESTEHENDEN LEGACY VIEWS ---
    # Der leere Pfad '' entspricht '/portfolio/'
    path('', views.liegenschaft_liste, name='liegenschaft_liste'),

    # Der Pfad für die Details, z.B. '/portfolio/1/'
    path('<int:pk>/', views.liegenschaft_detail, name='liegenschaft_detail'),

    # Hier kommen ggf. noch weitere alte Pfade hin, falls du welche hattest
    # path('einheit-loeschen/', ...),

    # --- UNSER NEUER VUE.JS TEST ---
    path('vue-test/', views.vue_test_view, name='vue_test'),
]