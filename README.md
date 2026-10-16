# Mijn Overzicht

Persoonlijk overzicht voor vaste lasten, verzekeringen, voertuigen, bezittingen,
inkomen, datums, contacten, documenten en noodinfo. Het is een Home Assistant-add-on
die **niet** in de zijbalk van Home Assistant opent. Je gebruikt hem als een gewone
site op zijn eigen poort, met een eigen wachtwoord.

De site start leeg. Er staan geen voorbeeldgegevens in.

## Installeren

1. Voeg in Home Assistant onder **Instellingen → Add-ons → Add-onwinkel → ⋮ → Repositories** dit adres toe:

   `https://github.com/stsanders06/mijn-overzicht`

2. Installeer **Mijn Overzicht**. Zet **vóór de eerste start** een wachtwoord van minstens 8 tekens bij de add-on. Start daarna.
3. Open in de browser `http://<ip-van-home-assistant>:8320` als je op hetzelfde netwerk zit.

Wijzig je daarna een optie (wachtwoord of ssl), start de add-on opnieuw. Een leeg wachtwoordveld laat een bestaand wachtwoord staan. Alleen als er nog geen account is én het veld leeg is, schrijft de add-on een **eenmalige instelcode** in het log. Die code gebruik je op `/instellen`. Een nieuwe start maakt een nieuwe code.

**Zet poort 8320 niet open naar internet.** Geen port forward. Gebruik het thuisnetwerk, of een VPN zoals WireGuard of Tailscale. Wil je versleuteld verkeer, zet `ssl` aan en wijs `certfile` en `keyfile` naar certificaten in `/ssl` (de map is alleen-lezen gekoppeld). Dan wordt het cookie `Secure` en stuurt de site HSTS. Zonder ssl blijft het gewoon http op het eigen netwerk, en is het cookie niet `Secure`.

Uitloggen, het wachtwoord wijzigen in de site, en het wachtwoord wijzigen in de add-on maken oude sessies ongeldig.

Na een paar foute pogingen wacht het inloggen even, en daarna steeds iets langer. Vanaf hetzelfde adres loopt dat op tot hooguit 60 seconden. Voor het account zelf is het plafond 8 seconden, zodat een ander adres je niet lang buitensluit. Een geblokkeerde poging telt niet extra mee.

De back-up is een zip van de database en de bestanden. De wachtwoord-hash en `secret_key` zitten er niet in. Na terugzetten zet je het wachtwoord weer in de add-on en start je opnieuw.

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
- **Zoeken** over alle items, en een **back-up** als zip van de database en de bestanden, zonder wachtwoord-hash en zonder sessiesleutel.

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
