"""Inlog, eerste keer, CSRF, sessies en het wachtwoord uit de add-on."""
import json
import pathlib

from conftest import TEST_HASH, TEST_WACHTWOORD
import main as overzicht


def _koek(browser):
    browser.get("/")
    koek = browser.get_cookie("session")
    assert koek is not None
    return koek.value


def _andere_client(app, waarde):
    ander = app.test_client()
    ander.set_cookie("session", waarde)
    return ander


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


def test_instellen_zonder_code_maakt_geen_account(zonder_account):
    assert zonder_account.get("/instellen").status_code == 200
    antwoord = zonder_account.post(
        "/instellen",
        data={
            "csrf_token": "test-token",
            "code": "verzonnen",
            "wachtwoord": "lang-wachtwoord",
            "nogmaals": "lang-wachtwoord",
        },
        follow_redirects=True,
    )
    assert antwoord.status_code == 200
    assert not overzicht.heeft_account()
    assert "klopt niet" in antwoord.get_data(as_text=True)


def test_eerste_keer_met_code_uit_het_log(zonder_account):
    code = overzicht.zorg_setup_code()
    assert code
    op_schijf = pathlib.Path(overzicht.SETUP_PATH).read_text(encoding="utf-8")
    assert code not in op_schijf
    antwoord = zonder_account.post(
        "/instellen",
        data={
            "csrf_token": "test-token",
            "code": code,
            "wachtwoord": "lang-wachtwoord",
            "nogmaals": "lang-wachtwoord",
        },
        follow_redirects=True,
    )
    assert "Dashboard" in antwoord.get_data(as_text=True)
    assert not pathlib.Path(overzicht.SETUP_PATH).exists()
    conn = overzicht.verbind()
    assert conn.execute("SELECT COUNT(*) FROM vaste_lasten").fetchone()[0] == 0
    conn.close()
    opnieuw_token = zonder_account.get("/").get_data(as_text=True)
    token = opnieuw_token.split('name="csrf_token" value="', 1)[1].split('"', 1)[0]
    opnieuw = zonder_account.post(
        "/instellen",
        data={
            "csrf_token": token,
            "code": code,
            "wachtwoord": "ander-wachtwoord",
            "nogmaals": "ander-wachtwoord",
        },
        follow_redirects=False,
    )
    assert opnieuw.status_code == 302
    assert "/inloggen" in opnieuw.headers["Location"]
    conn = overzicht.verbind()
    assert overzicht.check_password_hash(
        conn.execute("SELECT wachtwoord FROM account WHERE id=1").fetchone()[0],
        "lang-wachtwoord",
    )
    conn.close()


def test_nieuwe_start_draait_de_instelcode(zonder_account):
    eerste = overzicht.zorg_setup_code()
    tweede = overzicht.zorg_setup_code()
    assert eerste != tweede
    antwoord = zonder_account.post(
        "/instellen",
        data={
            "csrf_token": "test-token",
            "code": eerste,
            "wachtwoord": "lang-wachtwoord",
            "nogmaals": "lang-wachtwoord",
        },
        follow_redirects=True,
    )
    assert not overzicht.heeft_account()
    assert "klopt niet" in antwoord.get_data(as_text=True)


def test_te_kort_wachtwoord_bij_instellen_blijft_zonder_account(zonder_account):
    code = overzicht.zorg_setup_code()
    zonder_account.post(
        "/instellen",
        data={"csrf_token": "test-token", "code": code, "wachtwoord": "kort", "nogmaals": "kort"},
        follow_redirects=True,
    )
    assert not overzicht.heeft_account()
    assert pathlib.Path(overzicht.SETUP_PATH).exists()


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


def test_oude_koek_faalt_na_uitloggen(uitgelogde_client, app):
    uitgelogde_client.post(
        "/inloggen",
        data={"csrf_token": "test-token", "wachtwoord": TEST_WACHTWOORD, "onthoud": "ja"},
        follow_redirects=True,
    )
    oud = _koek(uitgelogde_client)
    tekst = uitgelogde_client.get("/").get_data(as_text=True)
    token = tekst.split('name="csrf_token" value="', 1)[1].split('"', 1)[0]
    uitgelogde_client.post("/uitloggen", data={"csrf_token": token})
    antwoord = _andere_client(app, oud).get("/")
    assert antwoord.status_code == 302
    assert "/inloggen" in antwoord.headers["Location"]


def test_fout_wachtwoord(uitgelogde_client):
    antwoord = uitgelogde_client.post(
        "/inloggen",
        data={"csrf_token": "test-token", "wachtwoord": "fout"},
        follow_redirects=True,
    )
    assert "klopt niet" in antwoord.get_data(as_text=True)


def test_vijf_fouten_zetten_een_pauze(uitgelogde_client, monkeypatch):
    vast = overzicht.nu()
    monkeypatch.setattr(overzicht, "nu", lambda: vast)
    for _ in range(5):
        uitgelogde_client.post("/inloggen", data={"csrf_token": "test-token", "wachtwoord": "fout"})
    assert overzicht.POGINGEN_ACCOUNT[0] == 3
    pagina = uitgelogde_client.get("/inloggen").get_data(as_text=True)
    assert "Wacht" in pagina
    assert "seconden" in pagina
    assert "minuten" not in pagina


def test_pauze_is_exponentieel_en_begrensd():
    moment = overzicht.nu()
    assert overzicht.pauze_seconden(2, moment, 60) == 0
    assert overzicht.pauze_seconden(3, moment, 60) == 1
    assert overzicht.pauze_seconden(4, moment, 60) == 2
    assert overzicht.pauze_seconden(6, moment, 8) == 8
    assert overzicht.pauze_seconden(12, moment, 60) == 60
    assert overzicht.pauze_seconden(12, moment, 8) == 8


