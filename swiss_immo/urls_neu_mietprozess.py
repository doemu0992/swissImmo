"""Mietprozess unter /neu/: Bewerbungen, Vermarktung, Mietzins, Anpassungen.

Aus `swiss_immo/urls.py` ausgelagert, Reihenfolge der Routen unverändert (die Reihenfolge entscheidet bei
überlappenden Mustern). Die Namen bleiben global (kein Namensraum): `reverse('fw_…')` und `{% url %}` ändern sich nicht.
"""
import core.views.fw.mietprozess as _bewerber_board
from core.views.fw import (
    fw_abnahme_neu,
    fw_abnahme_vorort_start,
    fw_anfangsmietzins,
    fw_anpassung_status,
    fw_bewerber_absage_uebrige,
    fw_bewerber_besichtigung,
    fw_bewerber_entscheid,
    fw_bewerber_vergleich,
    fw_bewerbung_detail,
    fw_bewerbung_status,
    fw_bewerbung_unterlagen,
    fw_bewerbung_zu_vertrag,
    fw_bewerbungen,
    fw_mietzins,
    fw_mietzins_anpassung,
    fw_mietzins_anpassung_rechnen,
    fw_mietzins_massenanpassung,
    fw_mietzins_versand,
    fw_pendenz_loeschen,
    fw_pendenz_neu,
    fw_pendenz_toggle)
from django.urls import path


urlpatterns = [
    path('neu/pendenzen/neu/', fw_pendenz_neu, name='fw_pendenz_neu'),
    path('neu/pendenzen/<int:pk>/toggle/', fw_pendenz_toggle, name='fw_pendenz_toggle'),
    path('neu/pendenzen/<int:pk>/loeschen/', fw_pendenz_loeschen, name='fw_pendenz_loeschen'),
    path('neu/bewerbungen/', fw_bewerbungen, name='fw_bewerbungen'),
    path('neu/vermarktung/<int:einheit_id>/bewerber/', fw_bewerber_vergleich, name='fw_bewerber_vergleich'),
    path('neu/bewerbungen/<int:pk>/entscheid/', fw_bewerber_entscheid, name='fw_bewerber_entscheid'),
    path('neu/bewerbungen/<int:pk>/besichtigung/', fw_bewerber_besichtigung, name='fw_bewerber_besichtigung'),
    path('neu/vermarktung/<int:einheit_id>/bewerber/absage-uebrige/', fw_bewerber_absage_uebrige, name='fw_bewerber_absage_uebrige'),
    path('neu/bewerbungen/<int:pk>/', fw_bewerbung_detail, name='fw_bewerbung_detail'),
    path('neu/bewerbungen/<int:pk>/status/', fw_bewerbung_status, name='fw_bewerbung_status'),
    path('neu/bewerbungen/<int:pk>/unterlagen/', fw_bewerbung_unterlagen, name='fw_bewerbung_unterlagen'),
    path('neu/bewerbungen/<int:pk>/vertrag/', fw_bewerbung_zu_vertrag, name='fw_bewerbung_zu_vertrag'),
    # Modul 4 (27.10.2026): Bewerber-Board — Spaltenwechsel und Prüf-Checkliste.
    path('neu/bewerbungen/<int:pk>/verschieben/', _bewerber_board.fw_bewerbung_verschieben,
         name='fw_bewerbung_verschieben'),
    path('neu/bewerbungen/<int:pk>/pruefung/', _bewerber_board.fw_bewerbung_pruefung,
         name='fw_bewerbung_pruefung'),
    path('neu/mietzins/', fw_mietzins, name='fw_mietzins'),
    path('neu/mietzins/massenanpassung/', fw_mietzins_massenanpassung, name='fw_mietzins_massenanpassung'),
    path('neu/mietzins/<int:vertrag_id>/anpassung/', fw_mietzins_anpassung, name='fw_mietzins_anpassung'),
    path('neu/mietzins/<int:vertrag_id>/anpassung/rechnen/', fw_mietzins_anpassung_rechnen,
         name='fw_mietzins_anpassung_rechnen'),
    path('neu/mietzins/versand/', fw_mietzins_versand, name='fw_mietzins_versand'),
    path('neu/anpassung/<int:pk>/status/', fw_anpassung_status, name='fw_anpassung_status'),
    path('neu/mietzins/<int:vertrag_id>/anfangsmietzins/', fw_anfangsmietzins, name='fw_anfangsmietzins'),
    path('neu/vertraege/<int:vertrag_id>/abnahme/neu/', fw_abnahme_neu, name='fw_abnahme_neu'),
    path('neu/vertraege/<int:vertrag_id>/abnahme/vorort/', fw_abnahme_vorort_start, name='fw_abnahme_vorort_start'),
]
