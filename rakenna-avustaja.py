#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
rakenna-avustaja.py – kokoaa Hautatietohaun avustajan index.html-tiedoston

Lukee samasta kansiosta template.html-pohjan sekä kattavuus.json- ja kunta-vastaavuudet.json-
tiedostot, upottaa kattavuusdatan pohjaan ja kirjoittaa tuloksen samaan kansioon nimellä index.html.

Käyttö:
  python rakenna-avustaja.py

Aja tämä aina, kun paivita-kattavuus.py on päivittänyt kattavuus.json-tiedoston
tai kun template.html on muuttunut.
"""
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
OUTPUT_NAME = 'index.html'  # GitHub Pages näyttää tämän sivuston etusivuna


def load(name):
    path = os.path.join(HERE, name)
    if not os.path.exists(path):
        sys.exit(f'Tiedosto puuttuu: {path}')
    return path


katt = json.load(open(load('kattavuus.json'), encoding='utf-8'))
mapping = json.load(open(load('kunta-vastaavuudet.json'), encoding='utf-8'))
tpl = open(load('template.html'), encoding='utf-8').read()

slim = {
    'generated': katt['generated'],
    'hautahaku': [{'id': c['id'], 'name': c['name'],
                   'cemeteries': [{'name': g['name'], 'kunta': g['kunta']} for g in c['cemeteries']]}
                  for c in katt['hautahaku']['congregations']],
    'hautakartta': [{'slug': c['slug'], 'name': c['name'], 'cemeteries': c['cemeteries']}
                    for c in katt['hautakartta']['congregations']],
    'haudat': [{'slug': c['slug'], 'name': c['name'], 'deceased': c['deceased'],
                'cemeteries': [x['name'] for x in c['cemeteries']]}
               for c in katt['haudat']['parishes']],
    'suomenkiha': katt['suomenkiha']['municipalities'],
    'genealogia': katt.get('genealogia', {}).get('municipalities', []),
    'geneanet': katt['geneanet']['regions'],
    'mapping': {k: v for k, v in mapping.items() if not k.startswith('_')},
}
marker = '/*__DATA__*/null'
if marker not in tpl:
    sys.exit('template.html-pohjasta puuttuu merkintä ' + marker)
out = tpl.replace(marker, json.dumps(slim, ensure_ascii=False, separators=(',', ':')))
dest = os.path.join(HERE, OUTPUT_NAME)
open(dest, 'w', encoding='utf-8').write(out)
print(f'Kirjoitettu {dest} ({len(out) // 1024} kt, kattavuus {katt["generated"]})')
