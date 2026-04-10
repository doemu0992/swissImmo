# tickets/forms.py
from django import forms
from .models import SchadenMeldung, HandwerkerAuftrag

class SchadenMeldungForm(forms.ModelForm):
    class Meta:
        model = SchadenMeldung
        fields = [
            'liegenschaft', 'betroffene_einheit', 'gemeldet_von',
            'titel', 'beschreibung', 'prioritaet', 'status', 'zutritt'
        ]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for field_name, field in self.fields.items():
            field.widget.attrs['class'] = 'bg-gray-50 border border-gray-200 text-gray-900 text-sm rounded-xl focus:ring-indigo-500 focus:border-indigo-500 block w-full p-2.5 transition-all outline-none'

        if 'beschreibung' in self.fields:
            self.fields['beschreibung'].widget.attrs['rows'] = 3

# --- NEU: Formular für den Handwerker-Auftrag ---
class HandwerkerAuftragForm(forms.ModelForm):
    class Meta:
        model = HandwerkerAuftrag
        fields = ['handwerker', 'status', 'bemerkung']

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for field_name, field in self.fields.items():
            field.widget.attrs['class'] = 'bg-gray-50 border border-gray-200 text-gray-900 text-sm rounded-xl focus:ring-indigo-500 focus:border-indigo-500 block w-full p-2.5 transition-all outline-none'

        if 'bemerkung' in self.fields:
            self.fields['bemerkung'].widget.attrs['rows'] = 3