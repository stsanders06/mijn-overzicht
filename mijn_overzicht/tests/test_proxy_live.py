"""Echte waitress, niet de Flask-testclient. Die ziet X-Forwarded-For nooit."""
import socket
import threading
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


def _koek(kop, vorige=""):
    koek = vorige
    for regel in kop.split("\r\n"):
        if regel.lower().startswith("set-cookie:"):
            deel = regel.split(":", 1)[1].strip().split(";", 1)[0]
            if deel.startswith("session="):
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


def _login(poort, xff, wachtwoord, koek=""):
    _status, kop, body = _verzoek(poort, "GET", "/inloggen", koek=koek, xff=xff)
    koek = _koek(kop, koek)
    token = body.decode("utf-8", "replace").split('name="csrf_token" value="', 1)[1].split('"', 1)[0]
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
