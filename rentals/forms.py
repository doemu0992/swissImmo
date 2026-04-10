# rentals/forms.py
from django import forms
from .models import Mietvertrag

class MietvertragForm(forms.ModelForm):
    class Meta:
        model = Mietvertrag
        fields = [
            'mieter', 'einheit', 'beginn', 'ende',
            'netto_mietzins', 'nebenkosten', 'kautions_betrag',
            'basis_referenzzinssatz', 'basis_lik_punkte', 'aktiv', 'sign_status'
        ]
        widgets = {
            'beginn': forms.DateInput(format='%Y-%m-%d', attrs={'type': 'date'}),
            'ende': forms.DateInput(format='%Y-%m-%d', attrs={'type': 'date'}),
            'aktiv': forms.CheckboxInput(attrs={'class': 'w-5 h-5 text-indigo-600 rounded border-gray-300 focus:ring-indigo-500 cursor-pointer'}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for field_name, field in self.fields.items():
            if field_name != 'aktiv':
                field.widget.attrs['class'] = 'bg-gray-50 border border-gray-200 text-gray-900 text-sm rounded-xl focus:ring-indigo-500 focus:border-indigo-500 block w-full p-2.5 transition-all outline-none'