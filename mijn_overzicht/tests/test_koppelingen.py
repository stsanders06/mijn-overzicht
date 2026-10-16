"""Koppelingen zijn wederzijds, klikbaar, en verdwijnen mee met het item."""
import main as overzicht


def test_koppeling_staat_aan_beide_kanten_en_verwijderen_maakt_schoon(post, client):
    post("/lasten/nieuw", data={"naam": "Inboedelpremie", "categorie": "Verzekering", "bedrag": "12", "frequentie": "maand"})
    post("/contacten/nieuw", data={"naam": "Alarmcentrale", "rol": "verzekeraar", "telefoon": "08001234567"})
    antwoord = post("/koppelen", data={"van_type": "last", "van_id": "1", "naar_type": "contact", "naar_id": "1"})
    assert antwoord.status_code == 302
    last = client.get("/lasten/1").get_data(as_text=True)
    contact = client.get("/contacten/1").get_data(as_text=True)
    assert 'href="/contacten/1"' in last
    assert "Alarmcentrale" in last
    assert 'href="/lasten/1"' in contact
    assert "Inboedelpremie" in contact
    assert "Gekoppeld" in last
    post("/contacten/1/verwijder")
    daarna = client.get("/lasten/1").get_data(as_text=True)
    assert "Alarmcentrale" not in daarna
    conn = overzicht.verbind()
    assert conn.execute("SELECT COUNT(*) FROM koppelingen").fetchone()[0] == 0
    conn.close()


def test_item_weghalen_wist_ook_de_andere_kant(post):
    post("/bezittingen/nieuw", data={"naam": "Fiets", "aankoop": "2024-05-01"})
    post("/documenten/nieuw", data={"titel": "Aankoopbon"})
    post("/koppelen", data={"van_type": "bezit", "van_id": "1", "naar_type": "document", "naar_id": "1"})
    post("/bezittingen/1/verwijder")
    conn = overzicht.verbind()
    assert conn.execute("SELECT COUNT(*) FROM koppelingen").fetchone()[0] == 0
    conn.close()


def test_document_toont_de_bezitting_niet_meer_na_verwijderen(post, client):
    post("/bezittingen/nieuw", data={"naam": "Boormachine"})
    post("/documenten/nieuw", data={"titel": "Kassabon"})
    post("/koppelen", data={"van_type": "document", "van_id": "1", "naar_type": "bezit", "naar_id": "1"})
    assert "Boormachine" in client.get("/documenten/1").get_data(as_text=True)
    post("/bezittingen/1/verwijder")
    assert "Boormachine" not in client.get("/documenten/1").get_data(as_text=True)


def test_een_item_koppelt_niet_aan_zichzelf(post, client):
    post("/datums/nieuw", data={"soort": "rijbewijs", "naam": "Rijbewijs", "datum": "2031-01-01"})
    antwoord = post(
        "/koppelen",
        data={"van_type": "datum", "van_id": "1", "naar_type": "datum", "naar_id": "1"},
        follow_redirects=True,
    )
    assert "zichzelf" in antwoord.get_data(as_text=True)
    conn = overzicht.verbind()
    assert conn.execute("SELECT COUNT(*) FROM koppelingen").fetchone()[0] == 0
    conn.close()


def test_premie_link_is_wederzijds_en_niet_los_te_knippen(post, client):
    post("/verzekeringen/nieuw", data={
        "soort": "inboedel", "maatschappij": "Univé", "premie": "18,50",
        "frequentie": "maand", "telt_mee": "ja",
    })
    verzekering = client.get("/verzekeringen/1").get_data(as_text=True)
    last = client.get("/lasten/1").get_data(as_text=True)
    assert 'href="/lasten/1"' in verzekering
    assert 'href="/verzekeringen/1"' in last
    conn = overzicht.verbind()
    koppel_id = conn.execute("SELECT id FROM koppelingen").fetchone()[0]
    conn.close()
    antwoord = post("/koppelen/%s/verwijder" % koppel_id, data={"van_type": "verzekering", "van_id": "1"}, follow_redirects=True)
    assert "veld" in antwoord.get_data(as_text=True)
    conn = overzicht.verbind()
    assert conn.execute("SELECT COUNT(*) FROM koppelingen").fetchone()[0] == 1
    conn.close()


def test_voertuig_verzekering_en_document_zijn_klikbaar(post, client):
    post("/verzekeringen/nieuw", data={"soort": "motor", "maatschappij": "ANWB", "premie": "20", "frequentie": "maand"})
    post("/voertuigen/nieuw", data={"soort": "motor", "merk": "Honda", "verzekering_id": "1"})
    post("/documenten/nieuw", data={"titel": "Kentekenbewijs"})
    post("/koppelen", data={"van_type": "voertuig", "van_id": "1", "naar_type": "document", "naar_id": "1"})
    voertuig = client.get("/voertuigen/1").get_data(as_text=True)
    assert 'href="/verzekeringen/1"' in voertuig
    assert 'href="/documenten/1"' in voertuig
    assert "Honda" in client.get("/verzekeringen/1").get_data(as_text=True)
    assert "Kentekenbewijs" in client.get("/voertuigen").get_data(as_text=True)
    post("/voertuigen/1", data={"soort": "motor", "merk": "Honda", "verzekering_id": ""})
    conn = overzicht.verbind()
    vast = conn.execute(
        "SELECT COUNT(*) FROM koppelingen WHERE vast=1 AND (type_a='voertuig' OR type_b='voertuig')"
    ).fetchone()[0]
    conn.close()
    assert vast == 0
    assert "Kentekenbewijs" in client.get("/voertuigen/1").get_data(as_text=True)


def test_datum_koppelt_aan_het_item(post, client):
    post("/voertuigen/nieuw", data={"soort": "auto", "merk": "Volvo"})
    post("/datums/nieuw", data={"soort": "overig", "naam": "APK-herinnering", "datum": "2026-11-01"})
    post("/koppelen", data={"van_type": "datum", "van_id": "1", "naar_type": "voertuig", "naar_id": "1"})
    assert 'href="/voertuigen/1"' in client.get("/datums/1").get_data(as_text=True)
    assert "APK-herinnering" in client.get("/voertuigen/1").get_data(as_text=True)


def test_zoekveld_op_de_detailpagina_vindt_een_kandidaat(post, client):
    post("/contacten/nieuw", data={"naam": "Praxis Stad", "rol": "overig"})
    post("/bezittingen/nieuw", data={"naam": "Schroefmachine", "winkel": "Praxis"})
    tekst = client.get("/bezittingen/1?kies=Praxis").get_data(as_text=True)
    assert "Praxis Stad" in tekst
    assert 'name="naar_type" value="contact"' in tekst


def test_gebruiker_koppelt_gezondheid(post, client):
    post("/contacten/nieuw", data={"naam": "Tandarts", "rol": "tandarts"})
    post("/koppelen", data={"van_type": "contact", "van_id": "1", "naar_type": "gezondheid", "naar_id": "1"})
    assert "Tandarts" in client.get("/gezondheid").get_data(as_text=True)
    assert 'href="/gezondheid"' in client.get("/contacten/1").get_data(as_text=True)
