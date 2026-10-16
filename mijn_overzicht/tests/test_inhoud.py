"""CRUD, totalen, garantie, uploads en back-up."""
import io
import os
import sqlite3
import tempfile
import zipfile
from datetime import date, timedelta

import main as overzicht


PNG = (
    b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01\x08\x06\x00\x00\x00"
    b"\x1f\x15\xc4\x89\x00\x00\x00\nIDATx\x9cc\x00\x01\x00\x00\x05\x00\x01\r\n-\xb4\x00\x00\x00\x00IEND\xaeB`\x82"
)
HEIC = b"\x00\x00\x00\x18ftypheic\x00\x00\x00\x00heic" + b"\x00\x00\x00\x00"
PDF = b"%PDF-1.4\n1 0 obj<<>>endobj\ntrailer<<>>\n%%EOF"


def test_verse_database_toont_nul(client):
    tekst = client.get("/").get_data(as_text=True)
    assert "€ 0,00" in tekst
    assert "Nog geen" not in tekst or "0 vaste lasten" in tekst


def test_totalen_rekenen_maand_kwartaal_en_jaar_omgerekend(post, client):
    post("/lasten/nieuw", data={"naam": "Huur", "categorie": "Wonen", "bedrag": "10", "frequentie": "maand"})
    post("/lasten/nieuw", data={"naam": "Vereniging", "categorie": "Wonen", "bedrag": "10", "frequentie": "kwartaal"})
    post("/lasten/nieuw", data={"naam": "Gemeente", "categorie": "Gemeente", "bedrag": "10", "frequentie": "jaar"})
    tekst = client.get("/").get_data(as_text=True)
    assert "€ 14,17" in tekst
    assert "€ 170,00" in tekst


def test_last_bewerken_en_weghalen(post, client):
    post("/lasten/nieuw", data={
        "naam": "Netflix", "categorie": "Abonnement", "bedrag": "15,99", "frequentie": "maand",
        "rekening": "ING betaal", "afschrijfdag": "4", "notitie": "deelt met huis",
    })
    tekst = client.get("/lasten/1").get_data(as_text=True)
    assert "Netflix" in tekst
    assert "15,99" in tekst
    post("/lasten/1", data={"naam": "Videoland", "categorie": "Abonnement", "bedrag": "5", "frequentie": "maand"})
    assert "Videoland" in client.get("/lasten").get_data(as_text=True)
    post("/lasten/1/verwijder")
    assert "Videoland" not in client.get("/lasten").get_data(as_text=True)


def test_html_in_een_naam_wordt_geescaped(post, client):
    post("/lasten/nieuw", data={"naam": "<script>alert(1)</script>", "categorie": "Overig", "bedrag": "1", "frequentie": "maand"})
    tekst = client.get("/lasten").get_data(as_text=True)
    assert "<script>alert" not in tekst
    assert "&lt;script&gt;" in tekst


def test_premie_telt_een_keer_mee(post, client):
    post("/verzekeringen/nieuw", data={
        "soort": "auto", "maatschappij": "Centraal Beheer", "premie": "50",
        "frequentie": "maand", "telt_mee": "ja",
    })
    post("/lasten/nieuw", data={"naam": "Huur", "categorie": "Wonen", "bedrag": "10", "frequentie": "maand"})
    tekst = client.get("/").get_data(as_text=True)
    assert "€ 60,00" in tekst
    assert "€ 720,00" in tekst
    conn = overzicht.verbind()
    assert conn.execute("SELECT COUNT(*) FROM vaste_lasten").fetchone()[0] == 2
    conn.close()
    last = client.get("/lasten/1").get_data(as_text=True)
    assert "readonly" in last
    post("/lasten/1", data={"naam": "Andere naam", "categorie": "Overig", "bedrag": "1", "frequentie": "jaar", "rekening": "creditcard"})
    conn = overzicht.verbind()
    rij = conn.execute("SELECT naam, bedrag_cent, rekening FROM vaste_lasten WHERE id=1").fetchone()
    conn.close()
    assert rij["bedrag_cent"] == 5000
    assert rij["rekening"] == "creditcard"
    assert "Centraal Beheer" in rij["naam"]


