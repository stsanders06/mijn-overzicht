"""Echte waitress, niet de Flask-testclient. Die ziet X-Forwarded-For nooit."""
import socket
import threading
import time
import urllib.parse

from waitress import create_server

import main as overzicht
from conftest import TEST_WACHTWOORD


def _lichaam(kop, rest):
    if "transfer-encoding: chunked" not in kop.lower():
        return rest
    uit = b""
    while rest:
        regel, _, rest = rest.partition(b"\r\n")
        if not regel:
            break
        grootte = int(regel.split(b";", 1)[0], 16)
        if grootte == 0:
            break
        uit += rest[:grootte]
        rest = rest[grootte + 2 :]
    return uit


SESSIE_KOEK = "mijn_overzicht_session"


def _koek(kop, vorige=""):
    koek = vorige
    voorvoegsel = SESSIE_KOEK + "="
    for regel in kop.split("\r\n"):
        if regel.lower().startswith("set-cookie:"):
            deel = regel.split(":", 1)[1].strip().split(";", 1)[0]
            if deel.startswith(voorvoegsel):
                koek = deel
    return koek


def _verzoek(poort, methode, pad, lichaam=b"", koek="", xff=""):
    regels = [f"{methode} {pad} HTTP/1.1", "Host: 127.0.0.1"]
    if koek:
        regels.append(f"Cookie: {koek}")
    if xff:
        regels.append(f"X-Forwarded-For: {xff}")
    if lichaam:
        regels.append("Content-Type: application/x-www-form-urlencoded")
        regels.append(f"Content-Length: {len(lichaam)}")
    regels.append("Connection: close")
    bericht = ("\r\n".join(regels) + "\r\n\r\n").encode() + lichaam
    with socket.create_connection(("127.0.0.1", poort), timeout=5) as sock:
        sock.sendall(bericht)
        stukken = []
        while True:
            brok = sock.recv(65536)
            if not brok:
                break
            stukken.append(brok)
    ruw = b"".join(stukken)
    kop, _, rest = ruw.partition(b"\r\n\r\n")
    tekst = kop.decode("iso-8859-1", "replace")
    status = int(tekst.split("\r\n", 1)[0].split()[1])
    return status, tekst, _lichaam(tekst, rest)


def _token(body):
    return body.decode("utf-8", "replace").split('name="csrf_token" value="', 1)[1].split('"', 1)[0]


def _post_inlog(poort, xff, wachtwoord, koek, token):
    lichaam = urllib.parse.urlencode({"csrf_token": token, "wachtwoord": wachtwoord}).encode()
    return _verzoek(poort, "POST", "/inloggen", lichaam, koek, xff)


def _login(poort, xff, wachtwoord, koek=""):
    _status, kop, body = _verzoek(poort, "GET", "/inloggen", koek=koek, xff=xff)
    koek = _koek(kop, koek)
    token = _token(body)
    lichaam = urllib.parse.urlencode({"csrf_token": token, "wachtwoord": wachtwoord}).encode()
    status, kop, body = _verzoek(poort, "POST", "/inloggen", lichaam, koek, xff)
    return status, kop, body, _koek(kop, koek)


def _locatie(kop):
    for regel in kop.split("\r\n"):
        if regel.lower().startswith("location:"):
            return regel.split(":", 1)[1].strip()
    return ""


def _server(app, **extra):
    server = create_server(app, host="127.0.0.1", port=0, **extra)
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    return server, thread


def _stop(server, thread):
    server.close()
    thread.join(timeout=3)


