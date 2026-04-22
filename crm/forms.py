# crm/forms.py
from django import forms
from .models import Mieter, Verwaltung, Mandant, Handwerker

class MieterForm(forms.ModelForm):
    class Meta:
        model = Mieter
        fields = '__all__'
        widgets = {
            'is_company': forms.CheckboxInput(attrs={'class': 'rounded text-indigo-600 focus:ring-indigo-500'}),
            'geburtsdatum': forms.DateInput(attrs={'type': 'date'}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for field in self.fields.values():
            if not isinstance(field.widget, forms.CheckboxInput):
                field.widget.attrs.update({'class': 'w-full p-2.5 rounded-xl border border-gray-200 focus:ring-indigo-500 focus:border-indigo-500 bg-gray-50/50'})

class VerwaltungForm(forms.ModelForm):
    class Meta:
        model = Verwaltung
        fields = ['firma', 'strasse', 'plz', 'ort', 'telefon', 'email', 'iban', 'logo', 'unterschrift_bild']

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for field in self.fields.values():
            field.widget.attrs.update({'class': 'w-full p-2.5 rounded-xl border border-gray-200 focus:ring-indigo-500 focus:border-indigo-500 bg-gray-50/50'})

class MandantForm(forms.ModelForm):
    class Meta:
        model = Mandant
        fields = ['firma_oder_name', 'kontaktperson', 'strasse', 'plz', 'ort', 'telefon', 'email', 'bank_name', 'iban', 'unterschrift_bild']

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for field in self.fields.values():
            field.widget.attrs.update({'class': 'w-full p-2.5 rounded-xl border border-gray-200 focus:ring-indigo-500 focus:border-indigo-500 bg-gray-50/50'})

class HandwerkerForm(forms.ModelForm):
    class Meta:
        model = Handwerker
        fields = '__all__'

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for field in self.fields.values():
            field.widget.attrs.update({'class': 'w-full p-2.5 rounded-xl border border-gray-200 focus:ring-indigo-500 focus:border-indigo-500 bg-gray-50/50'})