def test_verzekering_weghalen_haalt_de_premie_mee(post):
    post("/verzekeringen/nieuw", data={
        "soort": "zorg", "maatschappij": "CZ", "premie": "140", "frequentie": "maand", "telt_mee": "ja",
    })
    post("/verzekeringen/1/verwijder")
    conn = overzicht.verbind()
    assert conn.execute("SELECT COUNT(*) FROM verzekeringen").fetchone()[0] == 0
    assert conn.execute("SELECT COUNT(*) FROM vaste_lasten").fetchone()[0] == 0
    conn.close()


def test_voertuig_zonder_kilometerstand(post, client):
    post("/voertuigen/nieuw", data={"soort": "motor", "merk": "Yamaha", "model": "MT-07", "kenteken": "ab-12-cd", "bouwjaar": "2019"})
    tekst = client.get("/voertuigen").get_data(as_text=True)
    assert "Yamaha" in tekst
    assert "AB12CD" in client.get("/voertuigen/1").get_data(as_text=True)
    assert "kilometer" not in client.get("/voertuigen/nieuw").get_data(as_text=True).lower()


def test_garantie_badge_en_expliciete_einddatum_wint(post, client):
    vandaag = date.today()
    tot = (vandaag.replace(day=1) + timedelta(days=70)).isoformat()
    post("/bezittingen/nieuw", data={
        "naam": "Boormachine", "aankoop": "2020-01-15", "garantie_maanden": "12",
        "garantie_tot": tot, "winkel": "Praxis", "prijs": "89,50",
    })
    tekst = client.get("/bezittingen").get_data(as_text=True)
    assert "nog " in tekst
    assert "garantie" in tekst
    assert "badge verlopen" not in tekst
    verlopen = overzicht.garantie_badge("2020-01-01", 12, None, date(2022, 1, 1))
    assert verlopen["tekst"] == "verlopen"
    bijna = overzicht.garantie_badge(None, None, date.today().isoformat(), date.today())
    assert bijna["tekst"] == "verloopt vandaag"
    assert overzicht.tel_maanden_op(date(2023, 1, 31), 1) == date(2023, 2, 28)
    assert overzicht.tel_maanden_op(date(2024, 1, 31), 1) == date(2024, 2, 29)
    einde = overzicht.garantie_einde("2020-01-01", 6, "2030-05-01")
    assert einde == date(2030, 5, 1)


def test_maanden_garantie_tekst():
    op = date(2026, 1, 15)
    badge = overzicht.garantie_badge("2026-01-15", 3, None, op)
    assert badge["tekst"] == "nog 3 maanden garantie"
    kort = overzicht.garantie_badge(None, None, "2026-01-20", op)
    assert kort["tekst"] == "nog 5 dagen garantie"


def test_opzegadvies():
    op = date(2026, 6, 1)
    altijd = overzicht.opzeg_advies(None, 0, True, op)
    assert altijd["soort"] == "opzegbaar"
    einde = (op + timedelta(days=30)).isoformat()
    advies = overzicht.opzeg_advies(einde, 14, True, op)
    assert "Zeg op vóór" in advies["tekst"]
    stopt = overzicht.opzeg_advies(einde, None, False, op)
    assert stopt["soort"] == "loopt_af"


def test_bon_png_heic_en_pdf_en_html_wordt_geweigerd(post, client):
    antwoord = post(
        "/bezittingen/nieuw",
        data={"naam": "Lamp", "aankoop": "2026-01-01"},
        content_type="multipart/form-data",
    )
    # zonder bestanden alsnog opslaan
    assert antwoord.status_code == 302
    post(
        "/bezittingen/1",
        data={
            "naam": "Lamp",
            "bon": (io.BytesIO(PNG), "bon.png"),
            "bestanden": (io.BytesIO(b"<html>nee</html>"), "virus.html"),
        },
        content_type="multipart/form-data",
    )
    tekst = client.get("/bezittingen/1").get_data(as_text=True)
    assert "bon.png" in tekst
    assert "Niet toegevoegd: virus.html" in tekst
    assert tekst.count(">Weghalen<") == 2
    plaatje = client.get("/bestand/1")
    assert plaatje.status_code == 200
    assert plaatje.mimetype == "image/png"
    assert plaatje.data.startswith(b"\x89PNG")
    post(
        "/documenten/nieuw",
        data={"titel": "Polis", "bestanden": (io.BytesIO(PDF), "polis.pdf")},
        content_type="multipart/form-data",
    )
    pdf = client.get("/bestand/2")
    assert pdf.mimetype == "application/pdf"
    assert pdf.headers["X-Frame-Options"] == "SAMEORIGIN"
    assert "frame-ancestors 'self'" in pdf.headers["Content-Security-Policy"]
    assert "sandbox" in pdf.headers["Content-Security-Policy"]
    pagina = client.get("/")
    assert pagina.headers["X-Frame-Options"] == "DENY"
    assert "frame-ancestors 'none'" in pagina.headers["Content-Security-Policy"]
    assert "unsafe-inline" not in pagina.headers["Content-Security-Policy"]
    post(
        "/voertuigen/nieuw",
        data={
            "soort": "auto", "merk": "Test",
            "bestanden": (io.BytesIO(HEIC), "foto.heic"),
        },
        content_type="multipart/form-data",
    )
    assert client.get("/bestand/3").mimetype == "image/heic"


