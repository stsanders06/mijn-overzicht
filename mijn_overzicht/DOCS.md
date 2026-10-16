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

Eén account. Zet het wachtwoord (minstens 8 tekens) in de add-on **vóór de eerste start**, en start opnieuw nadat je een optie wijzigt. Een leeg veld laat een bestaand wachtwoord staan en wist het niet. Is er nog geen account, dan staat er bij het starten een eenmalige instelcode in het log. `/instellen` accepteert alleen die code. Op schijf staat de hash, niet de code zelf. Een nieuwe start vervangt de code.

Wijzigen in de app kan alleen als de add-on geen wachtwoord heeft. Uitloggen, wijzigen in de app en wijzigen via de add-on verhogen een sessieversie en een vingerafdruk van de hash. Oude cookies werken daarna niet meer. Wie net zelf het wachtwoord in de app wijzigt, blijft ingelogd met een nieuw cookie.

Op http is het cookie HttpOnly en SameSite=Lax, zonder Secure. Met `ssl: true` leest de app `certfile` en `keyfile` uit `/ssl`, zet het cookie op Secure en stuurt HSTS. Ontbreekt het certificaat, dan start de add-on niet (geen stille terugval naar http).

Foute pogingen: na 3 mislukkingen wacht het inloggen 1 seconde, daarna 2, 4, enzovoort. Per adres is het plafond 60 seconden, voor het account 8 seconden. Een ander apparaat wacht dus hooguit 8 seconden, ook als iemand anders blijft proberen. Tijdens het wachten telt een nieuwe poging niet mee. Elk formulier stuurt een CSRF-kenmerk mee.

Zet poort 8320 niet open naar internet. Gebruik het eigen netwerk of een VPN (WireGuard of Tailscale), of https via de certificaten van Home Assistant.

## Back-up

De zip bevat `overzicht.db` en `bestanden/`. In die kopie van de database is de wachtwoord-hash leeg. `secret_key` en `options.json` zitten er niet in. De draaiende database houdt het wachtwoord. Na terugzetten zet je het wachtwoord in de add-on en start je opnieuw.