def test_flood_houdt_een_juist_wachtwoord_snel(app, monkeypatch):
    """Vijftig adressen vullen het venster. Een vers adres blijft onder 1,5 s, en GET / ook."""
    vast = overzicht.nu()
    monkeypatch.setattr(overzicht, "nu", lambda: vast)
    overzicht.HTTPS_ACTIEF = True
    overzicht.app.config["SESSION_COOKIE_SECURE"] = True
    aantal = 50
    # Al gefaald, maar nog niet in de eigen pauze. Het venster zit vol, dus hun
    # extra foute pogingen mogen geen hash meer doen zodra het herkansingsslot bezet is.
    overzicht.MISLUKKINGEN.extend([vast] * overzicht.VENSTER_MAX)
    for n in range(1, aantal + 1):
        overzicht.POGINGEN_IP[f"203.0.113.{n}"] = (1, vast)
    server, thread = _server(app, **overzicht.WAITRESS_HTTPS)
    stop = threading.Event()
    aanvallers = []
    try:
        poort = server.effective_port

        def aanvaller(n):
            ip = f"203.0.113.{n}"
            try:
                _status, kop, body = _verzoek(poort, "GET", "/inloggen", xff=ip)
            except OSError:
                return
            koek = _koek(kop)
            try:
                token = _token(body)
            except IndexError:
                return
            while not stop.is_set():
                try:
                    _post_inlog(poort, ip, "fout", koek, token)
                except OSError:
                    if stop.is_set():
                        return

        aanvallers = [
            threading.Thread(target=aanvaller, args=(n,), name=f"aanval-{n}", daemon=True)
            for n in range(1, aantal + 1)
        ]
        for draad in aanvallers:
            draad.start()
        time.sleep(0.3)
        t_get = time.perf_counter()
        status, _kop, _body = _verzoek(poort, "GET", "/", xff="198.51.100.250")
        duur_get = time.perf_counter() - t_get
        assert status in {200, 302}
        assert duur_get < 1.0, duur_get
        tijden = []
        for n in range(20):
            begin = time.perf_counter()
            status, kop, _body, _sessie = _login(poort, "198.51.100.77", TEST_WACHTWOORD)
            duur = time.perf_counter() - begin
            tijden.append(duur)
            assert status == 302, (n, status, duur)
            assert urllib.parse.urlsplit(_locatie(kop)).path == "/", (n, _locatie(kop))
            assert duur < 1.5, (n, duur)
        t_get = time.perf_counter()
        status, _kop, _body = _verzoek(poort, "GET", "/", xff="198.51.100.251")
        duur_na = time.perf_counter() - t_get
        assert status in {200, 302}
        assert duur_na < 1.0, duur_na
        geordend = sorted(tijden)
        print(
            f"flood 20/20 max={geordend[-1]:.3f}s median={geordend[len(geordend)//2]:.3f}s "
            f"get={duur_get:.3f}s get_na={duur_na:.3f}s"
        )
    finally:
        stop.set()
        for draad in aanvallers:
            draad.join(timeout=2)
        _stop(server, thread)
        overzicht.POGINGEN_IP.clear()
        overzicht.MISLUKKINGEN.clear()
        overzicht.HTTPS_ACTIEF = False
        overzicht.app.config["SESSION_COOKIE_SECURE"] = False


def test_waitress_telt_xff_alleen_met_de_ssl_config(app, monkeypatch):
    vast = overzicht.nu()
    monkeypatch.setattr(overzicht, "nu", lambda: vast)
    overzicht.HTTPS_ACTIEF = True
    overzicht.app.config["SESSION_COOKIE_SECURE"] = True
    server, thread = _server(app, **overzicht.WAITRESS_HTTPS)
    try:
        assert server.adj.trusted_proxy == "127.0.0.1"
        assert server.adj.trusted_proxy_headers == {"x-forwarded-for"}
        poort = server.effective_port
        koek = ""
        for _ in range(4):
            _status, _kop, _body, koek = _login(poort, "203.0.113.8", "fout", koek)
        assert overzicht.POGINGEN_IP["203.0.113.8"][0] == 3
        assert "127.0.0.1" not in overzicht.POGINGEN_IP
        _status, kop, body = _verzoek(poort, "GET", "/inloggen", koek=koek, xff="203.0.113.8")
        assert b"Te veel pogingen" in body
        status, kop, _body, _koek = _login(poort, "198.51.100.8", TEST_WACHTWOORD)
        assert status == 302
        assert urllib.parse.urlsplit(_locatie(kop)).path == "/"
    finally:
        _stop(server, thread)
        overzicht.POGINGEN_IP.clear()
        overzicht.MISLUKKINGEN.clear()

    kaal, draad = _server(app, threads=4, url_scheme="https", clear_untrusted_proxy_headers=True)
    try:
        assert kaal.adj.trusted_proxy is None
        poort = kaal.effective_port
        _login(poort, "203.0.113.8", "fout")
        _login(poort, "198.51.100.8", "fout")
        assert overzicht.POGINGEN_IP["127.0.0.1"][0] == 2
        assert "203.0.113.8" not in overzicht.POGINGEN_IP
        assert "198.51.100.8" not in overzicht.POGINGEN_IP
    finally:
        _stop(kaal, draad)
        overzicht.HTTPS_ACTIEF = False
        overzicht.app.config["SESSION_COOKIE_SECURE"] = False
