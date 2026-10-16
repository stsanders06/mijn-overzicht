# Gegevens

Alles staat in `/data`:

- `overzicht.db` — SQLite, modus 0600
- `bestanden/` — uploads, alleen een gecontroleerde foto of PDF
- `secret_key` — sessiesleutel, niet in de back-up
- `options.json` — door de Supervisor geschreven; het wachtwoord wordt hieruit gelezen en niet gelogd

Bedragen staan in centen. Een kwartaalbedrag telt vier keer per jaar, een jaarbedrag één keer. Het maandtotaal is het jaartotaal gedeeld door 12, afgerond op een cent.

Een verzekering met “premie meetellen” maakt of werkt één vaste last bij (`verzekering_id`, uniek). Het dashboard telt alleen vaste lasten, dus de premie komt één keer voor. Haal je die last weg, dan stopt het meetellen; de verzekering blijft.

## Koppelingen

De tabel `koppelingen` bewaart één rij per paar. De twee kanten staan in vaste volgorde, zodat dezelfde link niet twee keer wordt opgeslagen. Op beide detailpagina’s staat hij onder **Gekoppeld**.

Een koppeling die uit een veld komt (premie die meetelt, of de verzekering van een voertuig) is vastgezet. Die haal je weg via dat veld. Andere koppelingen voeg je toe met het zoekveld en haal je weg met de knop ernaast.

Weghalen van een item wist zijn koppelingen aan beide kanten, plus de bestanden die eraan hangen.

## Inlog

Eén account. Zet het wachtwoord (minstens 8 tekens) in de add-on **vóór de eerste start**, en start opnieuw nadat je een optie wijzigt. Een leeg veld laat een bestaand wachtwoord staan en wist het niet. Is er nog geen account, dan staat er bij het starten een eenmalige instelcode in de uitvoer, ook als het logniveau waarschuwingen verbergt. `/instellen` accepteert alleen die code. Op schijf staat de hash, niet de code zelf. Een nieuwe start vervangt de code.

Wijzigen in de app kan alleen als de add-on geen wachtwoord heeft. Uitloggen, wijzigen in de app en wijzigen via de add-on verhogen een sessieversie en een vingerafdruk van de hash. Oude cookies werken daarna niet meer. Wie net zelf het wachtwoord in de app wijzigt, blijft ingelogd met een nieuw cookie.

Op http is het cookie HttpOnly en SameSite=Lax, zonder Secure. Het log waarschuwt dan dat ssl uit staat. Een meegestuurde `X-Forwarded-For` wordt dan genegeerd. Met `ssl: true` leest de app `certfile` en `keyfile` uit `/ssl` en laat nginx het verkeer afsluiten. Nginx overschrijft `X-Forwarded-For` met het adres van de verbinding; de app vertrouwt die kop alleen omdat het verzoek van localhost komt. Waitress blijft http, alleen op localhost. Het cookie wordt Secure en de site stuurt HSTS voor één dag (`max-age=86400`). Ontbreekt het certificaat, dan start de add-on niet (geen stille terugval naar http). In het log staat het adres als `https://…`. Stopt nginx of de webserver, dan stopt de add-on.

Foute pogingen: na 3 mislukkingen vanaf hetzelfde adres wacht het inloggen 1 seconde, daarna 2, 4, enzovoort, tot 60 seconden. Tijdens die pauze weigert dat adres ook een juist wachtwoord, en nieuwe pogingen vanaf dat adres tellen niet extra mee. Elke foute poging telt wel mee, ook als er al vanaf andere adressen is geprobeerd. Daardoor loopt de pauze per adres op en blijft het totale aantal gokken laag. Een juist wachtwoord vanaf een adres dat zelf niet in de pauze zit, werkt meteen. Elk formulier stuurt een CSRF-kenmerk mee.

Is het wachtwoord in de database leeg (na het terugzetten van een back-up), dan zegt de inlogpagina dat je het in de add-on moet zetten en opnieuw moet starten.

Zet poort 8320 niet open naar internet. Gebruik het eigen netwerk of een VPN (WireGuard of Tailscale), of https via de certificaten van Home Assistant.

## Back-up

De zip bevat `overzicht.db` en `bestanden/`. In die kopie van de database is de wachtwoord-hash leeg. `secret_key` en `options.json` zitten er niet in. De draaiende database houdt het wachtwoord. Na terugzetten zet je het wachtwoord in de add-on en start je opnieuw.
