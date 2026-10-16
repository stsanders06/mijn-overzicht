"""Inlog, eerste keer, CSRF, sessies en het wachtwoord uit de add-on."""
import json
import logging
import os
import pathlib
import signal
import subprocess
import sys
import threading
import time

import pytest

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


def test_leeg_wachtwoord_is_nederlands(uitgelogde_client):
    pagina = uitgelogde_client.get("/inloggen").get_data(as_text=True)
    assert "novalidate" in pagina
    antwoord = uitgelogde_client.post(
        "/inloggen",
        data={"csrf_token": "test-token", "wachtwoord": ""},
        follow_redirects=True,
    )
    tekst = antwoord.get_data(as_text=True)
    assert "Vul je wachtwoord in." in tekst
    assert "Fill out this field" not in tekst


def test_leeg_formulier_geeft_nederlandse_fout(client):
    pagina = client.get("/lasten/nieuw").get_data(as_text=True)
    assert 'novalidate' in pagina
    opening = pagina.split('id="afschrijfdag-veld"', 1)[1].split(">", 1)[0]
    assert "hidden" not in opening
    opening = pagina.split('id="referentie-veld"', 1)[1].split(">", 1)[0]
    assert "hidden" not in opening
    antwoord = client.post(
        "/lasten/nieuw",
        data={"csrf_token": "test-token", "naam": "", "categorie": "Wonen", "frequentie": "maand"},
    )
    assert antwoord.status_code == 400
    tekst = antwoord.get_data(as_text=True)
    assert "Vul een naam in." in tekst
    assert "Fill out this field" not in tekst


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
    assert overzicht.globale_aantal() == 3
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


def test_pauze_per_ip_blokkeert_geen_juist_wachtwoord(app):
    moment = overzicht.nu()
    overzicht.POGINGEN_IP["203.0.113.9"] = (12, moment)
    with app.test_request_context(environ_overrides={"REMOTE_ADDR": "203.0.113.9"}):
        assert overzicht.wachttijd_over() == 60
        assert overzicht.ip_wachttijd() == 60
    with app.test_request_context(environ_overrides={"REMOTE_ADDR": "198.51.100.4"}):
        assert overzicht.wachttijd_over() == 0
    overzicht.MISLUKKINGEN.extend([moment] * overzicht.VENSTER_MAX)
    assert overzicht.globale_aantal() >= overzicht.VENSTER_MAX
    with app.test_request_context(environ_overrides={"REMOTE_ADDR": "198.51.100.4"}):
        assert overzicht.wachttijd_over() == 0


def _inlog_vanaf(app, ip, wachtwoord):
    with app.test_client() as browser:
        with browser.session_transaction() as sessie:
            sessie["csrf_token"] = "test-token"
        return browser.post(
            "/inloggen",
            data={"csrf_token": "test-token", "wachtwoord": wachtwoord},
            environ_base={"REMOTE_ADDR": ip},
            follow_redirects=False,
        )


def test_juist_wachtwoord_lukt_vanaf_draaiende_adressen(app, monkeypatch):
    vast = overzicht.nu()
    monkeypatch.setattr(overzicht, "nu", lambda: vast)
    for _ in range(3):
        antwoord = _inlog_vanaf(app, "203.0.113.77", "fout")
        assert "/inloggen" in antwoord.headers["Location"]
    geblokkeerd = _inlog_vanaf(app, "203.0.113.77", TEST_WACHTWOORD)
    assert "/inloggen" in geblokkeerd.headers["Location"]
    for n in range(12):
        antwoord = _inlog_vanaf(app, f"203.0.113.{n + 1}", "fout")
        assert "/inloggen" in antwoord.headers["Location"]
    gelukt = 0
    for n in range(20):
        antwoord = _inlog_vanaf(app, f"198.51.100.{n + 1}", TEST_WACHTWOORD)
        if antwoord.headers["Location"].endswith("/"):
            gelukt += 1
    assert gelukt == 20


def test_pogingen_per_ip_blijven_begrensd(app):
    moment = overzicht.nu()
    overzicht.POGINGEN_IP.clear()
    for n in range(overzicht.POGINGEN_IP_MAX + 40):
        overzicht.POGINGEN_IP[f"198.51.{n // 250}.{n % 250}"] = (1, moment)
    with app.test_request_context(environ_overrides={"REMOTE_ADDR": "203.0.113.50"}):
        overzicht.noteer_mislukking()
    assert len(overzicht.POGINGEN_IP) <= overzicht.POGINGEN_IP_MAX
    assert "203.0.113.50" in overzicht.POGINGEN_IP


