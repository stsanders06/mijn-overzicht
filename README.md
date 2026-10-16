# Mijn Overzicht

Persoonlijk overzicht voor vaste lasten, verzekeringen, voertuigen, bezittingen,
inkomen, datums, contacten, documenten en noodinfo. Het is een Home Assistant-add-on
die **niet** in de zijbalk van Home Assistant opent. Je gebruikt hem als een gewone
site op zijn eigen poort, met een eigen wachtwoord.

De site start leeg. Er staan geen voorbeeldgegevens in.

## Installeren

1. Voeg in Home Assistant onder **Instellingen → Add-ons → Add-onwinkel → ⋮ → Repositories** dit adres toe:

   `https://github.com/stsanders06/mijn-overzicht`

2. Installeer **Mijn Overzicht** en start de add-on.
3. Zet bij de add-on een wachtwoord van minstens 8 tekens, of laat het leeg en kies het de eerste keer dat je de site opent.
4. Open in de browser `http://<ip-van-home-assistant>:8320`.

De add-on heeft geen ingress en geen paneel. Hij is alleen bereikbaar op poort 8320.

Gegevens (database, uploads en het sessiegeheim) blijven in `/data` staan bij een update.

## Wat erin zit

- **Dashboard:** vaste lasten per maand en per jaar, wat er binnenkort afloopt, en wat je kunt opzeggen.
- **Vaste lasten & abonnementen:** bedrag, frequentie (maand, kwartaal, jaar), afschrijfdag, rekening, einddatum, opzegtermijn en automatische verlenging. Totalen zijn omgerekend naar een maand.
- **Verzekeringen:** soort, maatschappij, dekking, polis en premie. Zet “meetellen” aan om de premie één keer als vaste last te tellen.
- **Voertuigen:** kenteken, bouwjaar, APK, bandenmaat en documenten. Geen kilometerstand.
- **Bezittingen:** aankoop, winkel, prijs, garantie (“nog X maanden garantie” of “verlopen”) en de bon als foto of PDF, ook HEIC uit de fotobibliotheek.
- **Inkomen & werk, belangrijke datums, contacten, documenten, gezondheid / noodinfo.**
- **Gekoppeld:** elk item kan naar elk ander item wijzen. De link is aan beide kanten te zien en aanklikbaar. Zoeken, toevoegen en weghalen doe je op de detailpagina.
- **Zoeken** over alle items, en een **back-up** als zip van de database en de bestanden.

## Lokaal draaien

```bash
pip install -r mijn_overzicht/app/requirements.txt
DATA_DIR=./data PORT=8320 python3 mijn_overzicht/app/main.py
```

Tests:

```bash
pip install -r mijn_overzicht/tests/requirements.txt
python -m playwright install webkit
python -m pytest
```
