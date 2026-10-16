"""Inlog, eerste keer, CSRF en het wachtwoord uit de add-on."""
import json
import pathlib

from conftest import TEST_WACHTWOORD
import main as overzicht


def test_lettertypen_zijn_zonder_inlog_bereikbaar(app):
    with app.test_client() as browser:
        antwoord = browser.get("/static/fonts/atelier-sans.woff2")
    assert antwoord.status_code == 200
    assert antwoord.mimetype in {"font/woff2", "application/octet-stream", "font/woff"}


def test_zonder_sessie_kom_je_op_inloggen(app):
    with app.test_client() as browser:
        antwoord = browser.get("/")
    assert antwoord.status_code == 302
    assert "/inloggen" in antwoord.headers["Location"]


def test_eerste_keer_kies_je_een_wachtwoord(zonder_account):
    assert zonder_account.get("/instellen").status_code == 200
    antwoord = zonder_account.post(
        "/instellen",
        data={"csrf_token": "test-token", "wachtwoord": "lang-wachtwoord", "nogmaals": "lang-wachtwoord"},
        follow_redirects=True,
    )
    assert antwoord.status_code == 200
    assert "Dashboard" in antwoord.get_data(as_text=True)
    conn = overzicht.verbind()
    assert conn.execute("SELECT COUNT(*) FROM vaste_lasten").fetchone()[0] == 0
    conn.close()


def test_te_kort_wachtwoord_bij_instellen_blijft_zonder_account(zonder_account):
    zonder_account.post(
        "/instellen",
        data={"csrf_token": "test-token", "wachtwoord": "kort", "nogmaals": "kort"},
        follow_redirects=True,
    )
    assert not overzicht.heeft_account()


def test_inloggen_en_uitloggen(uitgelogde_client):
    antwoord = uitgelogde_client.post(
        "/inloggen",
        data={"csrf_token": "test-token", "wachtwoord": TEST_WACHTWOORD, "onthoud": "ja"},
        follow_redirects=True,
    )
    tekst = antwoord.get_data(as_text=True)
    assert "Dashboard" in tekst
    token = tekst.split('name="csrf_token" value="', 1)[1].split('"', 1)[0]
    antwoord = uitgelogde_client.post("/uitloggen", data={"csrf_token": token}, follow_redirects=False)
    assert antwoord.status_code == 302
    assert uitgelogde_client.get("/").status_code == 302


def test_fout_wachtwoord(uitgelogde_client):
    antwoord = uitgelogde_client.post(
        "/inloggen",
        data={"csrf_token": "test-token", "wachtwoord": "fout"},
        follow_redirects=True,
    )
    assert "klopt niet" in antwoord.get_data(as_text=True)


def test_vijf_fouten_zetten_een_pauze(uitgelogde_client):
    for _ in range(5):
        uitgelogde_client.post("/inloggen", data={"csrf_token": "test-token", "wachtwoord": "fout"})
    pagina = uitgelogde_client.get("/inloggen").get_data(as_text=True)
    assert "Wacht" in pagina


def test_post_zonder_csrf_wordt_geweigerd(client):
    antwoord = client.post("/lasten/nieuw", data={"naam": "Huur"})
    assert antwoord.status_code == 400


def test_wachtwoord_wijzigen(client, post):
    antwoord = post(
        "/wachtwoord",
        data={"huidig": TEST_WACHTWOORD, "nieuw": "ander-wachtwoord", "nogmaals": "ander-wachtwoord"},
        follow_redirects=True,
    )
    assert "gewijzigd" in antwoord.get_data(as_text=True)


def test_opties_wachtwoord_wint_en_blokkeert_wijzigen_in_de_app(client, post, uitgelogde_client):
    pathlib.Path(overzicht.OPTIONS_PATH).write_text(
        json.dumps({"wachtwoord": "addon-wachtwoord"}), encoding="utf-8"
    )
    overzicht.synchroniseer_wachtwoord()
    antwoord = post(
        "/wachtwoord",
        data={"huidig": "addon-wachtwoord", "nieuw": "weer-een-ander", "nogmaals": "weer-een-ander"},
        follow_redirects=True,
    )
    assert "add-on" in antwoord.get_data(as_text=True)
    antwoord = uitgelogde_client.post(
        "/inloggen",
        data={"csrf_token": "test-token", "wachtwoord": "addon-wachtwoord"},
        follow_redirects=True,
    )
    assert "Dashboard" in antwoord.get_data(as_text=True)


def test_open_redirect_wordt_niet_gevolgd(uitgelogde_client):
    antwoord = uitgelogde_client.post(
        "/inloggen",
        data={"csrf_token": "test-token", "wachtwoord": TEST_WACHTWOORD, "verder": "https://example.test"},
        follow_redirects=False,
    )
    assert antwoord.headers["Location"].endswith("/")
