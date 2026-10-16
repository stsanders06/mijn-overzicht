# Changelog

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