def test_vergrendeld_adres_blijft_staan(app):
    moment = overzicht.nu()
    overzicht.POGINGEN_IP.clear()
    overzicht.POGINGEN_IP["203.0.113.9"] = (12, moment)
    for n in range(overzicht.POGINGEN_IP_MAX + 10):
        overzicht.POGINGEN_IP[f"198.51.{n // 250}.{n % 250}"] = (1, moment)
    with app.test_request_context(environ_overrides={"REMOTE_ADDR": "203.0.113.50"}):
        overzicht.noteer_mislukking()
    assert overzicht.POGINGEN_IP["203.0.113.9"] == (12, moment)
    assert "203.0.113.50" in overzicht.POGINGEN_IP
    assert len(overzicht.POGINGEN_IP) <= overzicht.POGINGEN_IP_MAX


def test_vol_venster_wacht_niet_en_juist_wachtwoord_lukt(app, monkeypatch):
    vast = overzicht.nu()
    monkeypatch.setattr(overzicht, "nu", lambda: vast)
    for n in range(overzicht.VENSTER_MAX):
        antwoord = _inlog_vanaf(app, f"203.0.113.{n + 1}", "fout")
        assert antwoord.status_code == 302
        assert "/inloggen" in antwoord.headers["Location"]
    assert overzicht.globale_aantal() >= overzicht.VENSTER_MAX
    assert overzicht.app.config["TEST_SLAAP"] == []
    # Dit adres faalde al. Het herkansingsslot is bezet: meteen 429, geen hash-wachtrij.
    assert overzicht._herkansing.acquire(blocking=False)
    try:
        vol = _inlog_vanaf(app, "203.0.113.1", "fout")
        assert vol.status_code == 429
        assert "later" in vol.get_data(as_text=True).lower()
        assert overzicht.POGINGEN_IP["203.0.113.1"][0] == 1
        gelukt = _inlog_vanaf(app, "198.51.100.20", TEST_WACHTWOORD)
        assert gelukt.status_code == 302
        assert gelukt.headers["Location"].endswith("/")
    finally:
        overzicht._herkansing.release()
    assert overzicht.app.config["TEST_SLAAP"] == []


def test_instelcode_staat_altijd_op_stdout(zonder_account, capsys):
    code = overzicht.zorg_setup_code()
    assert code in capsys.readouterr().out


def test_inlog_legt_lege_hash_na_back_up_uit(uitgelogde_client):
    conn = overzicht.verbind()
    conn.execute("UPDATE account SET wachtwoord='' WHERE id=1")
    conn.commit()
    conn.close()
    tekst = uitgelogde_client.get("/inloggen").get_data(as_text=True)
    assert "back-up" in tekst
    assert "add-on" in tekst
    antwoord = uitgelogde_client.post(
        "/inloggen",
        data={"csrf_token": "test-token", "wachtwoord": TEST_WACHTWOORD},
        follow_redirects=True,
    )
    assert "Dashboard" not in antwoord.get_data(as_text=True)


def test_elke_foute_poging_telt_ook_bij_draaiende_adressen(app, monkeypatch):
    vast = overzicht.nu()
    monkeypatch.setattr(overzicht, "nu", lambda: vast)
    adressen = [f"203.0.113.{n}" for n in range(1, 13)]
    for _ in range(8):
        for ip in adressen:
            antwoord = _inlog_vanaf(app, ip, "fout")
            assert "/inloggen" in antwoord.headers["Location"]
    for ip in adressen:
        assert overzicht.POGINGEN_IP[ip][0] == 3
    assert overzicht.globale_aantal() == len(adressen) * 3
    goed = _inlog_vanaf(app, "198.51.100.77", TEST_WACHTWOORD)
    assert goed.headers["Location"].endswith("/")


def _inlog_via_proxy(app, ip, wachtwoord, peer="127.0.0.1"):
    with app.test_client() as browser:
        with browser.session_transaction() as sessie:
            sessie["csrf_token"] = "test-token"
        return browser.post(
            "/inloggen",
            data={"csrf_token": "test-token", "wachtwoord": wachtwoord},
            environ_base={"REMOTE_ADDR": peer},
            headers={"X-Forwarded-For": ip},
            follow_redirects=False,
        )


def test_http_negeert_x_forwarded_for(app):
    overzicht.HTTPS_ACTIEF = False
    antwoord = _inlog_via_proxy(app, "198.51.100.9", "fout", peer="203.0.113.10")
    assert "/inloggen" in antwoord.headers["Location"]
    assert overzicht.POGINGEN_IP["203.0.113.10"][0] == 1
    assert "198.51.100.9" not in overzicht.POGINGEN_IP


def test_de_app_leest_x_forwarded_for_niet_zelf(app, monkeypatch):
    """Waitress zet het adres. De app heeft geen ProxyFix meer."""
    vast = overzicht.nu()
    monkeypatch.setattr(overzicht, "nu", lambda: vast)
    overzicht.HTTPS_ACTIEF = True
    try:
        antwoord = _inlog_via_proxy(app, "203.0.113.8", "fout")
        assert "/inloggen" in antwoord.headers["Location"]
        assert overzicht.POGINGEN_IP["127.0.0.1"][0] == 1
        assert "203.0.113.8" not in overzicht.POGINGEN_IP
        genegeerd = _inlog_via_proxy(app, "198.51.100.9", "fout", peer="203.0.113.40")
        assert "/inloggen" in genegeerd.headers["Location"]
        assert overzicht.POGINGEN_IP["203.0.113.40"][0] == 1
        assert "198.51.100.9" not in overzicht.POGINGEN_IP
    finally:
        overzicht.HTTPS_ACTIEF = False


