# Changelog

## 0.1.0

Eerste versie.

Na het installeren: **zet een wachtwoord** in de add-on, of kies het de eerste
keer dat je de site opent. Open daarna `http://<ip-van-home-assistant>:8320`.
De app staat niet in de zijbalk van Home Assistant.

- Dashboard met vaste lasten per maand en per jaar, wat er binnenkort afloopt,
  en wat je kunt opzeggen of wat vanzelf stopt.
- Vaste lasten en abonnementen, verzekeringen, voertuigen, bezittingen met
  garantie en bon, inkomen, belangrijke datums, contacten, documenten en
  noodinfo.
- Items kunnen naar elkaar verwijzen. Elke koppeling is aan beide kanten
  zichtbaar en aanklikbaar, onder Gekoppeld op de detailpagina.
- Eigen opmaak: papier en teal, een zijbalk op een groot scherm en een
  tabbalk onderaan op de telefoon.
- Eigen inlog met een gehasht wachtwoord, een sessie, CSRF-bescherming en een
  limiet op mislukte pogingen. De site draait buiten Home Assistant.
- Back-up als zip van de database en de bestanden. Gegevens blijven in `/data`
  staan bij een update.
