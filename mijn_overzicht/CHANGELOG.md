# Changelog

## 0.1.2

- Achter nginx telt het echte bezoekersadres, niet 127.0.0.1. Op gewoon http wordt een meegestuurde X-Forwarded-For genegeerd.
- Elke foute inlogpoging telt voor dat adres, ook als er al vanaf andere adressen is geprobeerd. Een juist wachtwoord vanaf een adres dat zelf niet in de pauze zit, werkt meteen.
- Stopt nginx of de webserver, dan stopt de add-on en kan Home Assistant hem opnieuw starten.
- Nginx draait zonder root, verbergt zijn versie, en een te groot verzoek krijgt een eigen pagina.

## 0.1.1

- Https loopt via nginx naar de app op localhost. Een open verbinding of een groot bestand blokkeert de andere bezoekers niet meer.
- Een juist wachtwoord wordt niet tegengehouden door foute pogingen vanaf andere adressen. Na foute pogingen wacht alleen dat adres zelf, tot hooguit 60 seconden.
- Het menu Meer sluit ook als je erbuiten tikt.
- De eenmalige instelcode staat altijd in de uitvoer. Na een teruggezette back-up zegt de inlogpagina dat je het wachtwoord in de add-on moet zetten en opnieuw moet starten.
- Zonder ssl waarschuwt het log dat het verkeer http is. Met ssl stuurt de site HSTS voor één dag.

## 0.1.0

Eerste versie.

Zet **vóór de eerste start** een wachtwoord van minstens 8 tekens in de add-on, en start daarna opnieuw als je een optie wijzigt. Laat je het veld leeg terwijl er nog geen account is, dan staat een eenmalige instelcode in het log; `/instellen` werkt alleen met die code. Open daarna `http://<ip-van-home-assistant>:8320` op het eigen netwerk. Zet de poort niet open naar internet. Gebruik een VPN (WireGuard of Tailscale) of zet `ssl` aan met certificaten uit `/ssl`. De app staat niet in de zijbalk van Home Assistant.

- Dashboard met vaste lasten per maand en per jaar, wat er binnenkort afloopt,
  en wat je kunt opzeggen of wat vanzelf stopt.
- Vaste lasten en abonnementen, verzekeringen, voertuigen, bezittingen met
  garantie en bon, inkomen, belangrijke datums, contacten, documenten en
  noodinfo.
- Items kunnen naar elkaar verwijzen. Elke koppeling is aan beide kanten
  zichtbaar en aanklikbaar, onder Gekoppeld op de detailpagina.
- Eigen opmaak: papier en teal, een zijbalk op een groot scherm en een
  tabbalk onderaan op de telefoon.
- Eigen inlog. Sessies vervallen bij uitloggen en bij een wachtwoordwijziging
  (in de site of in de add-on). Foute pogingen wachten exponentieel, hooguit
  60 seconden per adres en 8 seconden voor het account.
- Back-up als zip van de database en de bestanden, zonder wachtwoord-hash en
  zonder sessiesleutel. Gegevens blijven in `/data` staan bij een update.