def test_backup_bevat_database_en_bestanden_niet_de_sleutel(post, client):
    post("/lasten/nieuw", data={"naam": "Water", "categorie": "Water", "bedrag": "20", "frequentie": "maand"})
    post(
        "/documenten/nieuw",
        data={"titel": "Contract", "bestanden": (io.BytesIO(PDF), "contract.pdf")},
        content_type="multipart/form-data",
    )
    antwoord = post("/backup")
    archief = zipfile.ZipFile(io.BytesIO(antwoord.data))
    namen = archief.namelist()
    assert "overzicht.db" in namen
    assert any(naam.startswith("bestanden/") for naam in namen)
    assert not any("secret" in naam or naam.endswith("options.json") for naam in namen)
    fd, pad = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    try:
        with open(pad, "wb") as bestand:
            bestand.write(archief.read("overzicht.db"))
        kopie = sqlite3.connect(pad)
        assert kopie.execute("SELECT wachtwoord FROM account WHERE id=1").fetchone()[0] == ""
        kopie.close()
    finally:
        os.remove(pad)
    live = overzicht.verbind()
    assert live.execute("SELECT wachtwoord FROM account WHERE id=1").fetchone()[0]
    live.close()


def test_overige_tabbladen_en_zoeken(post, client):
    post("/inkomen/nieuw", data={"werkgever": "Bakkerij", "uren": "32", "netto": "2400", "betaaldag": "25"})
    post("/datums/nieuw", data={"soort": "paspoort", "naam": "Paspoort", "datum": "2030-04-01"})
    post("/contacten/nieuw", data={"naam": "Huisarts", "rol": "huisarts", "telefoon": "0612345678", "email": "arts@voorbeeld.nl"})
    post("/gezondheid", data={"bloedgroep": "O+", "medicijnen": "geen", "allergieen": "pinda", "nood_naam": "Sam"})
    assert "Bakkerij" in client.get("/inkomen").get_data(as_text=True)
    assert "€ 2.400,00" in client.get("/").get_data(as_text=True)
    assert "Paspoort" in client.get("/datums").get_data(as_text=True)
    assert "tel:+31612345678" in client.get("/contacten").get_data(as_text=True) or "tel:0612345678" in client.get("/contacten").get_data(as_text=True)
    assert "pinda" in client.get("/gezondheid").get_data(as_text=True)
    gevonden = client.get("/zoeken?q=pinda").get_data(as_text=True)
    assert "Gezondheid" in gevonden
    assert "minstens twee" in client.get("/zoeken?q=p").get_data(as_text=True)


def test_dashboard_noemt_apk_en_opzeggen(post, client):
    binnenkort = (date.today() + timedelta(days=20)).isoformat()
    post("/voertuigen/nieuw", data={"soort": "auto", "merk": "Fiat", "apk_tot": binnenkort})
    post("/lasten/nieuw", data={
        "naam": "Sportschool", "categorie": "Abonnement", "bedrag": "30", "frequentie": "maand",
        "contract_eind": (date.today() + timedelta(days=40)).isoformat(),
        "opzegtermijn_dagen": "30", "automatisch": "ja",
    })
    tekst = client.get("/").get_data(as_text=True)
    assert "Fiat" in tekst
    assert "Sportschool" in tekst
    assert "Zeg op vóór" in tekst
