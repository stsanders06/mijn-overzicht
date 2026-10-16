# Changelog

## 0.1.6

- Op een iPhone stond de onderste balk achter de zwevende Safari-balk. De pagina scrolde in een kolom van 100dvh, en die hoogte legt de balk te laag. Het document scrolt nu zelf. De balk staat vast onderaan, met ruimte voor de thuisindicator, en de labels blijven daarboven helemaal zichtbaar. De inhoud schuift eronderdoor.
- Het menu Meer schoot bij openen eerst uit beeld en sprong daarna naar het midden. Het groeit nu vanaf de knop Meer, rechtsonder, en blijft in beeld.

## 0.1.5

- Het formulier voor inkomen heeft `novalidate`, net als de andere formulieren met verplichte velden. Een lege naam bij loon geeft “Vul een naam in.” van de server. De browser toont geen Engelse melding.

## 0.1.4

- De vertraging tot 2 seconden uit 0.1.3 sliep terwijl een slot vastlag. Daardoor stonden alle bezoekers achter elkaar en kon de site na een golf foute pogingen onbereikbaar blijven. Die slaap is weg. Zitten er in 30 seconden al 8 foute controles, dan krijgt een extra foute poging meteen “Probeer het later opnieuw.” (429), zonder hash. Een juist wachtwoord vanaf een adres dat in dat venster nog niet gefaald heeft, wordt meteen gecontroleerd op een eigen slot en wacht niet achter de aanval. Er lopen hooguit een paar hashes tegelijk; is dat vol, dan ook meteen 429.
- Stopt Python met SIGKILL, dan stopt nginx mee. Een klein hulpprogramma zet daarvoor het overlijdenssignaal, zonder preexec in het proces van de app.
- De app leest `X-Forwarded-For` niet meer zelf. In ssl-modus doet waitress dat, alleen vanaf localhost.
- Tussen een categoriekop en de kaart eronder zit 12 pixels, ook bij Vaste lasten en Inkomen.
- Verplichte velden geven een Nederlandse fout van de server. De browser toont geen Engelse melding meer.
- Afschrijfdag en Vanaf blijven allebei zichtbaar zonder JavaScript. Met JavaScript zie je alleen het veld dat bij de gekozen frequentie hoort.

## 0.1.3

- In 0.1.2 schreef nginx het bezoekersadres wel in `X-Forwarded-For`, maar waitress haalde die kop weg vóór de app. Daardoor deelden alle bezoekers op https één teller. In ssl-modus vertrouwt waitress alleen `X-Forwarded-For` van 127.0.0.1, één hop, en niet `X-Forwarded-Proto`. Op gewoon http blijft een meegestuurde kop genegeerd.
- Te veel foute pogingen in 30 seconden vertragen de controle kort, tot 2 seconden, voor iedereen. Een juist wachtwoord vanaf een adres dat zelf niet in de pauze zit, lukt daarna alsnog. Een adres dat in zijn pauze zit, wordt niet meer uit de lijst gezet als die vol raakt.
- Stopt Python met TERM of INT, dan stopt de add-on netjes met code 0. Nginx zit in een eigen processgroep en wordt mee gestopt, ook de werkprocessen. Certificaatkopieën gaan bij het stoppen weg. Nginx-fouten gaan naar stderr.
- Vanaf is zichtbaar zonder JavaScript. Bij een weekritme zonder die datum staat er een hint. “Binnenkort” zegt 60 dagen. Pauzes rekenen in UTC.
- Een kaart in een lijst opent het item. Koppelingen, telefoon, mail en de website blijven hun eigen link. Weghalen staat los van de kaart erboven.
- Koppen van een categorie staan direct boven de kaarten van die categorie.
- Inkomen kan een toeslag zijn (zorg, huur, kinderopvang, kindgebonden budget, kinderbijslag of anders), met hetzelfde bedrag, dezelfde frequentie en dezelfde betaaldag. Oude rijen blijven loon per maand.
- Het menu Meer schuift en vervaagt open vanaf de knop, ongeveer 200 ms. Bij minder beweging gebeurt dat niet.
- De onderste balk schuift niet meer over de inhoud. De pagina houdt ruimte over voor die balk en voor de thuisindicator. Marges en tussenruimte gebruiken dezelfde stappen, zodat knoppen en koppen niet tegen de tekst of de rand plakken.

## 0.1.2

- Nginx overschrijft `X-Forwarded-For` met het adres van de verbinding. Op gewoon http wordt een meegestuurde kop genegeerd.
- Elke foute inlogpoging telt voor dat adres, ook als er al vanaf andere adressen is geprobeerd. Een juist wachtwoord vanaf een adres dat zelf niet in de pauze zit, werkt meteen.
- Stopt nginx of de webserver, dan stopt de add-on en kan Home Assistant hem opnieuw starten.
- Nginx draait zonder root, verbergt zijn versie, en een te groot verzoek krijgt een eigen pagina.
- Vaste lasten kunnen elke week, elke 2 weken of elke 4 weken. Elke 4 weken telt 13 keer per jaar; per maand is dat bedrag keer 13 gedeeld door 12. Een datum “vanaf” toont de volgende afschrijving, op de last en bij Binnenkort.

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
