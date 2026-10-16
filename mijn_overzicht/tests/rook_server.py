"""Rooktest tegen een draaiende add-on.

Gebruik: python3 rook_server.py http://127.0.0.1:8320
Bij https komen daar een luie verbinding, een verknipt POST en een upload van 3 MB bij.
"""
import http.cookiejar
import os
import socket
import ssl
import sys
import threading
import time
import urllib.error
import urllib.parse
import urllib.request


WACHTWOORD = os.environ.get("ROOK_WACHTWOORD", "rooktest-wachtwoord")


def afbreken(tekst):
    print(tekst, file=sys.stderr)
    sys.exit(1)


def opener_voor(basis):
    context = ssl._create_unverified_context()
    jar = http.cookiejar.CookieJar()
    return urllib.request.build_opener(
        urllib.request.HTTPSHandler(context=context),
        urllib.request.HTTPCookieProcessor(jar),
    )


def haal(opener, url, data=None, timeout=10, headers=None):
    verzoek = urllib.request.Request(url, data=data, headers=headers or {}, method="POST" if data else "GET")
    try:
        with opener.open(verzoek, timeout=timeout) as antwoord:
            return antwoord.status, antwoord.read(), antwoord.geturl()
    except urllib.error.HTTPError as fout:
        return fout.code, fout.read(), url


def csrf_uit(html):
    tekst = html.decode("utf-8", "replace")
    marker = 'name="csrf_token" value="'
    if marker not in tekst:
        afbreken("Geen csrf-token op de pagina")
    return tekst.split(marker, 1)[1].split('"', 1)[0]


def login_en_post(opener, basis):
    status, html, _ = haal(opener, basis + "/inloggen")
    if status != 200 or b"Inloggen" not in html:
        afbreken(f"Loginpagina gaf {status}")
    token = csrf_uit(html)
    status, html, url = haal(
        opener,
        basis + "/inloggen",
        urllib.parse.urlencode({"csrf_token": token, "wachtwoord": WACHTWOORD}).encode(),
    )
    if status != 200 or b"Dashboard" not in html:
        afbreken(f"Inloggen mislukte ({status}, {url})")
    status, html, _ = haal(opener, basis + "/lasten/nieuw")
    token = csrf_uit(html)
    status, html, url = haal(
        opener,
        basis + "/lasten/nieuw",
        urllib.parse.urlencode({
            "csrf_token": token,
            "naam": "Rooktest",
            "categorie": "Overig",
            "bedrag": "1",
            "frequentie": "maand",
        }).encode(),
    )
    if b"Rooktest" not in html:
        afbreken(f"POST van een vaste last kwam niet aan ({status}, {url})")
    print("Login en POST gelukt")


def gelijktijdig_tijdens_luie_socket(basis):
    host, poort = adres_van(basis)
    lui = socket.create_connection((host, poort), timeout=5)
    lui.settimeout(30)
    fouten = []

    def een():
        eigen = opener_voor(basis)
        try:
            status, html, _ = haal(eigen, basis + "/inloggen", timeout=3)
            if status != 200 or b"Inloggen" not in html:
                fouten.append(f"status {status}")
        except Exception as exc:  # noqa: BLE001 - de rooktest moet elke fout zien
            fouten.append(repr(exc))

    draden = [threading.Thread(target=een) for _ in range(4)]
    for draad in draden:
        draad.start()
    for draad in draden:
        draad.join(timeout=5)
    lui.close()
    if fouten or any(draad.is_alive() for draad in draden):
        afbreken(f"Luie verbinding blokkeert andere bezoekers: {fouten}")
    print("Luie verbinding blokkeert anderen niet")


def adres_van(basis):
    stuk = urllib.parse.urlsplit(basis)
    return stuk.hostname, stuk.port or (443 if stuk.scheme == "https" else 80)


def verknipt_post(basis):
    host, poort = adres_van(basis)
    eigen = opener_voor(basis)
    _, html, _ = haal(eigen, basis + "/inloggen")
    token = csrf_uit(html)
    koek = ""
    for cookie in eigen.handlers:
        jar = getattr(cookie, "cookiejar", None)
        if jar is None:
            continue
        for stuk in jar:
            if stuk.name == "session":
                koek = f"session={stuk.value}"
    lichaam = urllib.parse.urlencode({
        "csrf_token": token,
        "wachtwoord": "fout",
        "extra": "x" * 3000,
    }).encode()
    hoofd = (
        f"POST /inloggen HTTP/1.1\r\nHost: {host}\r\n"
        f"Content-Type: application/x-www-form-urlencoded\r\n"
        f"Content-Length: {len(lichaam)}\r\n"
        f"Cookie: {koek}\r\nConnection: close\r\n\r\n"
    ).encode() + lichaam
    rauw = socket.create_connection((host, poort), timeout=10)
    rauw.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
    context = ssl._create_unverified_context()
    tls = context.wrap_socket(rauw, server_hostname=host)
    try:
        for index in range(0, len(hoofd), 16):
            tls.send(hoofd[index:index + 16])
            time.sleep(0.001)
        data = b""
        while True:
            stuk = tls.recv(8192)
            if not stuk:
                break
            data += stuk
    finally:
        tls.close()
    statusregel = data.split(b"\r\n", 1)[0]
    if not statusregel.startswith(b"HTTP/1.1 ") or statusregel.endswith(b" 500"):
        afbreken(f"Verknipt POST mislukte: {statusregel!r}")
    print(f"Verknipt POST gelukt ({statusregel.decode()})")


def upload_drie_mb(opener, basis):
    _, html, _ = haal(opener, basis + "/documenten/nieuw")
    token = csrf_uit(html)
    pdf = b"%PDF-1.4\n" + (b"0" * (3 * 1024 * 1024)) + b"\n%%EOF"
    grens = "----rookgrens"
    delen = []
    for naam, waarde in (("csrf_token", token), ("titel", "Rookdocument")):
        delen.append(
            f"--{grens}\r\nContent-Disposition: form-data; name=\"{naam}\"\r\n\r\n{waarde}\r\n".encode()
        )
    delen.append(
        f"--{grens}\r\nContent-Disposition: form-data; name=\"bestanden\"; filename=\"rook.pdf\"\r\n"
        f"Content-Type: application/pdf\r\n\r\n".encode() + pdf + b"\r\n"
    )
    delen.append(f"--{grens}--\r\n".encode())
    lichaam = b"".join(delen)
    status, html, url = haal(
        opener,
        basis + "/documenten/nieuw",
        lichaam,
        timeout=30,
        headers={"Content-Type": f"multipart/form-data; boundary={grens}"},
    )
    tekst = html.decode("utf-8", "replace")
    if "Rookdocument" not in tekst or "Niet toegevoegd" in tekst:
        afbreken(f"Upload van 3 MB mislukte ({status}, {url})")
    print("Upload van 3 MB gelukt")


def main():
    if len(sys.argv) != 2:
        afbreken("Gebruik: rook_server.py <basis-url>")
    basis = sys.argv[1].rstrip("/")
    opener = opener_voor(basis)
    login_en_post(opener, basis)
    if basis.startswith("https://"):
        gelijktijdig_tijdens_luie_socket(basis)
        verknipt_post(basis)
        upload_drie_mb(opener, basis)


if __name__ == "__main__":
    main()
