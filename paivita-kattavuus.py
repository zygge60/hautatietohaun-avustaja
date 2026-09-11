#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
paivita-kattavuus.py – päivittää hautahakupalveluiden kattavuustiedot (kattavuus.json)

Noutaa kunkin palvelun oman hautausmaaluettelon, vertaa sitä edelliseen versioon ja
kirjoittaa uuden kattavuus.json-tiedoston sekä muutosraportin.

Lähteet:
  hautakartta.fi   GET /api/congregations ja jokaiselle seurakunnalle /<slug>/api/cemetery
  hautahaku.fi     sovelluksen JS-paketti (/asset-manifest.json -> main.js), jonka sisällä on
                   hautausmaataulukko JSON.parse('...')-merkkijonona
  haudat.fi        etusivun Suomi-osion maakuntalinkit -> seurakuntasivut (HTML)
  suomenkiha.fi    sovelluksen käyttämä Firestore-tietokanta, kokoelma "graveyards"
                   (vain hakemisto: nimi, kunta, tyyppi; ei henkilötietoja)
  genealogia.fi    Hautakivitietokannan hautausmaaluettelo (Google Sheets, CSV-vienti)
  geneanet         Suomi-sivun maakuntakohtaiset lukumäärät
  opasteapp.fi     seurakuntakohtaiset sivut (Vantaa, Kerava, Vihti); tarkistetaan, että ne vastaavat
  suvusto.fi       Haudat-osion sivupalkin kuvauspaikkaluettelo (kunnat ja kuvamäärät)

Käyttö (samassa kansiossa kuin kattavuus.json ja kunta-vastaavuudet.json):
  python paivita-kattavuus.py                 # päivittää kattavuus.json
  python paivita-kattavuus.py --dry-run       # näyttää muutokset, ei kirjoita
  python paivita-kattavuus.py --skip suomenkiha,geneanet,opasteapp,suvusto
  python paivita-kattavuus.py --only hautakartta

