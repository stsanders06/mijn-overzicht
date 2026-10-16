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

Eén account. Het wachtwoord uit de add-on (minstens 8 tekens) wint bij het starten. Een leeg veld laat het wachtwoord in de database staan. Wijzigen in de app kan alleen als de add-on geen wachtwoord heeft.

De sessie is HttpOnly en SameSite=Lax, zonder Secure, omdat de site op http in het eigen netwerk draait. Na vijf foute pogingen wacht het inloggen een kwartier. Elk formulier stuurt een CSRF-kenmerk mee.