def test_pauze_per_ip_en_kort_voor_het_account(app):
    moment = overzicht.nu()
    overzicht.POGINGEN_IP["203.0.113.9"] = (12, moment)
    overzicht.POGINGEN_ACCOUNT = (0, None)
    with app.test_request_context(environ_overrides={"REMOTE_ADDR": "203.0.113.9"}):
        assert overzicht.wachttijd_over() == 60
    with app.test_request_context(environ_overrides={"REMOTE_ADDR": "198.51.100.4"}):
        assert overzicht.wachttijd_over() == 0
    overzicht.POGINGEN_ACCOUNT = (12, moment)
    with app.test_request_context(environ_overrides={"REMOTE_ADDR": "198.51.100.4"}):
        assert overzicht.wachttijd_over() == 8


def test_post_zonder_csrf_wordt_geweigerd(client):
    antwoord = client.post("/lasten/nieuw", data={"naam": "Huur"})
    assert antwoord.status_code == 400


def test_wachtwoord_wijzigen_ongeldig_oude_koek(client, post, app):
    client.get("/")
    oud = client.get_cookie("session").value
    antwoord = post(
        "/wachtwoord",
        data={"huidig": TEST_WACHTWOORD, "nieuw": "ander-wachtwoord", "nogmaals": "ander-wachtwoord"},
        follow_redirects=True,
    )
    assert "gewijzigd" in antwoord.get_data(as_text=True)
    assert client.get("/").status_code == 200
    antwoord = _andere_client(app, oud).get("/")
    assert antwoord.status_code == 302
    assert "/inloggen" in antwoord.headers["Location"]


def test_leeg_optieveld_wist_het_wachtwoord_niet(app):
    pathlib.Path(overzicht.OPTIONS_PATH).write_text(json.dumps({"wachtwoord": ""}), encoding="utf-8")
    overzicht.synchroniseer_wachtwoord()
    conn = overzicht.verbind()
    assert conn.execute("SELECT wachtwoord FROM account WHERE id=1").fetchone()[0] == TEST_HASH
    conn.close()


def test_zelfde_addonwachtwoord_houdt_de_sessie(client):
    pathlib.Path(overzicht.OPTIONS_PATH).write_text(
        json.dumps({"wachtwoord": TEST_WACHTWOORD}), encoding="utf-8"
    )
    overzicht.synchroniseer_wachtwoord()
    assert client.get("/").status_code == 200


def test_opties_wachtwoord_wint_en_ongeldig_oude_koek(client, app, uitgelogde_client):
    client.get("/")
    oud = client.get_cookie("session").value
    pathlib.Path(overzicht.OPTIONS_PATH).write_text(
        json.dumps({"wachtwoord": "addon-wachtwoord"}), encoding="utf-8"
    )
    overzicht.synchroniseer_wachtwoord()
    antwoord = _andere_client(app, oud).get("/")
    assert antwoord.status_code == 302
    assert "/inloggen" in antwoord.headers["Location"]
    antwoord = uitgelogde_client.post(
        "/inloggen",
        data={"csrf_token": "test-token", "wachtwoord": "addon-wachtwoord"},
        follow_redirects=True,
    )
    tekst = antwoord.get_data(as_text=True)
    assert "Dashboard" in tekst
    token = tekst.split('name="csrf_token" value="', 1)[1].split('"', 1)[0]
    antwoord = uitgelogde_client.post(
        "/wachtwoord",
        data={
            "csrf_token": token,
            "huidig": "addon-wachtwoord",
            "nieuw": "weer-een-ander",
            "nogmaals": "weer-een-ander",
        },
        follow_redirects=True,
    )
    assert "add-on" in antwoord.get_data(as_text=True)


def test_open_redirect_wordt_niet_gevolgd(uitgelogde_client):
    antwoord = uitgelogde_client.post(
        "/inloggen",
        data={"csrf_token": "test-token", "wachtwoord": TEST_WACHTWOORD, "verder": "https://example.test"},
        follow_redirects=False,
    )
    assert antwoord.headers["Location"].endswith("/")


def test_secure_en_hsts_alleen_bij_https(uitgelogde_client, app):
    antwoord = uitgelogde_client.post(
        "/inloggen",
        data={"csrf_token": "test-token", "wachtwoord": TEST_WACHTWOORD},
        follow_redirects=False,
    )
    assert "Secure" not in antwoord.headers.get("Set-Cookie", "")
    assert "Strict-Transport-Security" not in uitgelogde_client.get("/inloggen").headers
    overzicht.HTTPS_ACTIEF = True
    app.config["SESSION_COOKIE_SECURE"] = True
    try:
        with app.test_client() as browser:
            with browser.session_transaction() as sessie:
                sessie["csrf_token"] = "test-token"
            antwoord = browser.post(
                "/inloggen",
                data={"csrf_token": "test-token", "wachtwoord": TEST_WACHTWOORD},
                follow_redirects=False,
            )
            assert "Secure" in antwoord.headers.get("Set-Cookie", "")
            assert antwoord.headers["Strict-Transport-Security"] == "max-age=31536000"
    finally:
        overzicht.HTTPS_ACTIEF = False
        app.config["SESSION_COOKIE_SECURE"] = False


def test_ssl_zonder_certificaat_faalt(app):
    pathlib.Path(overzicht.OPTIONS_PATH).write_text(json.dumps({"ssl": True}), encoding="utf-8")
    assert overzicht.ssl_gevraagd() is True
    assert overzicht.maak_ssl_context() is None
    pathlib.Path(overzicht.OPTIONS_PATH).write_text(json.dumps({"ssl": False}), encoding="utf-8")
    assert overzicht.ssl_gevraagd() is False
