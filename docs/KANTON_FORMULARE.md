# Amtliche kantonale Mietformulare — Quellen & Integrationsstatus

Für jede Liegenschaft wird anhand des Kantons (`Liegenschaft.kanton`, ersatzweise
PLZ) automatisch das richtige Formular gewählt. Ein Kanton ist **„eingebaut"**,
sobald sein Original-PDF unter `core/services/formulare/` liegt und die
Feld-Koordinaten in `core/services/formular_fill.py` gemappt sind.

> **Download-Hinweis:** Die Behörden-PDFs können aus der Build-Umgebung nicht
> automatisch heruntergeladen werden (Netzwerk-Policy → 403). Die Originale müssen
> manuell geladen und beigelegt werden. Untenstehende Links wurden per Websuche
> ermittelt (Stand Juli 2026) — vor Gebrauch die aktuellste Version prüfen.

Zwei Formulartypen je Kanton:
- **MZ** = Mitteilung Mietzins-/Vertragsänderung (Art. 269d OR)
- **KD** = Kündigung Wohn-/Geschäftsräume (Art. 266l/298 OR)

| KT | Status | MZ (Mietzinsänderung) | KD (Kündigung) |
|----|--------|-----------------------|-----------------|
| SO | ✅ eingebaut | (im Repo) | (im Repo) |
| ZH | 🔗 Link | https://www.gerichte-zh.ch/fileadmin/user_upload/Dokumente/Themen/Miete/Formulare_und_Merkblaetter/F_Mietzinserhoehung.pdf | https://www.zh.ch/content/dam/zhweb/bilder-dokumente/organisation/direktion-der-justiz-und-des-innern/generalsekretariat/mietwesen/formulare-neu-ab-nov2025/Formular-Kuendigung.pdf |
| BE | 🔗 Link | https://www.zsg.justice.be.ch/content/dam/zsg_justice/dokumente/de/zivilrecht/formular-zinserhoehung-miete-be.pdf | https://www.zsg.justice.be.ch/content/dam/zsg_justice/dokumente/de/zivilrecht/formular-kuendigung-miete-be-online.pdf |
| LU | 🔗 Link | https://gerichte.lu.ch/-/media/Gerichte/Dokumente/rechtsgebiete/formulare/Mietrecht/Mietvertragsaenderung_pdf.pdf | https://gerichte.lu.ch/-/media/Gerichte/Dokumente/rechtsgebiete/formulare/Mietvertrag_Kuendigung_pdf.pdf |
| AG | 🔗 Link | https://www.ag.ch/media/kanton-aargau/jb/dokumente/schlichtungsbehoerden/schlichtungsbehoerden-fuer-miete-und-pacht/formular-fuer-mitteilung-von-miet-und-pachtzinsaenderungen.pdf | https://www.ag.ch/media/kanton-aargau/jb/dokumente/schlichtungsbehoerden/schlichtungsbehoerden-fuer-miete-und-pacht/formular-fuer-kuendigung-von-miet-undpachtvertraegen.pdf |
| BS | 🔗 Link | Übersicht: https://www.bs.ch/regierungsrat/staatskanzlei/staatliche-schlichtungsstelle-fuer-mietstreitigkeiten/formulare | https://media.bs.ch/original_file/b5992c3d30bb0ebf5ac1acf7f746c01bf2cbfb9c/formular-zur-kuendigung-von-wohn-und-geschaeftsraeumen-durch.pdf |
| BL | 🔗 Link | https://www.baselland.ch/politik-und-behorden/direktionen/volkswirtschafts-und-gesundheitsdirektion/schlichtungsstellen/mietangelegenheiten/formulare/downloads-1/form_mietvertragsaenderung.pdf | Übersicht: https://www.baselland.ch/politik-und-behorden/direktionen/volkswirtschafts-und-gesundheitsdirektion/generalsekretariat/aufgaben/schlichtungsstellen/mietangelegenheiten |
| SG | 🔗 Link | Übersicht: https://www.sg.ch/recht/gerichte/informationen---formulare/mietrecht--mitteilungen-des-vermieters.html | https://www.sg.ch/content/dam/sgch/recht/gerichte/formulare/mietrecht/2024_66.052_Formular_Kuendigung_Nov_2024.pdf |
| TG | 🔗 Link | https://djs.tg.ch/public/upload/assets/181002/2025-09-25_Formular_Miet-_Pachtvertragsaenderung_def._Kofax.pdf | Übersicht: https://djs.tg.ch/rechtsdienst/amtliche-formulare-.html/4952 |
| GR | 🔗 Link | https://www.gr.ch/DE/institutionen/verwaltung/dvs/alg/Dokumente%20Wohnbaufrderung/MW_HS_01_DE_Formular_zur_Mitteilung_von_Mietzinserhoehungen_und_einseitigen_Vertragsaenderungen_gemaess_Art._269d_OR.pdf | https://www.gr.ch/DE/institutionen/verwaltung/dvs/alg/Dokumente%20Wohnbaufrderung/MW_HS_02_DE_Formular_fuer_die_Kuendigung_von_Wohn-_und_Geschaeftsraeumen_durch_den_Vermieter.pdf |
| SZ | 🔗 Link | Übersicht: https://www.sz.ch/behoerden/verwaltung/volkswirtschaftsdepartement/departementssekretariat/miete-und-pacht.html | https://www.sz.ch/public/upload/assets/31074/Kuendigung_Formular_fuer_die_Mitteilung_einer_Kuendigung_des_Vermieters_nicht_landwirtschaftlichen_Verpaechters_von_Wohn-_und_Geschaeftsraeumen_gemaess_Art_266l_und_Art._298_OR.pdf |
| SH | 🔗 Link | https://sh.ch/CMS/get/file/598cf9ce-a962-44d3-872d-6cf5b6728b9f | https://sh.ch/CMS/get/file/2bb91d37-eaa6-4d8f-905a-9b296dfb6b88 |
| ZG | 🔗 Link | https://zg.ch/dam/jcr:49e73bf6-a294-4b81-a7f9-1dd2a838648a/MietvertragsaenderungAnfangsmietzins+per+30+09+2025.pdf | https://zg.ch/dam/jcr:d34b55d3-ff27-44f1-875e-bffc8431e0cf/Kuendigung%20Mietvertrag.pdf |
| AR | 🔗 Link | Übersicht: https://ar.ch/gerichte/vermittler-und-schlichtungsstellen/schlichtungsstelle-fuer-miete-und-nichtlandwirtschaftliche-pacht/ | https://ar.ch/fileadmin/user_upload/Gerichte/Vermittlung_Schlichtung/Schlichtungsstelle/Formular_Kuendigung_20201126_neu.pdf |
| AI | 🔗 Link | https://www.ai.ch/themen/persoenliches/wohnen-und-umziehen/schlichtungsstelle-mietverhaeltnisse/publikationen/mitteilung-mietzinsaenderung-formular.pdf/download | Übersicht: https://www.ai.ch/themen/persoenliches/wohnen-und-umziehen/schlichtungsstelle-mietverhaeltnisse |
| NW | 🔗 Link | Online-Schalter: https://www.nw.ch/online-schalter/2478/detail | (Kanton NW Online-Schalter) |
| GL | 🔎 offen | via kantonale Schlichtungsstelle / HEV GL | via kantonale Schlichtungsstelle / HEV GL |
| UR | 🔎 offen | via kantonale Schlichtungsstelle / HEV UR | via kantonale Schlichtungsstelle / HEV UR |
| OW | 🔎 offen | via kantonale Schlichtungsstelle / HEV OW | via kantonale Schlichtungsstelle / HEV OW |
| VD | 🔎 offen (FR) | Formulaire officiel avis de majoration | Formulaire officiel de résiliation |
| GE | 🔎 offen (FR) | Formulaire officiel avis de majoration | Formulaire officiel de résiliation |
| FR | 🔎 offen (FR/DE) | Formulaire officiel / amtliches Formular | Formulaire officiel / amtliches Formular |
| NE | 🔎 offen (FR) | Formulaire officiel | Formulaire officiel |
| JU | 🔎 offen (FR) | Formulaire officiel | Formulaire officiel |
| VS | 🔎 offen (FR/DE) | Formulaire officiel / amtliches Formular | Formulaire officiel / amtliches Formular |
| TI | 🔎 offen (IT) | Modulo ufficiale | Modulo ufficiale disdetta |

## Vorgehen zum Einbauen eines Kantons

1. Original-PDF laden und ins Chat schicken (oder in `core/services/formulare/`
   ablegen als `<KT>_mietzins_original.pdf` / `<KT>_kuendigung_original.pdf`).
2. Feld-Koordinaten des Formulars mit `pdfplumber` auslesen und in
   `core/services/formular_fill.py` eine `fill_mietzins_<kt>` /
   `fill_kuendigung_<kt>` ergänzen (analog Solothurn).
3. In `core/views/fw.py` (`fw_mietzins_anpassung`, `fw_kuendigung_formular`) den
   Kanton auf „Original ausfüllen" schalten.
4. Bis dahin greift für den Kanton die generische Nachbildung mit dem korrekten
   Schlichtungsbehörden-Block (sobald dessen Adressen hinterlegt sind).