Vaatii Pythonin 3.8+ ja requests-kirjaston (pip install requests).
Kaikki lähteet ovat palveluiden sisäisiä rakenteita, eivät luvattuja rajapintoja:
jos jokin lähde ei toimi, kyseisen palvelun edelliset tiedot säilytetään ja skripti varoittaa.
"""
import argparse
import csv
import html as html_mod
import datetime as dt
import io
import json
import os
import re
import sys
import time

try:
    import requests
except ImportError:
    sys.exit("Asenna requests: pip install requests")

HERE = os.path.dirname(os.path.abspath(__file__))
DATA = HERE  # kaikki tiedostot samassa kansiossa skriptin kanssa
OUT = os.path.join(DATA, 'kattavuus.json')
MAPFILE = os.path.join(DATA, 'kunta-vastaavuudet.json')
LOG = os.path.join(DATA, 'kattavuus-muutokset.txt')

UA = 'hautahakuapp-kattavuus/1.0 (sukututkijoiden hakuavustaja; kattavuusluettelon päivitys)'
SESSION = requests.Session()
SESSION.headers['User-Agent'] = UA
PAUSE = 0.7  # sekuntia pyyntöjen välillä – ei kuormiteta palveluita


def get(url, **kw):
    time.sleep(PAUSE)
    r = SESSION.get(url, timeout=40, **kw)
    r.raise_for_status()
    return r


def warn(msg):
    print('  VAROITUS:', msg, file=sys.stderr)


# ---------------------------------------------------------------- hautakartta.fi
def fetch_hautakartta():
    base = 'https://hautakartta.fi'
    congs = get(base + '/api/congregations').json()
    out = []
    for c in congs:
        slug = c.get('url')
        if not slug:
            continue
        try:
            cem = get(f'{base}/{slug}/api/cemetery').json()
        except Exception as e:
            warn(f'hautakartta {slug}: {e}')
            cem = []
        out.append({
            'slug': slug,
            'name': c.get('name'),
            'url': f'{base}/{slug}/',
            'cemeteries': [x.get('title') for x in cem],
            'cemetery_details': [{'id': x.get('id'), 'name': x.get('title'),
                                  'lat': (x.get('location') or {}).get('lat'),
                                  'lng': (x.get('location') or {}).get('lng')} for x in cem],
        })
    return out


# ---------------------------------------------------------------- hautahaku.fi
def _decode_js_single_quoted(s):
    """Purkaa JS:n yksinkertaisin lainausmerkein kirjoitetun merkkijonon sisällön."""
    def rep(m):
        e = m.group(1)
        if e.startswith('x'):
            return chr(int(e[1:], 16))
        if e.startswith('u'):
            return chr(int(e[1:], 16))
        return {'n': '\n', 'r': '\r', 't': '\t', "'": "'", '"': '"', '\\': '\\', '/': '/', 'b': '\b', 'f': '\f'}.get(e, e)
    return re.sub(r'\\(x[0-9a-fA-F]{2}|u[0-9a-fA-F]{4}|.)', rep, s)


def parse_hautahaku_bundle(js):
    """Etsii JS-paketista JSON.parse('...')-lohkon, jossa on hautausmaataulukko."""
    key = '"graveyards":[{"id"'
    k = js.find(key)
    if k < 0:
        raise ValueError('hautausmaataulukkoa ei löytynyt paketista (rakenne muuttunut?)')
    q1 = js.rfind("JSON.parse('", 0, k)
    q2 = js.find("')", k)
    if q1 < 0 or q2 < 0:
        raise ValueError('JSON.parse-lohkoa ei löytynyt (rakenne muuttunut?)')
    obj = json.loads(_decode_js_single_quoted(js[q1 + 12:q2]))

    def find(o):
        if isinstance(o, dict):
            g = o.get('graveyards')
            if isinstance(g, list) and g and isinstance(g[0], dict) and 'graveyards' in g[0]:
                return g
            for v in o.values():
                r = find(v)
                if r:
                    return r
        elif isinstance(o, list):
            for v in o:
                r = find(v)
                if r:
                    return r
    arr = find(obj)
    if not arr:
        raise ValueError('ylläpitäjäluetteloa ei löytynyt JSON-lohkosta')
    return arr


def fetch_hautahaku(mapping):
    base = 'https://www.hautahaku.fi'
    manifest = get(base + '/asset-manifest.json').json()
    mainjs = manifest['files']['main.js']
    js = get(base + mainjs).text
    arr = parse_hautahaku_bundle(js)
    po2kunta = mapping['postitoimipaikka_kunta']
    out = []
    for c in arr:
        cems = []
        for g in c.get('graveyards', []):
            pc = (g.get('postcode') or '').strip()
            m = re.match(r'(\d{5})\s+(.*)', pc)
            postcode, po = (m.group(1), m.group(2)) if m else ('', pc)
            cems.append({'id': g.get('id'), 'name': (g.get('name') or '').strip(),
                         'address': g.get('address'), 'postcode': postcode, 'postoffice': po,
                         'kunta': po2kunta.get(po, po)})
        out.append({'id': c.get('id'), 'name': c.get('name'), 'cemeteries': cems})
    return out


# ---------------------------------------------------------------- haudat.fi
LINK_RE = re.compile(r'<a[^>]+href="(?:https?://haudat\.fi)?(/(?:region|forsamling)/[^"]+)"[^>]*>(.*?)</a>', re.S)


def _clean(t):
    t = html_mod.unescape(t).replace('\xa0', ' ')
    t = re.sub(r'\s+', ' ', t).strip()
    return re.sub(r'\s*/\s*', '/', t)


def _links(html):
    """Palauttaa (polku, nimi, lukumäärä) -kolmikot haudat.fi:n listasivuilta."""
    res = []
    for href, inner in LINK_RE.findall(html):
        texts = [_clean(t) for t in re.findall(r'>([^<>]+)<', '>' + inner + '<') if _clean(t)]
        if not texts:
            continue
        name = texts[0]
        num = None
        for t in texts[1:]:
            d = re.sub(r'\D', '', t)
            if d:
                num = int(d)
        res.append((href, name, num))
    return res


def fetch_haudat():
    base = 'https://haudat.fi'
    html = get(base + '/').text
    # Suomi-osio: h2 "Suomi" ... h2 "Ruotsi"
    m = re.search(r'Suomi\s*</h2>(.*?)(?:<h2|$)', html, re.S)
    section = m.group(1) if m else html
    regions = [(h, n) for h, n, _ in _links(section) if h.startswith('/region/')]
    seen, out = set(), []
    for rpath, rname in regions:
        if rpath in seen:
            continue
        seen.add(rpath)
        rhtml = get(base + rpath).text
        for ppath, pname, pnum in _links(rhtml):
            if not ppath.startswith('/forsamling/') or ppath.count('/') != 2:
                continue
            phtml = get(base + ppath).text
            cems = [{'name': cn, 'deceased': cnum} for cp, cn, cnum in _links(phtml)
                    if cp.startswith(ppath + '/')]
            out.append({'region': rpath.split('/')[-1], 'region_name': rname, 'name': pname,
                        'slug': ppath.split('/')[-1], 'url': base + ppath,
                        'deceased': pnum, 'cemeteries': cems})
    return out


# ---------------------------------------------------------------- suomenkiha.fi
FIRESTORE = 'https://firestore.googleapis.com/v1/projects/kalmisto-26e73/databases/(default)/documents/graveyards'


def suomenkiha_web_key():
    """Lukee suomenkiha.fi-sovelluksen julkisen Firebase-web-avaimen palvelun omasta
    sovelluskoodista ajon aikana (sama avain, jonka selain saa sivun ladatessaan).
    Avainta ei tallenneta tähän skriptiin. Vaihtoehtoisesti avaimen voi antaa
    ympäristömuuttujassa SUOMENKIHA_WEB_KEY."""
    env = os.environ.get('SUOMENKIHA_WEB_KEY')
    if env:
        return env
    base = 'https://suomenkiha.fi'
    html = get(base + '/').text
    scripts = re.findall(r'<script[^>]+src="([^"]+)"', html)
    for src in scripts:
        url = src if src.startswith('http') else base + '/' + src.lstrip('/')
        try:
            js = get(url).text
        except Exception:
            continue
        m = re.search(r'apiKey\s*:\s*"([A-Za-z0-9_\-]+)"', js)
        if m:
            return m.group(1)
    raise ValueError('suomenkiha.fi:n web-avainta ei löytynyt sovelluskoodista (rakenne muuttunut?)')


def fetch_suomenkiha():
    key = suomenkiha_web_key()
    token, rows = None, []
    for _ in range(40):
        params = {'pageSize': 300, 'key': key,
                  'mask.fieldPaths': ['name', 'city', 'type', 'area']}
        if token:
            params['pageToken'] = token
        j = get(FIRESTORE, params=params).json()
        for d in j.get('documents', []):
            f = d.get('fields', {})
            v = lambda k: (f.get(k) or {}).get('stringValue') or ''
            rows.append({'city': v('city'), 'name': v('name'), 'type': v('type'), 'area': v('area')})
        token = j.get('nextPageToken')
        if not token:
            break
    agg = {}
    for r in rows:
        if r['type'] == 'church':
            continue
        a = agg.setdefault(r['city'], {'city': r['city'], 'graveyards': 0, 'warCemeteries': 0, 'orthodox': 0, 'names': []})
        a['graveyards' if r['type'] == 'graveyard' else 'warCemeteries' if r['type'] == 'warCemetery' else 'orthodox'] += 1
        if r['name']:
            a['names'].append(r['name'])
    return sorted(agg.values(), key=lambda x: x['city'].lower()), len(rows)


# ---------------------------------------------------------------- genealogia.fi (Hautakivitietokanta)
SHEET = 'https://docs.google.com/spreadsheets/d/1NgVb7A84pHnwH8_BgCvUelcgyzxHMYUx/export?format=csv'


SHEET_ALT = 'https://docs.google.com/spreadsheets/d/1NgVb7A84pHnwH8_BgCvUelcgyzxHMYUx/gviz/tq?tqx=out:csv'


def fetch_genealogia():
    text = ''
    for url in (SHEET, SHEET_ALT):
        r = get(url, allow_redirects=True)
        text = r.content.decode('utf-8-sig', errors='replace')
        if 'Paikkakunta' in text:
            break
    if 'Paikkakunta' not in text:
        raise ValueError('CSV-vienti ei sisältänyt Paikkakunta-saraketta; vastaus alkaa: ' + re.sub(r'\s+', ' ', text[:160]))
    # otsikkorivi voi olla muualla kuin ensimmäisellä rivillä
    lines = text.splitlines()
    start = next(i for i, l in enumerate(lines) if 'Paikkakunta' in l)
    rows = list(csv.DictReader(io.StringIO('\n'.join(lines[start:]))))
    rows = [{(k or '').strip(): v for k, v in r.items()} for r in rows]
    agg = {}
    for row in rows:
        k = (row.get('Paikkakunta') or '').strip()
        if not k:
            continue
        a = agg.setdefault(k, {'kunta': k, 'cemeteries': 0, 'photographed': 0, 'cemetery_list': []})
        a['cemeteries'] += 1
        pct = (row.get('Prosentti') or '').replace('%', '').strip()
        done = (row.get('Kuvattu') or '').strip().upper() == 'TRUE' or pct.isdigit() and int(pct) > 0
        a['photographed'] += 1 if done else 0
        a['cemetery_list'].append({'name': (row.get('Hautausmaa') or '').strip(), 'kuvattu': done,
                                   'prosentti': pct, 'vuosi': (row.get('Vuosi') or '').strip()})
    return sorted(agg.values(), key=lambda x: x['kunta'].lower())


# ---------------------------------------------------------------- geneanet
def fetch_geneanet():
    html = get('https://fi.geneanet.org/siviilihautausmaa/geo/FIN/suomi').text
    regions = {}
    for m in re.finditer(r'<a[^>]+href="[^"]*/siviilihautausmaa/geo/FIN/[^"]+"[^>]*>([^<]{1,80})</a>\s*\(\s*(\d+)\s*\)', html):
        txt = re.sub(r'\s+', ' ', m.group(1)).strip()
        if txt:
            regions[txt] = int(m.group(2))
    if not regions:
        raise ValueError('maakuntalukuja ei löytynyt (sivun rakenne muuttunut?)')
    return regions


# ---------------------------------------------------------------- opasteapp.fi
OPASTEAPP_INSTANCES = [
    {'slug': 'hautausmaa-vantaa', 'name': 'Vantaan seurakuntien hautausmaat', 'kunnat': ['Vantaa']},
    {'slug': 'hautausmaa-kerava', 'name': 'Keravan hautausmaa', 'kunnat': ['Kerava']},
    {'slug': 'hautausmaa-vihti', 'name': 'Vihdin hautausmaa', 'kunnat': ['Vihti']},
]


def fetch_opasteapp():
    """OpasteAppilla ei ole luetteloa instansseistaan; tunnetut instanssit tarkistetaan ja
    etusivulta poimitaan mahdolliset uudet hautausmaa-*-linkit."""
    base = 'https://www.opasteapp.fi'
    html = get(base + '/').text
    found = {m.group(1) for m in re.finditer(r'href="[^"]*?/(hautausmaa-[a-z0-9-]+)/?"', html)}
    known = {i['slug'] for i in OPASTEAPP_INSTANCES}
    out = []
    for inst in OPASTEAPP_INSTANCES + [{'slug': s, 'name': s, 'kunnat': []} for s in sorted(found - known)]:
        try:
            page = get(f"{base}/{inst['slug']}/").text
            title = re.search(r'<title>(.*?)</title>', page, re.S)
            h = re.search(r'<h\d[^>]*>([^<]{3,80})</h\d>', page)
            name = (h.group(1).strip() if h else inst['name'])
            out.append({'slug': inst['slug'], 'name': name if name and name != 'OpasteApp' else inst['name'],
                        'url': f"{base}/{inst['slug']}/", 'kunnat': inst['kunnat']})
        except Exception as e:
            warn(f"opasteapp {inst['slug']}: {e}")
    return out


# ---------------------------------------------------------------- suvusto.fi
def fetch_suvusto():
    """Lukee Suvuston Haudat-osion sivupalkista kuvauspaikat: kunnat ja kuvamäärät.
    Sivupalkissa kunta on muodossa '+Kemijärvi (5264)' tai avattuna '—Kemijärvi (5264)'."""
    html = get('https://suvusto.fi/haudat/').text
    text = re.sub(r'<[^>]+>', ' ', html)
    text = html_mod.unescape(re.sub(r'\s+', ' ', text))
    m = re.search(r'KUVAUSPAIKAT(.*?)SUKUNIMET', text, re.I)
    if not m:
        raise ValueError('kuvauspaikkaluetteloa ei löytynyt (sivun rakenne muuttunut?)')
    out = []
    for name, n in re.findall(r'[+—–-]\s*([A-ZÅÄÖ][\wåäöÅÄÖ .-]+?)\s*\((\d+)\)', m.group(1)):
        name = name.strip()
        if 'hautuumaa' in name.lower() or 'hautausmaa' in name.lower():
            continue  # avattu kunta listaa myös hautausmaansa; ne ohitetaan
        slug = re.sub(r'[^a-z0-9-]', '', name.lower().replace('ä', 'a').replace('ö', 'o').replace('å', 'a').replace(' ', '-'))
        out.append({'kunta': name, 'slug': slug, 'url': f'https://suvusto.fi/haudat/{slug}/', 'photos': int(n)})
    if not out:
        raise ValueError('kuvauspaikkoja ei löytynyt')
    return out


# ---------------------------------------------------------------- kuntaindeksi
def build_index(d, mapping):
    idx = {}

    def add(kunta, key, val):
        idx.setdefault(kunta, {}).setdefault(key, []).append(val)

    for c in d['hautahaku']['congregations']:
        for g in c['cemeteries']:
            add(g['kunta'], 'hautahaku', f"{g['name']} ({c['name']})")
    hk_kunnat = mapping['hautakartta_kunnat']
    for c in d['hautakartta']['congregations']:
        for k in hk_kunnat.get(c['slug'], [re.sub(r' (seurakunta|seurakunnat|seurakuntayhtymä|tuomiokirkkoseurakunta).*$', '', c['name']).replace('Rauman', 'Rauma')]):
            add(k, 'hautakartta', c['name'])
    hd_kunnat = mapping['haudat_kunnat']
    for c in d['haudat']['parishes']:
        for k in hd_kunnat.get(c['slug'], [c['name']]):
            add(k, 'haudat', c['name'])
    for c in d.get('suvusto', {}).get('municipalities', []):
        add(c['kunta'], 'suvusto', f"{c['photos']} hautakivikuvaa")
    oa_kunnat = mapping.get('opasteapp_kunnat', {})
    for c in d.get('opasteapp', {}).get('instances', []):
        for k in oa_kunnat.get(c['slug'], c.get('kunnat', [])):
            add(k, 'opasteapp', c['name'])
    for s in d['suomenkiha']['municipalities']:
        k = s['city'].split('/')[0].strip()
        parts = []
        if s['graveyards']: parts.append(f"{s['graveyards']} hautausmaa(ta)")
        if s['warCemeteries']: parts.append(f"{s['warCemeteries']} sankarihautausmaa(ta)")
        if s['orthodox']: parts.append(f"{s['orthodox']} ortodoksista")
        add(k, 'suomenkiha', ', '.join(parts))
    for g in d['genealogia']['municipalities']:
        add(g['kunta'], 'hautakivitietokanta', f"{g['photographed']}/{g['cemeteries']} hautausmaata kuvattu")
    # entiset kunnat -> nykyinen kunta (lisää viittaus)
    for old, new in mapping['entinen_kunta'].items():
        if new in idx and old not in idx:
            idx[old] = {'katso': new}
    return {k: idx[k] for k in sorted(idx, key=str.lower)}


DEFAULT_MAPPING = {
    "_ohje": "Käsin ylläpidettävä vastaavuustaulukko. postitoimipaikka_kunta: hautahaku.fi:n postitoimipaikka -> nykyinen kunta. hautakartta_kunnat / haudat_kunnat: seurakunnan tunnus -> kunnat, joita se kattaa. entinen_kunta: lakkautettu kunta -> nykyinen kunta (kuntaindeksin ristiviittaus). Lisää rivejä, kun päivitysraportti ilmoittaa uusista seurakunnista tai postitoimipaikoista.",
    "postitoimipaikka_kunta": {
        "Hiltulanlahti": "Kuopio", "Hirvilahti": "Kuopio", "Jännevirta": "Kuopio", "Vartiala": "Kuopio",
        "Riistavesi": "Kuopio", "Kortejoki": "Kuopio", "Vehmersalmi": "Kuopio", "Räsälä": "Kuopio",
        "Karttula": "Kuopio", "Syvänniemi": "Kuopio", "Juankoski": "Kuopio", "Muuruvesi": "Kuopio",
        "Nilsiä": "Kuopio", "Säyneinen": "Kuopio", "Kosula": "Tuusniemi", "Pieksänkoski": "Kuopio",
        "Haluna": "Kuopio", "Maaninka": "Kuopio", "Karjalohja": "Lohja", "Pusula": "Lohja", "Nummi": "Lohja",
        "Sammatti": "Lohja", "Siuro": "Nokia", "Sarkola": "Nokia", "Tottijärvi": "Nokia", "Ahlainen": "Pori",
        "Lassila": "Pori", "Lavia": "Pori", "Noormarkku": "Pori", "Pomarkku": "Pomarkku",
        "Peräseinäjoki": "Seinäjoki", "Nurmo": "Seinäjoki", "Ylistaro": "Seinäjoki", "Kitinoja": "Seinäjoki",
        "Terälahti": "Tampere", "Kangasala": "Kangasala", "Vanha-Ulvila": "Ulvila", "Kullaa": "Ulvila",
        "Ulvila": "Ulvila", "Vähäkyrö": "Vaasa", "Viljakkala": "Ylöjärvi", "Kuru": "Ylöjärvi",
        "Länsi-Teisko": "Ylöjärvi", "Itä-Aure": "Ylöjärvi", "Vantaa": "Vantaa", "Kaavi": "Kaavi", "Tuusniemi": "Tuusniemi",
        "Helsinki": "Helsinki", "Espoo": "Espoo", "Tampere": "Tampere", "Vaasa": "Vaasa", "Seinäjoki": "Seinäjoki",
        "Pori": "Pori", "Kuopio": "Kuopio", "Hyvinkää": "Hyvinkää", "Järvenpää": "Järvenpää", "Lohja": "Lohja",
        "Kauniainen": "Kauniainen", "Nokia": "Nokia", "Uurainen": "Uurainen", "Ylöjärvi": "Ylöjärvi"
    },
    "hautakartta_kunnat": {
        "joensuunseurakunnat": ["Joensuu"], "jyvaskylanseurakunta": ["Jyväskylä"], "jamsanseurakunta": ["Jämsä"],
        "kotka-kyminseurakunta": ["Kotka"], "lahdenseurakunnat": ["Lahti"], "lappeenrannanseurakunnat": ["Lappeenranta"],
        "mikkelintuomiokirkkoseurakunta": ["Mikkeli", "Puumala"], "naantalinseurakunnat": ["Naantali"],
        "oulunseurakunnat": ["Oulu"], "paimionseurakunta": ["Paimio", "Sauvo"], "raumanseurakunta": ["Rauma"],
        "turunseurakunnat": ["Turku", "Kaarina"], "hameenlinnanseurakunnat": ["Hämeenlinna"],
        "imatranseurakunta": ["Imatra"], "kontiolahdenseurakunta": ["Kontiolahti"], "leppavirranseurakunta": ["Leppävirta"],
        "someronseurakunta": ["Somero"], "tuusulanseurakunta": ["Tuusula"], "helsinginortodoksinenseurakunta": ["Helsinki"],
        "forssanseurakunta": ["Forssa"], "heinolanseurakunta": ["Heinola"], "janakkalanseurakunta": ["Janakkala"],
        "lapuanseurakunta": ["Lapua"], "merikarvianseurakunta": ["Merikarvia"], "siilinjarvenseurakunta": ["Siilinjärvi"]
    },
    "opasteapp_kunnat": {
        "hautausmaa-vantaa": ["Vantaa"], "hautausmaa-kerava": ["Kerava"], "hautausmaa-vihti": ["Vihti"]
    },
    "haudat_kunnat": {
        "eckero-hammarlands-forsamling": ["Eckerö", "Hammarland"], "suomussalmen-seurakunta": ["Suomussalmi"],
        "muuramen-seurakunta": ["Muurame"], "pyhtaan-seurakunta": ["Pyhtää"], "ranuan-seurakunta": ["Ranua"],
        "malax-forsamling": ["Maalahti"], "narpes-forsamling": ["Närpiö"], "inga-forsamling": ["Inkoo"],
        "raaseporin-seurakuntayhtyma": ["Raasepori"], "vihdin-seurakunta": ["Vihti"], "pyharannan-seurakunta": ["Pyhäranta"]
    },
    "entinen_kunta": {
        "Nilsiä": "Kuopio", "Juankoski": "Kuopio", "Karttula": "Kuopio", "Maaninka": "Kuopio", "Vehmersalmi": "Kuopio",
        "Riistavesi": "Kuopio", "Karjalohja": "Lohja", "Nummi-Pusula": "Lohja", "Sammatti": "Lohja",
        "Ahlainen": "Pori", "Lavia": "Pori", "Noormarkku": "Pori", "Peräseinäjoki": "Seinäjoki", "Nurmo": "Seinäjoki",
        "Ylistaro": "Seinäjoki", "Kuru": "Ylöjärvi", "Viljakkala": "Ylöjärvi", "Teisko": "Tampere", "Vähäkyrö": "Vaasa",
        "Kullaa": "Ulvila", "Haukipudas": "Oulu", "Kiiminki": "Oulu", "Ylikiiminki": "Oulu", "Yli-Ii": "Oulu",
        "Oulunsalo": "Oulu", "Kiihtelysvaara": "Joensuu", "Pyhäselkä": "Joensuu", "Tuupovaara": "Joensuu", "Eno": "Joensuu",
        "Anttola": "Mikkeli", "Haukivuori": "Mikkeli", "Ristiina": "Mikkeli", "Suomenniemi": "Mikkeli",
        "Joutseno": "Lappeenranta", "Ylämaa": "Lappeenranta", "Nuijamaa": "Lappeenranta", "Jämsänkoski": "Jämsä",
        "Kuorevesi": "Jämsä", "Kymi": "Kotka", "Karhula": "Kotka", "Nastola": "Lahti", "Maaria": "Turku",
        "Kakskerta": "Turku", "Paattinen": "Turku", "Piikkiö": "Kaarina", "Kuusisto": "Kaarina", "Merimasku": "Naantali",
        "Velkua": "Naantali", "Rymättylä": "Naantali", "Karuna": "Sauvo", "Vanaja": "Hämeenlinna", "Lammi": "Hämeenlinna",
        "Tuulos": "Hämeenlinna", "Hauho": "Hämeenlinna", "Kalvola": "Hämeenlinna", "Renko": "Hämeenlinna",
        "Tammisaari": "Raasepori", "Karjaa": "Raasepori", "Pohja": "Raasepori", "Snappertuna": "Raasepori",
        "Tenhola": "Raasepori", "Bromarv": "Raasepori", "Mustio": "Raasepori", "Petolahti": "Maalahti",
        "Bergö": "Maalahti", "Pirttikylä": "Närpiö", "Ylimarkku": "Närpiö", "Degerby": "Inkoo", "Kodisjoki": "Rauma",
        "Lappi": "Rauma", "Korpilahti": "Jyväskylä", "Säynätsalo": "Jyväskylä", "Jokela": "Tuusula", "Kellokoski": "Tuusula"
    }
}


# ---------------------------------------------------------------- vertailu
def names_by_service(d):
    """Palauttaa {palvelu: {seurakunta: set(hautausmaat)}} vertailua varten."""
    out = {}
    out['hautahaku'] = {c['name']: {g['name'] for g in c['cemeteries']} for c in d.get('hautahaku', {}).get('congregations', [])}
    out['hautakartta'] = {c['name']: set(c['cemeteries']) for c in d.get('hautakartta', {}).get('congregations', [])}
    out['haudat'] = {c['name']: {x['name'] for x in c['cemeteries']} for c in d.get('haudat', {}).get('parishes', [])}
    out['suomenkiha'] = {s['city']: {s['graveyards'] + s['warCemeteries'] + s['orthodox']} for s in d.get('suomenkiha', {}).get('municipalities', [])}
    out['hautakivitietokanta'] = {g['kunta']: {g['photographed']} for g in d.get('genealogia', {}).get('municipalities', [])}
    out['opasteapp'] = {c['name']: set(c.get('kunnat', [])) for c in d.get('opasteapp', {}).get('instances', [])}
    out['suvusto'] = {c['kunta']: {c['photos']} for c in d.get('suvusto', {}).get('municipalities', [])}
    return out


def diff(old, new):
    lines = []
    o, n = names_by_service(old), names_by_service(new)
    for svc in n:
        oc, nc = o.get(svc, {}), n[svc]
        for k in sorted(set(nc) - set(oc)):
            lines.append(f'{svc}: UUSI {k} ({len(nc[k])} kohdetta)' if svc in ('hautahaku', 'hautakartta', 'haudat') else f'{svc}: UUSI {k}')
        for k in sorted(set(oc) - set(nc)):
            lines.append(f'{svc}: POISTUNUT {k}')
        for k in sorted(set(nc) & set(oc)):
            if svc in ('hautahaku', 'hautakartta', 'haudat'):
                for c in sorted(nc[k] - oc[k]):
                    lines.append(f'{svc}: {k}: uusi hautausmaa {c}')
                for c in sorted(oc[k] - nc[k]):
                    lines.append(f'{svc}: {k}: poistunut hautausmaa {c}')
            elif nc[k] != oc[k]:
                lines.append(f'{svc}: {k}: {next(iter(oc[k]))} -> {next(iter(nc[k]))}')
    return lines


# ---------------------------------------------------------------- pääohjelma
def main():
    ap = argparse.ArgumentParser(description='Päivitä hautahakupalveluiden kattavuustiedot')
    ap.add_argument('--dry-run', action='store_true', help='näytä muutokset, älä kirjoita tiedostoja')
    ap.add_argument('--skip', default='', help='ohitettavat lähteet pilkuilla: hautahaku,hautakartta,haudat,suomenkiha,genealogia,geneanet')
    ap.add_argument('--only', default='', help='päivitä vain nämä lähteet')
    args = ap.parse_args()
    skip = {s.strip() for s in args.skip.split(',') if s.strip()}
    only = {s.strip() for s in args.only.split(',') if s.strip()}

    def active(name):
        return name not in skip and (not only or name in only)

    os.makedirs(DATA, exist_ok=True)
    if os.path.exists(MAPFILE):
        mapping = json.load(open(MAPFILE, encoding='utf-8'))
    else:
        mapping = DEFAULT_MAPPING
        if not args.dry_run:
            json.dump(mapping, open(MAPFILE, 'w', encoding='utf-8'), ensure_ascii=False, indent=1)
            print('Luotiin', MAPFILE)
    for k in DEFAULT_MAPPING:
        mapping.setdefault(k, DEFAULT_MAPPING[k])

    old = json.load(open(OUT, encoding='utf-8')) if os.path.exists(OUT) else {}
    new = {
        'generated': dt.date.today().isoformat(),
        'note': 'Kattavuus poimittu palveluiden omista hautausmaaluetteloista skriptillä paivita-kattavuus.py.',
        'sources': {},
        'hautahaku': old.get('hautahaku', {'url': 'https://www.hautahaku.fi/fi', 'congregations': []}),
        'hautakartta': old.get('hautakartta', {'url': 'https://hautakartta.fi/', 'congregations': []}),
        'haudat': old.get('haudat', {'url': 'https://haudat.fi/', 'parishes': []}),
        'suomenkiha': old.get('suomenkiha', {'url': 'https://suomenkiha.fi/', 'municipalities': []}),
        'genealogia': old.get('genealogia', {'url': 'https://www.genealogia.fi/hautakivitietokanta/', 'municipalities': []}),
        'geneanet': old.get('geneanet', {'url': 'https://fi.geneanet.org/siviilihautausmaa/geo/FIN/suomi', 'regions': {}}),
        'opasteapp': old.get('opasteapp', {'url': 'https://www.opasteapp.fi/', 'instances': []}),
        'suvusto': old.get('suvusto', {'url': 'https://suvusto.fi/haudat/', 'municipalities': []}),
    }
    # säilytä vanhat lähdeaikaleimat
    new['sources'] = dict(old.get('sources', {}))

    steps = [
        ('hautakartta', lambda: {'url': 'https://hautakartta.fi/', 'congregations': fetch_hautakartta()}),
        ('hautahaku', lambda: {'url': 'https://www.hautahaku.fi/fi', 'congregations': fetch_hautahaku(mapping)}),
        ('haudat', lambda: {'url': 'https://haudat.fi/', 'parishes': fetch_haudat()}),
        ('suomenkiha', lambda: (lambda m, n: {'url': 'https://suomenkiha.fi/', 'directory_entries': n, 'municipalities': m})(*fetch_suomenkiha())),
        ('genealogia', lambda: {'url': 'https://www.genealogia.fi/hautakivitietokanta/', 'sheet': SHEET, 'municipalities': fetch_genealogia()}),
        ('geneanet', lambda: (lambda r: {'url': 'https://fi.geneanet.org/siviilihautausmaa/geo/FIN/suomi', 'regions': r, 'total_cemeteries': sum(r.values())})(fetch_geneanet())),
        ('opasteapp', lambda: {'url': 'https://www.opasteapp.fi/', 'instances': fetch_opasteapp()}),
        ('suvusto', lambda: {'url': 'https://suvusto.fi/haudat/', 'municipalities': fetch_suvusto()}),
    ]
    for name, fn in steps:
        if not active(name):
            print(f'{name}: ohitettu, säilytetään edelliset tiedot')
            continue
        print(f'{name}: noudetaan ...', flush=True)
        try:
            res = fn()
            n = len(res.get('congregations') or res.get('parishes') or res.get('municipalities') or res.get('regions') or res.get('instances') or [])
            if n == 0:
                raise ValueError('nouto palautti tyhjän luettelon')
            new[name] = res
            new['sources'][name] = {'fetched': dt.datetime.now().isoformat(timespec='minutes'), 'ok': True}
            print(f'{name}: OK, {n} kohdetta')
        except Exception as e:
            warn(f'{name}: nouto epäonnistui ({e}); säilytetään edelliset tiedot')
            new['sources'][name] = {'fetched': dt.datetime.now().isoformat(timespec='minutes'), 'ok': False, 'error': str(e)}

    new['kuntaindeksi'] = build_index(new, mapping)

    changes = diff(old, new) if old else ['(ensimmäinen ajo, ei vertailtavaa)']
    # uudet postitoimipaikat / seurakunnat, joille ei ole vastaavuutta
    unknown_po = sorted({g['postoffice'] for c in new['hautahaku']['congregations'] for g in c['cemeteries']
                         if g['postoffice'] and g['postoffice'] not in mapping['postitoimipaikka_kunta']})
    unknown_hk = sorted(c['slug'] for c in new['hautakartta']['congregations'] if c['slug'] not in mapping['hautakartta_kunnat'])
    unknown_hd = sorted(c['slug'] for c in new['haudat']['parishes'] if c['slug'] not in mapping['haudat_kunnat'])
    unknown_oa = sorted(c['slug'] for c in new.get('opasteapp', {}).get('instances', []) if c['slug'] not in mapping.get('opasteapp_kunnat', {}))
    todo = []
    if unknown_po: todo.append('Tarkista kunta näille hautahaku.fi:n postitoimipaikoille (kunta-vastaavuudet.json): ' + ', '.join(unknown_po))
    if unknown_hk: todo.append('Lisää kunnat näille hautakartta.fi-seurakunnille: ' + ', '.join(unknown_hk))
    if unknown_hd: todo.append('Lisää kunnat näille haudat.fi-seurakunnille: ' + ', '.join(unknown_hd))
    if unknown_oa: todo.append('Lisää kunnat näille opasteapp.fi-seurakunnille (opasteapp_kunnat): ' + ', '.join(unknown_oa))

    print('\nMuutokset edelliseen versioon:')
    for l in changes or ['(ei muutoksia)']:
        print(' ', l)
    for t in todo:
        print('\nTEHTÄVÄ:', t)

    if args.dry_run:
        print('\n--dry-run: tiedostoja ei kirjoitettu')
        return
    json.dump(new, open(OUT, 'w', encoding='utf-8'), ensure_ascii=False, indent=1)
    with open(LOG, 'a', encoding='utf-8') as f:
        f.write(f"\n=== {new['generated']} ===\n")
        for l in changes or ['(ei muutoksia)']:
            f.write(l + '\n')
        for t in todo:
            f.write('TEHTÄVÄ: ' + t + '\n')
    print('\nKirjoitettu', OUT, 'ja', LOG)


if __name__ == '__main__':
    main()
