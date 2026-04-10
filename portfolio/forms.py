# portfolio/forms.py
from django import forms
from .models import Liegenschaft, Einheit

class LiegenschaftForm(forms.ModelForm):
    class Meta:
        model = Liegenschaft
        fields = ['strasse', 'plz', 'ort', 'baujahr', 'egid', 'kataster_nummer', 'versicherungswert']

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for field_name, field in self.fields.items():
            field.widget.attrs['class'] = 'bg-gray-50 border border-gray-200 text-gray-900 text-sm rounded-xl focus:ring-indigo-500 focus:border-indigo-500 block w-full p-2.5 transition-all outline-none'

# --- NEU: Formular für die Einheiten ---
class EinheitForm(forms.ModelForm):
    class Meta:
        model = Einheit
        fields = ['bezeichnung', 'typ', 'zimmer', 'flaeche_m2', 'etage', 'nettomiete_aktuell', 'nebenkosten_aktuell']

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for field_name, field in self.fields.items():
            field.widget.attrs['class'] = 'bg-gray-50 border border-gray-200 text-gray-900 text-sm rounded-xl focus:ring-indigo-500 focus:border-indigo-500 block w-full p-2.5 transition-all outline-none'