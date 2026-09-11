# Hautatietohaun avustaja

Sukututkijan apuväline, joka kokoaa yhteen kuusi suomalaisia hautatietoja tarjoavaa verkkopalvelua. Avustaja kertoo, mistä palveluista etsityn kunnan hautausmaat löytyvät, ja avaa kunkin palvelun oikeaan kohtaan – valmiiksi täytettynä, jos palvelu sen sallii.

Avustaja on **yksi HTML-tiedosto**, joka toimii selaimessa. Se ei hae, tallenna eikä välitä hautatietoja itse: kaikki haut tehdään palveluiden omilla sivuilla.

## Mukana olevat palvelut

| Palvelu | Aineisto | Ylläpitäjä |
|---|---|---|
| [hautahaku.fi](https://www.hautahaku.fi/fi) | Virallinen hautarekisteri, 15 seurakuntataloutta (mm. Helsinki, Espoo, Tampere, Vaasa, Pori, Kuopio) | Seurakunnat |
| [hautakartta.fi](https://hautakartta.fi/) | Virallinen hautarekisteri ja kartta, 25 seurakuntaa (mm. Turku, Oulu, Lahti, Jyväskylä, Joensuu, Mikkeli) | Geometrix Oy seurakuntien toimeksiannosta |
| [haudat.fi](https://haudat.fi/) | Virallinen hautarekisteri, 11 pienempää seurakuntaa | Vitec Software |
| [suomenkiha.fi](https://suomenkiha.fi/) | Hautakivikuvat ja indeksoidut nimet, lähes koko Suomi | Suomen kirkkoja ja hautausmaita -yhteisö |
| [Hautakivitietokanta](https://www.genealogia.fi/hautakivitietokanta/) | Hautakivikuvat ja indeksoidut nimet, koko Suomi | Suomen Sukututkimusseura |
| [Geneanet](https://fi.geneanet.org/siviilihautausmaa/) | Yhteisöllinen hautakivikokoelma, Suomesta 179 hautausmaata | Geneanet |

## Käyttö

Toimiva versio on julkaistu verkossa: [https://zygge60.github.io/hautatietohaun-avustaja/](https://zygge60.github.io/hautatietohaun-avustaja/)

Omalla koneella:

1. Lataa [`index.html`](index.html) ja [`kayttoohje.html`](kayttoohje.html) samaan kansioon ja avaa `index.html` selaimessa.
2. Kirjoita sukunimi ja/tai valitse kunta. Kunnan valinta näyttää heti, missä palveluissa kunnan hautausmaat ovat.
3. Paina **Hae** ja avaa palvelut painikkeista. Palveluissa, jotka eivät tue valmiiksi täytettyä linkkiä, painike kopioi hakusanan leikepöydälle liitettäväksi.

Tarkempi ohje: [kayttoohje.html](kayttoohje.html) (aukeaa myös avustajan Käyttöohje-painikkeesta).

## Tiedostot

```
index.html               valmis avustaja (rakennetaan pohjasta ja datasta)
kayttoohje.html          käyttöohje; pidettävä samassa kansiossa kuin index.html
template.html            avustajan pohja; kattavuusdata upotetaan merkinnän /*__DATA__*/ kohdalle
kattavuus.json           palveluiden hautausmaaluettelot ja kuntaindeksi (koneellisesti päivitettävä)
kunta-vastaavuudet.json  käsin ylläpidettävä taulukko: postitoimipaikka -> kunta, seurakunta -> kunnat,
                         lakkautettu kunta -> nykyinen kunta
kattavuus-muutokset.txt  päivitysskriptin muutosloki (syntyy ensimmäisellä ajolla)
paivita-kattavuus.py     noutaa palveluiden hautausmaaluettelot ja päivittää kattavuus.json
rakenna-avustaja.py      upottaa datan pohjaan ja tuottaa index.html
```

Kaikki tiedostot ovat samassa kansiossa; skriptit lukevat ja kirjoittavat tiedostoja omasta kansiostaan.

## Kattavuustietojen päivittäminen

Palveluihin liittyy uusia seurakuntia muutaman kerran vuodessa ja suomenkiha.fi:hin lisätään hautausmaita jatkuvasti. Päivitys tehdään Python-skripteillä, jotka edellyttävät Python 3.8:aa tai uudempaa sekä requests-kirjastoa. Kattavuus päivitetään tiedostojen kansiossa:

```
pip install requests
python paivita-kattavuus.py --dry-run   # näyttää muutokset kirjoittamatta mitään
python paivita-kattavuus.py             # päivittää kattavuus.json ja muutoslokin
python rakenna-avustaja.py              # kokoaa uuden index.html-tiedoston
```

Skripti lukee kunkin palvelun oman hautausmaaluettelon (hautakartta.fi:n seurakuntarajapinta, hautahaku.fi:n sovelluspaketin taulukko, haudat.fi:n seurakuntasivut, suomenkiha.fi:n hakemisto, Hautakivitietokannan hautausmaaluettelo ja Geneanetin maakuntasivu), vertaa sitä edelliseen versioon ja tulostaa muutokset. Jos jokin lähde ei toimi, sen edelliset tiedot säilyvät ja skripti varoittaa. Kun luetteloon ilmestyy uusi seurakunta tai postitoimipaikka, jolle ei ole kuntavastaavuutta, skripti pyytää lisäämään sen `kunta-vastaavuudet.json`-tiedostoon.

Valitsimilla `--only` ja `--skip` voi rajata päivityksen tiettyihin palveluihin.

## Miten avustaja toimii palveluiden kanssa

Avustaja rakentaa kullekin palvelulle linkin, jonka käyttäjä avaa itse.

Hautakivitietokanta ja Geneanet tukevat osoiteparametreja, joten linkki avaa hakusivun hakuehdot valmiiksi täytettyinä.

Hautahaku.fi, hautakartta.fi ja suomenkiha.fi eivät tue osoiteparametreja. Niissä avustaja avaa palvelun oikeaan kohtaan (esimerkiksi hautakartta.fi:ssä valitun seurakunnan hautakarttaan) ja kopioi hakusanan leikepöydälle palvelun odottamassa muodossa.

Haudat.fi:n käyttöehdot kieltävät syvälinkityksen ilman lupaa, joten siihen ei tehdä täytettyä linkkiä, vaikka palvelu sen teknisesti sallisi.

Avustaja ei kutsu palveluiden hakurajapintoja. Kattavuustietojen päivitysskripti lukee vain palveluiden hautausmaaluetteloita, ei henkilötietoja, ja tekee sen harvakseltaan tunnistettavalla User-Agent-otsakkeella.

## Tunnetut rajoitukset

Vantaan, Keravan ja Vihdin seurakuntien OpasteApp-palvelu ei ole vielä mukana (Vihti löytyy haudat.fi:stä).

Kuntaindeksi perustuu palveluiden hautausmaaluetteloihin ja käsin ylläpidettyihin kuntaliitostietoihin. Jos jokin lakkautettu kunta ohjaa väärään nykyiseen kuntaan, korjaus tehdään `kunta-vastaavuudet.json`-tiedostoon.

Kattavuusluettelo vanhenee hitaasti; Asetukset ja tiedot -osio näyttää, milloin se on päivitetty.

## Osallistuminen

Virheilmoitukset ja parannusehdotukset ovat tervetulleita issue-toiminnon kautta. Erityisen hyödyllisiä ovat havainnot palveluiden muuttuneesta rakenteesta (päivitysskriptin varoitukset) ja puuttuvista kuntavastaavuuksista.

## Lisenssi

Ohjelmakoodi: valitse lisenssi ennen julkaisua (esimerkiksi MIT). Hautatiedot ovat kunkin palvelun ylläpitäjän aineistoa ja niiden käyttöä säätelevät palveluiden omat käyttöehdot; tässä projektissa on vain palveluiden julkiset hautausmaaluettelot.

## Tekijä

Jari Aro, jari.t.aro@gmail.com
