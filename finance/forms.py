# finance/forms.py
from django import forms
from .models import AbrechnungsPeriode, NebenkostenBeleg

class AbrechnungsPeriodeForm(forms.ModelForm):
    class Meta:
        model = AbrechnungsPeriode
        fields = ['liegenschaft', 'bezeichnung', 'start_datum', 'ende_datum', 'abgeschlossen']
        widgets = {
            'start_datum': forms.DateInput(format='%Y-%m-%d', attrs={'type': 'date'}),
            'ende_datum': forms.DateInput(format='%Y-%m-%d', attrs={'type': 'date'}),
            'abgeschlossen': forms.CheckboxInput(attrs={'class': 'w-5 h-5 text-indigo-600 rounded border-gray-300 focus:ring-indigo-500 cursor-pointer'}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for field_name, field in self.fields.items():
            if field_name != 'abgeschlossen':
                field.widget.attrs['class'] = 'bg-gray-50 border border-gray-200 text-gray-900 text-sm rounded-xl focus:ring-indigo-500 focus:border-indigo-500 block w-full p-2.5 transition-all outline-none'

class NebenkostenBelegForm(forms.ModelForm):
    class Meta:
        model = NebenkostenBeleg
        fields = ['beleg_scan', 'verteilschluessel', 'datum', 'text', 'betrag', 'kategorie']
        widgets = {
            'datum': forms.DateInput(format='%Y-%m-%d', attrs={'type': 'date'}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for field_name, field in self.fields.items():
            field.widget.attrs['class'] = 'bg-gray-50 border border-gray-200 text-gray-900 text-sm rounded-xl focus:ring-indigo-500 focus:border-indigo-500 block w-full p-2.5 transition-all outline-none'