def test_nginx_config_overschrijft_het_adres_en_geeft_413(app):
    tekst = overzicht.bouw_nginx_config(8320, 18080, "/tmp/cert.pem", "/tmp/key.pem", "/tmp/nginx.pid", "/tmp/nginx")
    assert "proxy_set_header X-Forwarded-For $remote_addr;" in tekst
    assert "error_log stderr warn;" in tekst
    assert "proxy_add_x_forwarded_for" not in tekst
    assert "server_tokens off;" in tekst
    assert "error_page 413 @te_groot;" in tekst
    assert "X-Frame-Options" in tekst
    assert "Content-Security-Policy" in tekst
    assert overzicht.nginx_werkmap() != overzicht.DATA_DIR
    assert not overzicht.nginx_werkmap().startswith(overzicht.DATA_DIR + os.sep)


def test_gestopte_nginx_stopt_de_addon():
    class Nep:
        def wait(self):
            return 9

    gestopt = []
    afsluiten = threading.Event()
    overzicht.bewaak_nginx(Nep(), afsluiten, os.path.join(overzicht.DATA_DIR, "ontbreekt.pid"), stop=gestopt.append)
    assert gestopt == [1]
    afsluiten.set()
    gestopt.clear()
    overzicht.bewaak_nginx(Nep(), afsluiten, os.path.join(overzicht.DATA_DIR, "ontbreekt.pid"), stop=gestopt.append)
    assert gestopt == []


def _proces_weg(pid):
    try:
        with open(f"/proc/{pid}/stat", encoding="utf-8") as bestand:
            staat = bestand.read().rsplit(")", 1)[-1].split()[0]
    except FileNotFoundError:
        return True
    return staat in {"Z", "X"}


def test_kind_sterft_als_python_wordt_gedood(tmp_path):
    helper = os.path.join(os.path.dirname(overzicht.__file__), "sterf_met_ouder.py")
    pidpad = tmp_path / "kind.pid"
    ouder = tmp_path / "ouder.py"
    ouder.write_text(
        "import os, signal, subprocess, sys, time\n"
        f"helper = {helper!r}\n"
        "proc = subprocess.Popen([sys.executable, helper, 'sleep', '30'], start_new_session=True)\n"
        f"open({str(pidpad)!r}, 'w').write(str(proc.pid))\n"
        "time.sleep(0.4)\n"
        "os.kill(os.getpid(), signal.SIGKILL)\n",
        encoding="utf-8",
    )
    subprocess.run([sys.executable, str(ouder)], timeout=5, check=False)
    kind = int(pidpad.read_text())
    deadline = time.time() + 3
    while time.time() < deadline and not _proces_weg(kind):
        time.sleep(0.05)
    weg = _proces_weg(kind)
    if not weg:
        os.kill(kind, signal.SIGKILL)
    assert weg


def test_stop_nginx_raakt_de_groep_ook_als_de_master_al_weg_is(monkeypatch):
    signalen = []
    monkeypatch.setattr(overzicht.os, "killpg", lambda pid, sig: signalen.append((pid, sig)))

    class Dood:
        pid = 4242

        def poll(self):
            return 0

    afsluiten = threading.Event()
    overzicht.stop_nginx(Dood(), afsluiten, os.path.join(overzicht.DATA_DIR, "ontbreekt.pid"))
    assert afsluiten.is_set()
    assert (4242, signal.SIGTERM) in signalen


def test_term_eindigt_met_code_0(caplog):
    netjes = threading.Event()
    with caplog.at_level(logging.INFO):
        with pytest.raises(SystemExit) as einde:
            overzicht.vraag_stop(netjes, signal.SIGTERM)
        assert einde.value.code == 0
        assert netjes.is_set()
        assert overzicht.afsluitcode(netjes) == 0
        assert overzicht.afsluitcode(threading.Event()) == 1
    assert "Stopverzoek" in caplog.text
    assert "De add-on is gestopt." in caplog.text
    assert "De webserver is gestopt" in caplog.text


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
            assert antwoord.headers["Strict-Transport-Security"] == "max-age=86400"
    finally:
        overzicht.HTTPS_ACTIEF = False
        app.config["SESSION_COOKIE_SECURE"] = False


def test_ssl_zonder_certificaat_faalt(app):
    pathlib.Path(overzicht.OPTIONS_PATH).write_text(json.dumps({"ssl": True}), encoding="utf-8")
    assert overzicht.ssl_gevraagd() is True
    assert overzicht.maak_ssl_context() is None
    pathlib.Path(overzicht.OPTIONS_PATH).write_text(json.dumps({"ssl": False}), encoding="utf-8")
    assert overzicht.ssl_gevraagd() is False
