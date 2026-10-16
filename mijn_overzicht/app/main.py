"""Mijn Overzicht: vaste lasten, verzekeringen, voertuigen en bezittingen.

De site draait als Home Assistant-add-on op een eigen poort, buiten de zijbalk
en buiten de inlog van Home Assistant. Daarom heeft ze een eigen account.
Gegevens staan in /data en blijven bij een update staan. Er worden geen
voorbeeldgegevens ingevuld.
"""
import atexit
import calendar
import hashlib
import io
import json
import logging
import os
import pwd
import re
import secrets
import signal
import socket
import sqlite3
import ssl
import subprocess
import sys
import tempfile
import threading
import time
import zipfile
from datetime import date, datetime, timedelta
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from urllib.parse import urlsplit
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from flask import Flask, Response, abort, flash, redirect, render_template, request, send_file, session, url_for
from jinja2 import StrictUndefined
from werkzeug.middleware.proxy_fix import ProxyFix
from werkzeug.security import check_password_hash, generate_password_hash

# Hoort gelijk te lopen met version in config.yaml. In Home Assistant wint het
# versienummer dat de Supervisor heeft geïnstalleerd; anders deze fallback.
VERSIE_FALLBACK = "0.1.2"
VERSIE = os.environ.get("ADDON_VERSION") or VERSIE_FALLBACK

DATA_DIR = os.environ.get("DATA_DIR", os.path.join(os.path.dirname(__file__), "data"))
DB_PATH = os.path.join(DATA_DIR, "overzicht.db")
BESTAND_DIR = os.path.join(DATA_DIR, "bestanden")
OPTIONS_PATH = os.path.join(DATA_DIR, "options.json")
SETUP_PATH = os.path.join(DATA_DIR, "setup_code")
SSL_DIR = os.environ.get("SSL_DIR", "/ssl")

os.makedirs(DATA_DIR, exist_ok=True)
os.makedirs(BESTAND_DIR, exist_ok=True)

# Wat er binnenkort op het dashboard komt, en hoe ver terug een verlopen datum
# nog genoemd wordt. Langer terug is meestal al afgehandeld.
BINNENKORT_DAGEN = 60
VERLOPEN_DAGEN = 365

WACHTWOORD_MINIMUM = 8
# Vertraging begint pas na een paar mislukte pogingen en loopt exponentieel op.
# Per adres blokkeert die pauze ook een juist wachtwoord, en elke foute poging
# telt mee, ook tijdens de accountpauze. Een juist wachtwoord vanaf een adres
# dat zelf niet in de pauze zit, werkt meteen.
PAUZE_NA_POGINGEN = 3
IP_PLAFOND = 60
ACCOUNT_PLAFOND = 8
POGINGEN_IP_MAX = 256
# Een dag. Langer vastzetten op http-naar-https is lastig terug te draaien.
HSTS_SECONDEN = 86400
# Waitress blijft http, alleen op localhost. Nginx doet de TLS op de echte poort.
INTERN_POORT = 18080
SESSIE_DAGEN = 30
MAX_BESTAND = 12 * 1024 * 1024
MAX_VERZOEK = 32 * 1024 * 1024

MAANDEN = ["jan", "feb", "mrt", "apr", "mei", "jun", "jul", "aug", "sep", "okt", "nov", "dec"]
MAAL_PER_JAAR = {"maand": 12, "kwartaal": 4, "jaar": 1}
FREQUENTIE_PER = {"maand": "per maand", "kwartaal": "per kwartaal", "jaar": "per jaar"}

LAST_CATEGORIEEN = [
    "Wonen", "Energie", "Water", "Telecom", "Verzekering", "Vervoer",
    "Abonnement", "Gemeente", "Overig",
]
FREQUENTIES = [("maand", "Per maand"), ("kwartaal", "Per kwartaal"), ("jaar", "Per jaar")]
VERZEKERING_SOORTEN = [
    ("zorg", "Zorg"), ("auto", "Auto"), ("motor", "Motor"), ("reis", "Reis"),
    ("inboedel", "Inboedel"), ("opstal", "Opstal"), ("aansprakelijkheid", "Aansprakelijkheid"),
    ("rechtsbijstand", "Rechtsbijstand"), ("overig", "Overig"),
]
VOERTUIG_SOORTEN = [("auto", "Auto"), ("motor", "Motor")]
DATUM_SOORTEN = [
    ("paspoort", "Paspoort"), ("id", "Identiteitskaart"), ("rijbewijs", "Rijbewijs"),
    ("belastingaangifte", "Belastingaangifte"), ("overig", "Overig"),
]
CONTACT_ROLLEN = [
    ("huisarts", "Huisarts"), ("tandarts", "Tandarts"), ("verzekeraar", "Verzekeraar"),
    ("garage", "Garage"), ("pas_blokkeren", "Pas blokkeren"), ("overig", "Overig"),
]
BLOEDGROEPEN = ["", "A+", "A-", "B+", "B-", "AB+", "AB-", "O+", "O-", "onbekend"]

NAV = [
    ("dashboard", "index", "Dashboard"),
    ("lasten", "lasten", "Vaste lasten & abonnementen"),
    ("verzekeringen", "verzekeringen", "Verzekeringen"),
    ("voertuigen", "voertuigen", "Voertuigen"),
    ("bezittingen", "bezittingen", "Bezittingen"),
    ("inkomen", "inkomen", "Inkomen & werk"),
    ("datums", "datums", "Belangrijke datums"),
    ("contacten", "contacten", "Contacten"),
    ("documenten", "documenten", "Documenten"),
    ("gezondheid", "gezondheid", "Gezondheid / noodinfo"),
]

EIGENAARS = {"bezit", "voertuig", "verzekering", "document"}
TABELLEN = {
    "vaste_lasten", "verzekeringen", "voertuigen", "bezittingen",
    "inkomens", "datums", "contacten", "documenten",
}
PLAATJES = {".jpg", ".jpeg", ".png", ".gif", ".webp", ".heic", ".heif"}
MIME = {
    ".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".png": "image/png",
    ".gif": "image/gif", ".webp": "image/webp", ".pdf": "application/pdf",
    ".heic": "image/heic", ".heif": "image/heif",
}
HEIC_MERKEN = {b"heic", b"heix", b"hevc", b"hevx", b"mif1", b"msf1", b"heim", b"heis", b"avci"}

# Elk item kan aan elk ander item hangen. De soortnamen zijn intern; de
# Nederlandse labels staan op de pagina.
KOPPEL_SOORTEN = {
    "last": {
        "label": "Vaste last",
        "tabel": "vaste_lasten",
        "pad": "/lasten/{id}",
        "zoek": ("naam", "categorie", "rekening", "notitie"),
    },
    "verzekering": {
        "label": "Verzekering",
        "tabel": "verzekeringen",
        "pad": "/verzekeringen/{id}",
        "zoek": ("maatschappij", "plan", "polisnummer", "dekking", "notitie", "hulpnummer"),
    },
    "voertuig": {
        "label": "Voertuig",
        "tabel": "voertuigen",
        "pad": "/voertuigen/{id}",
        "zoek": ("merk", "model", "kenteken", "notitie", "bandenmaat"),
    },
    "bezit": {
        "label": "Bezit",
        "tabel": "bezittingen",
        "pad": "/bezittingen/{id}",
        "zoek": ("naam", "winkel", "notitie"),
    },
    "inkomen": {
        "label": "Inkomen",
        "tabel": "inkomens",
        "pad": "/inkomen/{id}",
        "zoek": ("werkgever", "notitie"),
    },
    "datum": {
        "label": "Datum",
        "tabel": "datums",
        "pad": "/datums/{id}",
        "zoek": ("naam", "notitie", "soort"),
    },
    "contact": {
        "label": "Contact",
        "tabel": "contacten",
        "pad": "/contacten/{id}",
        "zoek": ("naam", "telefoon", "email", "notitie", "rol"),
    },
    "document": {
        "label": "Document",
        "tabel": "documenten",
        "pad": "/documenten/{id}",
        "zoek": ("titel", "notitie", "link"),
    },
    "gezondheid": {
        "label": "Gezondheid",
        "tabel": "noodinfo",
        "pad": "/gezondheid",
        "zoek": ("bloedgroep", "medicijnen", "allergieen", "nood_naam", "notitie"),
    },
}
KOPPEL_VAN_TABEL = {
    "vaste_lasten": "last",
    "verzekeringen": "verzekering",
    "voertuigen": "voertuig",
    "bezittingen": "bezit",
    "inkomens": "inkomen",
    "datums": "datum",
    "contacten": "contact",
    "documenten": "document",
}

FAVICON = """<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 32 32">
<rect width="32" height="32" rx="8" fill="#0f5c50"/>
<rect x="8" y="7" width="16" height="18" rx="2" fill="#fffdf8"/>
<rect x="11" y="12" width="10" height="2" rx="1" fill="#b8612e"/>
<rect x="11" y="17" width="10" height="2" rx="1" fill="#b8612e"/>
<rect x="11" y="22" width="7" height="2" rx="1" fill="#0f5c50"/>
</svg>"""


def _chmod(pad, modus):
    try:
        os.chmod(pad, modus)
    except OSError:
        pass


def _activeer_tijdzone():
    if not os.environ.get("TZ"):
        os.environ["TZ"] = "Europe/Amsterdam"
    if hasattr(time, "tzset"):
        try:
            time.tzset()
        except OSError:
            pass


_activeer_tijdzone()


def actieve_tijdzone():
    naam = os.environ.get("TZ") or "Europe/Amsterdam"
    try:
        return ZoneInfo(naam)
    except ZoneInfoNotFoundError:
        return ZoneInfo("Europe/Amsterdam")


def nu():
    return datetime.now(actieve_tijdzone()).replace(tzinfo=None)


def vandaag():
    return nu().date()


def _secret_key():
    override = os.environ.get("SECRET_KEY")
    if override:
        return override
    pad = os.path.join(DATA_DIR, "secret_key")
    if os.path.exists(pad):
        with open(pad, encoding="utf-8") as bestand:
            sleutel = bestand.read().strip()
        if sleutel:
            return sleutel
    sleutel = secrets.token_hex(32)
    with open(pad, "w", encoding="utf-8") as bestand:
        bestand.write(sleutel)
    _chmod(pad, 0o600)
    return sleutel


app = Flask(__name__)
app.secret_key = _secret_key()
app.jinja_env.undefined = StrictUndefined
app.config["MAX_CONTENT_LENGTH"] = MAX_VERZOEK
# Secure en HSTS gaan aan in activeer_https_vlag(), alleen als ssl aan staat.
# Op gewoon http zou Secure het cookie blokkeren.
app.config["SESSION_COOKIE_HTTPONLY"] = True
app.config["SESSION_COOKIE_SAMESITE"] = "Lax"
app.config["SESSION_COOKIE_SECURE"] = False
app.config["PERMANENT_SESSION_LIFETIME"] = timedelta(days=SESSIE_DAGEN)

# Eén trage hash, zodat een ontbrekend account niet sneller antwoordt dan een fout wachtwoord.
DUMMY_HASH = generate_password_hash("niet-het-wachtwoord")
POGINGEN_IP = {}
POGINGEN_ACCOUNT = (0, None)
HTTPS_ACTIEF = False


class VertrouwProxyAlleenLokaal:
    """X-Forwarded-For telt alleen in ssl-modus, en alleen vanaf localhost.

    Nginx overschrijft die kop met het echte adres. Op gewoon http blijft het
    TCP-adres gelden, ook als een bezoeker de kop zelf meestuurt.
    """

    def __init__(self, toepassing):
        self.toepassing = toepassing
        self.binnen = ProxyFix(toepassing, x_for=1)

    def __call__(self, environ, start_response):
        if HTTPS_ACTIEF and environ.get("REMOTE_ADDR") in {"127.0.0.1", "::1"}:
            return self.binnen(environ, start_response)
        return self.toepassing(environ, start_response)


app.wsgi_app = VertrouwProxyAlleenLokaal(app.wsgi_app)


def verbind():
    conn = sqlite3.connect(DB_PATH, timeout=10)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA busy_timeout = 5000")
    return conn


def init_db():
    """Maak de tabellen aan. Een nieuwe installatie blijft leeg."""
    conn = verbind()
    conn.execute("PRAGMA journal_mode = WAL")
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS account (
            id INTEGER PRIMARY KEY CHECK (id = 1),
            wachtwoord TEXT NOT NULL,
            aangemaakt TEXT NOT NULL,
            sessie_versie INTEGER NOT NULL DEFAULT 1
        );
        CREATE TABLE IF NOT EXISTS verzekeringen (
            id INTEGER PRIMARY KEY,
            soort TEXT NOT NULL,
            maatschappij TEXT NOT NULL DEFAULT '',
            plan TEXT NOT NULL DEFAULT '',
            eigen_risico TEXT NOT NULL DEFAULT '',
            dekking TEXT NOT NULL DEFAULT '',
            polisnummer TEXT NOT NULL DEFAULT '',
            premie_cent INTEGER,
            frequentie TEXT NOT NULL DEFAULT 'maand',
            telt_mee INTEGER NOT NULL DEFAULT 0,
            hulpnummer TEXT NOT NULL DEFAULT '',
            looptijd_van TEXT,
            looptijd_tot TEXT,
            notitie TEXT NOT NULL DEFAULT '',
            aangemaakt TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS vaste_lasten (
            id INTEGER PRIMARY KEY,
            naam TEXT NOT NULL,
            categorie TEXT NOT NULL DEFAULT 'Overig',
            bedrag_cent INTEGER NOT NULL DEFAULT 0,
            frequentie TEXT NOT NULL DEFAULT 'maand',
            afschrijfdag INTEGER,
            rekening TEXT NOT NULL DEFAULT '',
            contract_eind TEXT,
            opzegtermijn_dagen INTEGER,
            automatisch INTEGER NOT NULL DEFAULT 0,
            notitie TEXT NOT NULL DEFAULT '',
            link TEXT NOT NULL DEFAULT '',
            verzekering_id INTEGER UNIQUE REFERENCES verzekeringen(id) ON DELETE CASCADE,
            aangemaakt TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS voertuigen (
            id INTEGER PRIMARY KEY,
            soort TEXT NOT NULL,
            merk TEXT NOT NULL DEFAULT '',
            model TEXT NOT NULL DEFAULT '',
            kenteken TEXT NOT NULL DEFAULT '',
            bouwjaar INTEGER,
            apk_tot TEXT,
            verzekering_id INTEGER REFERENCES verzekeringen(id) ON DELETE SET NULL,
            bandenmaat TEXT NOT NULL DEFAULT '',
            notitie TEXT NOT NULL DEFAULT '',
            aangemaakt TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS bezittingen (
            id INTEGER PRIMARY KEY,
            naam TEXT NOT NULL,
            aankoop TEXT,
            winkel TEXT NOT NULL DEFAULT '',
            prijs_cent INTEGER,
            garantie_maanden INTEGER,
            garantie_tot TEXT,
            notitie TEXT NOT NULL DEFAULT '',
            aangemaakt TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS inkomens (
            id INTEGER PRIMARY KEY,
            werkgever TEXT NOT NULL,
            uren REAL,
            netto_cent INTEGER,
            betaaldag INTEGER,
            notitie TEXT NOT NULL DEFAULT '',
            aangemaakt TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS datums (
            id INTEGER PRIMARY KEY,
            soort TEXT NOT NULL,
            naam TEXT NOT NULL,
            datum TEXT NOT NULL,
            notitie TEXT NOT NULL DEFAULT '',
            aangemaakt TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS contacten (
            id INTEGER PRIMARY KEY,
            naam TEXT NOT NULL,
            rol TEXT NOT NULL DEFAULT 'overig',
            telefoon TEXT NOT NULL DEFAULT '',
            email TEXT NOT NULL DEFAULT '',
            notitie TEXT NOT NULL DEFAULT '',
            aangemaakt TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS documenten (
            id INTEGER PRIMARY KEY,
            titel TEXT NOT NULL,
            link TEXT NOT NULL DEFAULT '',
            verval TEXT,
            notitie TEXT NOT NULL DEFAULT '',
            aangemaakt TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS noodinfo (
            id INTEGER PRIMARY KEY CHECK (id = 1),
            bloedgroep TEXT NOT NULL DEFAULT '',
            medicijnen TEXT NOT NULL DEFAULT '',
            allergieen TEXT NOT NULL DEFAULT '',
            nood_naam TEXT NOT NULL DEFAULT '',
            nood_telefoon TEXT NOT NULL DEFAULT '',
            nood_relatie TEXT NOT NULL DEFAULT '',
            notitie TEXT NOT NULL DEFAULT ''
        );
        CREATE TABLE IF NOT EXISTS bestanden (
            id INTEGER PRIMARY KEY,
            eigenaar TEXT NOT NULL,
            eigenaar_id INTEGER NOT NULL,
            rol TEXT NOT NULL DEFAULT 'overig',
            opslag TEXT NOT NULL UNIQUE,
            naam TEXT NOT NULL,
            toegevoegd TEXT NOT NULL
        );
        CREATE INDEX IF NOT EXISTS bestanden_eigenaar ON bestanden (eigenaar, eigenaar_id);
        CREATE TABLE IF NOT EXISTS koppelingen (
            id INTEGER PRIMARY KEY,
            type_a TEXT NOT NULL,
            id_a INTEGER NOT NULL,
            type_b TEXT NOT NULL,
            id_b INTEGER NOT NULL,
            vast INTEGER NOT NULL DEFAULT 0,
            UNIQUE (type_a, id_a, type_b, id_b)
        );
        CREATE INDEX IF NOT EXISTS koppelingen_a ON koppelingen (type_a, id_a);
        CREATE INDEX IF NOT EXISTS koppelingen_b ON koppelingen (type_b, id_b);
        """
    )
    kolommen = {rij[1] for rij in conn.execute("PRAGMA table_info(account)")}
    if "sessie_versie" not in kolommen:
        conn.execute("ALTER TABLE account ADD COLUMN sessie_versie INTEGER NOT NULL DEFAULT 1")
    conn.commit()
    conn.close()
    if os.path.exists(DB_PATH):
        _chmod(DB_PATH, 0o600)


def lees_opties():
    try:
        with open(OPTIONS_PATH, encoding="utf-8") as bestand:
            data = json.load(bestand)
    except (OSError, json.JSONDecodeError):
        return {}
    return data if isinstance(data, dict) else {}


def optie_wachtwoord():
    waarde = lees_opties().get("wachtwoord", "")
    return waarde if isinstance(waarde, str) else ""


def optie_wachtwoord_actief():
    return len(optie_wachtwoord()) >= WACHTWOORD_MINIMUM


def _waar(waarde):
    if isinstance(waarde, bool):
        return waarde
    return str(waarde or "").strip().lower() in {"1", "true", "yes", "on"}


def ssl_gevraagd():
    omgeving = os.environ.get("SSL", "").strip().lower()
    if omgeving in {"0", "false", "no", "off"}:
        return False
    if omgeving in {"1", "true", "yes", "on"}:
        return True
    return _waar(lees_opties().get("ssl"))


def certificaat_pad(naam, omgeving):
    override = os.environ.get(omgeving, "").strip()
    if override:
        return override
    naam = naam if isinstance(naam, str) and naam.strip() else ""
    if not naam:
        return ""
    if os.path.isabs(naam):
        return naam
    return os.path.join(SSL_DIR, naam)


def ssl_paden():
    opties = lees_opties()
    cert = certificaat_pad(opties.get("certfile") or "fullchain.pem", "SSL_CERTFILE")
    sleutel = certificaat_pad(opties.get("keyfile") or "privkey.pem", "SSL_KEYFILE")
    return cert, sleutel


def maak_ssl_context():
    cert, sleutel = ssl_paden()
    if not os.path.isfile(cert) or not os.path.isfile(sleutel):
        logging.getLogger(__name__).error(
            "SSL staat aan, maar het certificaat of de sleutel ontbreekt."
        )
        return None
    context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    context.load_cert_chain(cert, sleutel)
    return context


def activeer_https_vlag():
    global HTTPS_ACTIEF
    HTTPS_ACTIEF = ssl_gevraagd()
    app.config["SESSION_COOKIE_SECURE"] = HTTPS_ACTIEF


def vingerafdruk(hash_):
    return hashlib.sha256((hash_ or "").encode("utf-8")).hexdigest()


def lees_account():
    conn = verbind()
    rij = conn.execute("SELECT wachtwoord, sessie_versie FROM account WHERE id=1").fetchone()
    conn.close()
    return rij


def verhoog_sessie_versie(conn):
    conn.execute("UPDATE account SET sessie_versie = COALESCE(sessie_versie, 1) + 1 WHERE id=1")


def synchroniseer_wachtwoord():
    """Het wachtwoord uit de add-on wint, als het lang genoeg is.

    Een leeg veld laat een bestaand wachtwoord staan. Verandert het wachtwoord,
    dan worden alle sessies ongeldig. Het wachtwoord zelf komt niet in het log.
    """
    wachtwoord = optie_wachtwoord()
    if not wachtwoord:
        return
    if len(wachtwoord) < WACHTWOORD_MINIMUM:
        logging.getLogger(__name__).warning(
            "Het wachtwoord in de add-on is korter dan %s tekens en wordt genegeerd.",
            WACHTWOORD_MINIMUM,
        )
        return
    conn = verbind()
    rij = conn.execute("SELECT wachtwoord FROM account WHERE id=1").fetchone()
    if rij is not None and check_password_hash(rij["wachtwoord"], wachtwoord):
        conn.close()
        wis_setup_code()
        return
    digest = generate_password_hash(wachtwoord)
    if rij is None:
        conn.execute(
            "INSERT INTO account (id, wachtwoord, aangemaakt, sessie_versie) VALUES (1, ?, ?, 1)",
            (digest, vandaag().isoformat()),
        )
    else:
        conn.execute(
            "UPDATE account SET wachtwoord=?, sessie_versie=COALESCE(sessie_versie, 1) + 1 WHERE id=1",
            (digest,),
        )
    conn.commit()
    conn.close()
    wis_setup_code()


def wis_setup_code():
    try:
        os.remove(SETUP_PATH)
    except OSError:
        pass


def zorg_setup_code():
    """Eenmalige code voor /instellen, alleen als er nog geen account is.

    De code zelf gaat naar het log. Op schijf staat alleen de hash. Een nieuwe
    start maakt een nieuwe code; de vorige werkt dan niet meer.
    """
    if heeft_account() or optie_wachtwoord_actief():
        wis_setup_code()
        return None
    code = secrets.token_urlsafe(9)
    with open(SETUP_PATH, "w", encoding="utf-8") as bestand:
        bestand.write(generate_password_hash(code))
    _chmod(SETUP_PATH, 0o600)
    regel = (
        "Mijn Overzicht: nog geen account. Zet een wachtwoord in de add-on en herstart, "
        f"of open /instellen met deze eenmalige code: {code}"
    )
    # print blijft zichtbaar als het logniveau warning en info wegfiltert.
    print(regel, flush=True)
    logging.getLogger(__name__).warning("%s", regel)
    return code


def setup_code_klopt(code):
    try:
        with open(SETUP_PATH, encoding="utf-8") as bestand:
            digest = bestand.read().strip()
    except OSError:
        return False
    if not digest or not isinstance(code, str) or not code:
        return False
    return check_password_hash(digest, code)


def csrf_token():
    if "csrf_token" not in session:
        session["csrf_token"] = secrets.token_urlsafe(32)
    return session["csrf_token"]


def melding(tekst, soort="gelukt"):
    flash(json.dumps({"tekst": tekst}, ensure_ascii=False), soort)


def pagina(template, actief, status=200, **context):
    context["actief"] = actief
    html = render_template(template, **context)
    if status == 200:
        return html
    return html, status


def weiger(template, actief, fouten, **context):
    melding(" ".join(fouten), "fout")
    return pagina(template, actief, status=400, **context)


def meld_bestanden(erbij, geweigerd):
    if erbij == 1:
        melding("Opgeslagen, met 1 bestand.")
    elif erbij:
        melding(f"Opgeslagen, met {erbij} bestanden.")
    else:
        melding("Opgeslagen.")
    if geweigerd:
        namen = ", ".join(tekst(naam, 40) for naam in geweigerd[:5])
        melding(
            f"Niet toegevoegd: {namen}. Alleen een foto (JPG, PNG, HEIC) of een PDF, tot 12 MB.",
            "fout",
        )


def terug_naar(standaard=None):
    referer = request.referrer or ""
    if referer:
        stuk = urlsplit(referer)
        eigen = urlsplit(request.host_url)
        if stuk.netloc == eigen.netloc:
            pad = stuk.path + (f"?{stuk.query}" if stuk.query else "")
            veilig = veilig_pad(pad)
            if veilig:
                return veilig
    return standaard or url_for("index")


def veilig_pad(pad):
    if not isinstance(pad, str) or not pad.startswith("/") or pad.startswith("//") or "\\" in pad:
        return None
    if urlsplit(pad).netloc:
        return None
    return pad


@app.template_filter("bedrag")
def _filter_bedrag(waarde):
    return format_bedrag(waarde)


@app.template_filter("datum_nl")
def _filter_datum(waarde):
    return datum_nl(waarde)


@app.template_filter("uit_json")
def _uit_json(waarde):
    return json.loads(waarde)


@app.context_processor
def algemeen():
    zoek_q = ""
    if request.endpoint == "zoeken":
        zoek_q = request.args.get("q", "") or ""
    return {"versie": VERSIE, "nav": NAV, "zoek_q": zoek_q}


app.jinja_env.globals["csrf_token"] = csrf_token
app.jinja_env.globals["LAST_CATEGORIEEN"] = LAST_CATEGORIEEN
app.jinja_env.globals["VERZEKERING_SOORTEN"] = VERZEKERING_SOORTEN
app.jinja_env.globals["VOERTUIG_SOORTEN"] = VOERTUIG_SOORTEN
app.jinja_env.globals["DATUM_SOORTEN"] = DATUM_SOORTEN
app.jinja_env.globals["CONTACT_ROLLEN"] = CONTACT_ROLLEN
app.jinja_env.globals["FREQUENTIES"] = FREQUENTIES
app.jinja_env.globals["BLOEDGROEPEN"] = BLOEDGROEPEN


PAGINA_CSP = (
    "default-src 'self'; img-src 'self' data:; style-src 'self'; script-src 'self'; "
    "frame-src 'self'; form-action 'self'; base-uri 'self'; object-src 'none'; "
    "frame-ancestors 'none'"
)
BESTAND_CSP = "default-src 'none'; style-src 'none'; script-src 'none'; sandbox; frame-ancestors 'self'"


@app.after_request
def beveiligingskoppen(antwoord):
    antwoord.headers["X-Content-Type-Options"] = "nosniff"
    antwoord.headers["Referrer-Policy"] = "same-origin"
    antwoord.headers["Cache-Control"] = "no-store"
    if request.endpoint == "bestand_zien":
        antwoord.headers["X-Frame-Options"] = "SAMEORIGIN"
        antwoord.headers["Content-Security-Policy"] = BESTAND_CSP
    else:
        antwoord.headers["X-Frame-Options"] = "DENY"
        antwoord.headers["Content-Security-Policy"] = PAGINA_CSP
    if HTTPS_ACTIEF or request.is_secure:
        antwoord.headers["Strict-Transport-Security"] = f"max-age={HSTS_SECONDEN}"
    return antwoord


@app.before_request
def controleer_inlog():
    if request.endpoint in {"inloggen", "account_instellen", "favicon", "static"}:
        return None
    if not heeft_account():
        return redirect(url_for("account_instellen"))
    if sessie_geldig():
        return None
    session.clear()
    terug = request.full_path.rstrip("?") or request.path
    return redirect(url_for("inloggen", verder=terug))


@app.before_request
def controleer_csrf():
    if request.method != "POST":
        return None
    verwacht = session.get("csrf_token") or ""
    gekregen = request.form.get("csrf_token", "")
    if not isinstance(gekregen, str) or not verwacht or len(verwacht) != len(gekregen):
        abort(400, "Deze opdracht kwam niet van de app zelf.")
    if not secrets.compare_digest(verwacht, gekregen):
        abort(400, "Deze opdracht kwam niet van de app zelf.")
    return None


@app.errorhandler(404)
def niet_gevonden(_fout):
    if not sessie_geldig():
        return redirect(url_for("inloggen"))
    return pagina("fout.html", "", titel="Niet gevonden", tekst="Deze pagina bestaat niet."), 404


@app.errorhandler(413)
def te_groot(_fout):
    melding("Dat is te veel in één keer. Een bestand mag hooguit 12 MB zijn.", "fout")
    return redirect(url_for("index"))


def heeft_account():
    conn = verbind()
    aantal = conn.execute("SELECT COUNT(*) FROM account").fetchone()[0]
    conn.close()
    return aantal > 0


def sessie_geldig():
    if not session.get("ingelogd"):
        return False
    rij = lees_account()
    if rij is None:
        return False
    if session.get("sessie_versie") != rij["sessie_versie"]:
        return False
    verwacht = vingerafdruk(rij["wachtwoord"])
    gekregen = session.get("wachtwoord_vinger") or ""
    if not isinstance(gekregen, str) or len(gekregen) != len(verwacht):
        return False
    return secrets.compare_digest(gekregen, verwacht)


def _afzender():
    return request.remote_addr or "onbekend"


def pauze_seconden(aantal, laatste, plafond):
    if not laatste or aantal < PAUZE_NA_POGINGEN:
        return 0
    duur = min(2 ** (aantal - PAUZE_NA_POGINGEN), plafond)
    resterend = duur - (nu() - laatste).total_seconds()
    if resterend <= 0:
        return 0
    return int(resterend) + (0 if resterend == int(resterend) else 1)


def ip_wachttijd():
    aantal, laatste = POGINGEN_IP.get(_afzender(), (0, None))
    return pauze_seconden(aantal, laatste, IP_PLAFOND)


def account_wachttijd():
    aantal, laatste = POGINGEN_ACCOUNT
    return pauze_seconden(aantal, laatste, ACCOUNT_PLAFOND)


def wachttijd_over():
    """Pauze die het formulier toont: alleen dit adres, niet het hele account."""
    return ip_wachttijd()


def hash_klopt(hash_, wachtwoord):
    if not isinstance(hash_, str) or not hash_.strip() or not isinstance(wachtwoord, str):
        return False
    try:
        return check_password_hash(hash_, wachtwoord)
    except (ValueError, TypeError):
        return False


def wachtwoord_ontbreekt():
    rij = lees_account()
    if rij is None:
        return False
    return not str(rij["wachtwoord"] or "").strip()


def noteer_mislukking():
    global POGINGEN_ACCOUNT
    nu_ = nu()
    ip = _afzender()
    aantal, _ = POGINGEN_IP.get(ip, (0, None))
    POGINGEN_IP[ip] = (aantal + 1, nu_)
    if len(POGINGEN_IP) > POGINGEN_IP_MAX:
        oudste = sorted(POGINGEN_IP, key=lambda sleutel: POGINGEN_IP[sleutel][1] or datetime.min)
        for sleutel in oudste[: len(POGINGEN_IP) - POGINGEN_IP_MAX]:
            POGINGEN_IP.pop(sleutel, None)
    acc_aantal, _ = POGINGEN_ACCOUNT
    POGINGEN_ACCOUNT = (acc_aantal + 1, nu_)


def wis_mislukkingen():
    global POGINGEN_ACCOUNT
    POGINGEN_IP.pop(_afzender(), None)
    POGINGEN_ACCOUNT = (0, None)


def start_sessie(onthoud):
    rij = lees_account()
    session.clear()
    session["ingelogd"] = True
    session["csrf_token"] = secrets.token_urlsafe(32)
    session["sessie_versie"] = rij["sessie_versie"] if rij else 0
    session["wachtwoord_vinger"] = vingerafdruk(rij["wachtwoord"]) if rij else ""
    session.permanent = bool(onthoud)


@app.route("/favicon.svg")
def favicon():
    return Response(FAVICON, mimetype="image/svg+xml")


@app.route("/instellen", methods=["GET", "POST"])
def account_instellen():
    if heeft_account():
        return redirect(url_for("inloggen"))
    if request.method == "POST":
        if wachttijd_over():
            return redirect(url_for("account_instellen"))
        code = request.form.get("code", "")
        wachtwoord = request.form.get("wachtwoord", "")
        nogmaals = request.form.get("nogmaals", "")
        if not setup_code_klopt(code):
            noteer_mislukking()
            melding("De instelcode klopt niet. Hij staat eenmalig in het log van de add-on.", "fout")
            return redirect(url_for("account_instellen"))
        if len(wachtwoord) < WACHTWOORD_MINIMUM:
            melding(f"Kies een wachtwoord van minstens {WACHTWOORD_MINIMUM} tekens.", "fout")
            return redirect(url_for("account_instellen"))
        if wachtwoord != nogmaals:
            melding("De twee wachtwoorden zijn niet hetzelfde.", "fout")
            return redirect(url_for("account_instellen"))
        conn = verbind()
        try:
            conn.execute(
                "INSERT INTO account (id, wachtwoord, aangemaakt, sessie_versie) VALUES (1, ?, ?, 1)",
                (generate_password_hash(wachtwoord), vandaag().isoformat()),
            )
            conn.commit()
        except sqlite3.IntegrityError:
            conn.close()
            return redirect(url_for("inloggen"))
        conn.close()
        wis_setup_code()
        wis_mislukkingen()
        start_sessie(True)
        return redirect(url_for("index"))
    return render_template("instellen.html", minimum=WACHTWOORD_MINIMUM, wacht=wachttijd_over())


@app.route("/inloggen", methods=["GET", "POST"])
def inloggen():
    if not heeft_account():
        return redirect(url_for("account_instellen"))
    if sessie_geldig():
        return redirect(url_for("index"))
    verder = request.args.get("verder", "") if request.method == "GET" else request.form.get("verder", "")
    if request.method == "POST":
        # Dit adres heeft te vaak gefaald. Een ander adres wordt hier niet door geraakt.
        if ip_wachttijd():
            return redirect(url_for("inloggen"))
        wachtwoord = request.form.get("wachtwoord", "")
        conn = verbind()
        rij = conn.execute("SELECT wachtwoord FROM account WHERE id=1").fetchone()
        conn.close()
        hash_ = rij["wachtwoord"] if rij else ""
        if rij is not None and hash_klopt(hash_, wachtwoord):
            wis_mislukkingen()
            start_sessie(request.form.get("onthoud") == "ja")
            return redirect(veilig_pad(verder) or url_for("index"))
        # Elke foute gok telt voor dit adres, ook als het account al in de pauze zit.
        # Zo kan een aanvaller met steeds een nieuw adres niet onbeperkt blijven proberen.
        noteer_mislukking()
        if not str(hash_ or "").strip():
            melding("Er is geen wachtwoord ingesteld. Zet het in de add-on en start opnieuw.", "fout")
        else:
            melding("Wachtwoord klopt niet.", "fout")
        return redirect(url_for("inloggen", verder=verder))
    return render_template(
        "inloggen.html",
        verder=verder,
        wacht=ip_wachttijd(),
        zonder_wachtwoord=wachtwoord_ontbreekt(),
    )


@app.route("/uitloggen", methods=["POST"])
def uitloggen():
    conn = verbind()
    if conn.execute("SELECT id FROM account WHERE id=1").fetchone():
        verhoog_sessie_versie(conn)
        conn.commit()
    conn.close()
    session.clear()
    melding("Je bent uitgelogd.")
    return redirect(url_for("inloggen"))


@app.route("/wachtwoord", methods=["POST"])
def wachtwoord_wijzigen():
    if optie_wachtwoord_actief():
        melding("Het wachtwoord staat in de add-on. Wijzig het daar en start de add-on opnieuw.", "fout")
        return redirect(url_for("index"))
    huidig = request.form.get("huidig", "")
    nieuw = request.form.get("nieuw", "")
    nogmaals = request.form.get("nogmaals", "")
    conn = verbind()
    rij = conn.execute("SELECT wachtwoord FROM account WHERE id=1").fetchone()
    hash_ = rij["wachtwoord"] if rij else DUMMY_HASH
    if not check_password_hash(hash_, huidig) or rij is None:
        conn.close()
        melding("Je huidige wachtwoord klopt niet.", "fout")
        return redirect(url_for("index"))
    if len(nieuw) < WACHTWOORD_MINIMUM:
        conn.close()
        melding(f"Kies een wachtwoord van minstens {WACHTWOORD_MINIMUM} tekens.", "fout")
        return redirect(url_for("index"))
    if nieuw != nogmaals:
        conn.close()
        melding("De twee nieuwe wachtwoorden zijn niet hetzelfde.", "fout")
        return redirect(url_for("index"))
    conn.execute(
        "UPDATE account SET wachtwoord=?, sessie_versie=COALESCE(sessie_versie, 1) + 1 WHERE id=1",
        (generate_password_hash(nieuw),),
    )
    conn.commit()
    conn.close()
    start_sessie(True)
    melding("Je wachtwoord is gewijzigd.")
    return redirect(url_for("index"))


def bijschrift(paren, sleutel):
    for code, tekst_label in paren:
        if code == sleutel:
            return tekst_label
    return sleutel or ""


def format_bedrag(centen):
    if centen is None or centen == "":
        return ""
    centen = int(centen)
    teken = "-" if centen < 0 else ""
    centen = abs(centen)
    euros, cent = divmod(centen, 100)
    return teken + f"{euros:,}".replace(",", ".") + f",{cent:02d}"


def format_uren(waarde):
    if waarde is None:
        return ""
    tekst_uren = f"{float(waarde):.2f}".replace(".", ",").rstrip("0").rstrip(",")
    return tekst_uren


def datum_nl(waarde):
    if not waarde:
        return ""
    if isinstance(waarde, date):
        dag = waarde
    else:
        try:
            dag = date.fromisoformat(str(waarde)[:10])
        except ValueError:
            return ""
    return f"{dag.day} {MAANDEN[dag.month - 1]} {dag.year}"


def tekst(waarde, max_len):
    if waarde is None:
        return ""
    schoon = str(waarde).replace("\r\n", "\n").replace("\r", "\n").strip()
    return schoon[:max_len]


def keuze(waarde, toegestaan, label, fouten, verplicht=True):
    waarde = (waarde or "").strip()
    if waarde in toegestaan:
        return waarde
    if not waarde and not verplicht:
        return ""
    fouten.append(f"Kies een geldige {label}.")
    return ""


def heel_getal(waarde, label, fouten, min_waarde, max_waarde):
    ruw = (waarde or "").strip()
    if ruw == "":
        return None
    if not re.fullmatch(r"\d+", ruw):
        fouten.append(f"{label} moet een geheel getal zijn.")
        return None
    nummer = int(ruw)
    if nummer < min_waarde or nummer > max_waarde:
        fouten.append(f"{label} moet tussen {min_waarde} en {max_waarde} liggen.")
        return None
    return nummer


def naar_centen(waarde, label, fouten, leeg_is_nul=False):
    ruw = (waarde or "").strip().replace("€", "").replace("EUR", "").replace("\u00a0", "").replace(" ", "")
    if ruw == "":
        return 0 if leeg_is_nul else None
    if "," in ruw and "." in ruw:
        if ruw.rfind(",") > ruw.rfind("."):
            ruw = ruw.replace(".", "").replace(",", ".")
        else:
            ruw = ruw.replace(",", "")
    elif "," in ruw:
        ruw = ruw.replace(",", ".")
    try:
        bedrag = Decimal(ruw)
    except InvalidOperation:
        fouten.append(f"{label} is geen bedrag.")
        return None
    if bedrag < 0 or bedrag > Decimal("10000000"):
        fouten.append(f"{label} moet tussen 0 en 10.000.000 liggen.")
        return None
    return int((bedrag * 100).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def datum_veld(waarde, label, fouten, verplicht=False):
    ruw = (waarde or "").strip()
    if not ruw:
        if verplicht:
            fouten.append(f"Vul {label} in.")
        return None
    try:
        return date.fromisoformat(ruw).isoformat()
    except ValueError:
        fouten.append(f"{label} is geen geldige datum.")
        return None


def toon_link(waarde):
    ruw = (waarde or "").strip()
    if not ruw or len(ruw) > 500:
        return ""
    stuk = urlsplit(ruw)
    if stuk.scheme in {"http", "https"} and stuk.netloc and "\\" not in ruw:
        return ruw
    return ""


def link_veld(waarde, fouten):
    ruw = tekst(waarde, 500)
    if not ruw:
        return ""
    if toon_link(ruw):
        return ruw
    fouten.append("De link moet met http:// of https:// beginnen.")
    return ""


def email_veld(waarde, fouten):
    ruw = tekst(waarde, 200)
    if not ruw:
        return ""
    if re.fullmatch(r"[^@\s]+@[^@\s]+\.[^@\s]+", ruw):
        return ruw
    fouten.append("Dit e-mailadres klopt niet.")
    return ""


def tel_link(nummer):
    cijfers = re.sub(r"[^\d+]", "", nummer or "")
    if cijfers.startswith("00"):
        cijfers = "+" + cijfers[2:]
    if cijfers.count("+") > 1 or ("+" in cijfers and not cijfers.startswith("+")):
        return ""
    kaal = cijfers[1:] if cijfers.startswith("+") else cijfers
    if not kaal.isdigit() or not 6 <= len(kaal) <= 15:
        return ""
    return "tel:" + cijfers


def mail_link(adres):
    adres = (adres or "").strip()
    if re.fullmatch(r"[^@\s]+@[^@\s]+\.[^@\s]+", adres):
        return "mailto:" + adres
    return ""


def net_kenteken(waarde):
    ruw = (waarde or "").strip().upper()
    if not ruw:
        return "", None
    schoon = re.sub(r"[^A-Z0-9]", "", ruw)
    if not schoon or len(schoon) > 10:
        return ruw, "Kenteken mag alleen letters en cijfers hebben, hooguit 10."
    return schoon, None


def naar_uren(waarde, fouten):
    ruw = (waarde or "").strip().replace(",", ".")
    if ruw == "":
        return None
    try:
        uren = Decimal(ruw)
    except InvalidOperation:
        fouten.append("Contracturen is geen getal.")
        return None
    if uren < 0 or uren > 80:
        fouten.append("Contracturen moet tussen 0 en 80 liggen.")
        return None
    return float(uren.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))


def per_jaar_cent(bedrag_cent, frequentie):
    return int(bedrag_cent or 0) * MAAL_PER_JAAR.get(frequentie, 0)


def totalen(rijen):
    jaar = sum(per_jaar_cent(rij["bedrag_cent"], rij["frequentie"]) for rij in rijen)
    maand = (jaar + 6) // 12 if jaar else 0
    return maand, jaar


def per_categorie(rijen):
    bak = {}
    for rij in rijen:
        bak[rij["categorie"]] = bak.get(rij["categorie"], 0) + per_jaar_cent(rij["bedrag_cent"], rij["frequentie"])
    return [
        {"naam": naam, "jaar": bedrag, "maand": (bedrag + 6) // 12}
        for naam, bedrag in sorted(bak.items())
    ]


def tel_maanden_op(start, maanden):
    maand_index = start.month - 1 + int(maanden)
    jaar = start.year + maand_index // 12
    maand = maand_index % 12 + 1
    dag = min(start.day, calendar.monthrange(jaar, maand)[1])
    return date(jaar, maand, dag)


def garantie_einde(aankoop, maanden, garantie_tot):
    if garantie_tot:
        try:
            return date.fromisoformat(garantie_tot)
        except ValueError:
            return None
    if aankoop and maanden is not None:
        try:
            return tel_maanden_op(date.fromisoformat(aankoop), int(maanden))
        except (ValueError, TypeError):
            return None
    return None


def garantie_badge(aankoop, maanden, garantie_tot, op=None):
    op = op or vandaag()
    eind = garantie_einde(aankoop, maanden, garantie_tot)
    if eind is None:
        return None
    if eind < op:
        return {"tekst": "verlopen", "soort": "verlopen", "eind": eind.isoformat()}
    if eind == op:
        return {"tekst": "verloopt vandaag", "soort": "bijna", "eind": eind.isoformat()}
    maanden_over = (eind.year - op.year) * 12 + (eind.month - op.month)
    if eind.day < op.day:
        maanden_over -= 1
    if maanden_over >= 1:
        woord = "maand" if maanden_over == 1 else "maanden"
        soort = "bijna" if maanden_over <= 2 else "ok"
        return {"tekst": f"nog {maanden_over} {woord} garantie", "soort": soort, "eind": eind.isoformat()}
    dagen = (eind - op).days
    woord = "dag" if dagen == 1 else "dagen"
    return {"tekst": f"nog {dagen} {woord} garantie", "soort": "bijna", "eind": eind.isoformat()}


def opzeg_advies(eind_iso, termijn, automatisch, op=None):
    op = op or vandaag()
    auto = bool(automatisch)
    if not eind_iso and auto and termijn == 0:
        return {"tekst": "Op elk moment opzegbaar", "datum": None, "soort": "opzegbaar"}
    if not eind_iso:
        return None
    try:
        eind = date.fromisoformat(eind_iso)
    except ValueError:
        return None
    if eind < op:
        return None
    if auto:
        deadline = eind - timedelta(days=termijn or 0)
        if deadline <= op + timedelta(days=BINNENKORT_DAGEN):
            return {
                "tekst": f"Zeg op vóór {datum_nl(deadline)}, anders verlengt dit automatisch",
                "datum": deadline,
                "soort": "opzeggen",
            }
        return None
    if eind <= op + timedelta(days=BINNENKORT_DAGEN):
        return {"tekst": "Loopt af en verlengt niet vanzelf", "datum": eind, "soort": "loopt_af"}
    return None


def _advies_item(advies, titel, url):
    chip = {"opzeggen": "bijna", "opzegbaar": "ok", "loopt_af": "neutral"}[advies["soort"]]
    return {
        "titel": titel,
        "url": url,
        "tekst": advies["tekst"],
        "datum": advies["datum"].isoformat() if advies["datum"] else "",
        "soort": advies["soort"],
        "chip": chip,
    }


def opzeg_lijst(conn, op=None):
    op = op or vandaag()
    items = []
    gekoppeld = set()
    for rij in conn.execute("SELECT * FROM vaste_lasten ORDER BY naam"):
        if rij["verzekering_id"]:
            gekoppeld.add(rij["verzekering_id"])
        advies = opzeg_advies(rij["contract_eind"], rij["opzegtermijn_dagen"], rij["automatisch"], op)
        if advies:
            items.append(_advies_item(advies, rij["naam"], f"/lasten/{rij['id']}"))
    for rij in conn.execute("SELECT * FROM verzekeringen ORDER BY maatschappij"):
        if rij["id"] in gekoppeld:
            continue
        advies = opzeg_advies(rij["looptijd_tot"], None, 0, op)
        if advies:
            items.append(_advies_item(advies, verzekering_kaarttitel(rij), f"/verzekeringen/{rij['id']}"))
    items.sort(key=lambda item: (item["datum"] or "9999", item["titel"]))
    return items


def agenda(conn, op=None):
    op = op or vandaag()
    vroeg = op - timedelta(days=VERLOPEN_DAGEN)
    laat = op + timedelta(days=BINNENKORT_DAGEN)
    items = []
    gekoppeld = {
        rij["verzekering_id"]
        for rij in conn.execute("SELECT verzekering_id FROM vaste_lasten WHERE verzekering_id IS NOT NULL")
    }

    def voeg(datum_iso, titel, soort, url):
        if not datum_iso:
            return
        try:
            dag = date.fromisoformat(datum_iso)
        except ValueError:
            return
        if dag < vroeg or dag > laat:
            return
        items.append({
            "iso": dag.isoformat(),
            "titel": titel,
            "soort": soort,
            "url": url,
            "verlopen": dag < op,
        })

    for rij in conn.execute("SELECT * FROM vaste_lasten"):
        voeg(rij["contract_eind"], rij["naam"], "Contract", f"/lasten/{rij['id']}")
    for rij in conn.execute("SELECT * FROM verzekeringen"):
        if rij["id"] in gekoppeld:
            continue
        voeg(rij["looptijd_tot"], verzekering_kaarttitel(rij), "Verzekering", f"/verzekeringen/{rij['id']}")
    for rij in conn.execute("SELECT * FROM voertuigen"):
        voeg(rij["apk_tot"], voertuig_titel(rij), "APK", f"/voertuigen/{rij['id']}")
    for rij in conn.execute("SELECT * FROM bezittingen"):
        eind = garantie_einde(rij["aankoop"], rij["garantie_maanden"], rij["garantie_tot"])
        if eind:
            voeg(eind.isoformat(), rij["naam"], "Garantie", f"/bezittingen/{rij['id']}")
    for rij in conn.execute("SELECT * FROM datums"):
        voeg(rij["datum"], rij["naam"], bijschrift(DATUM_SOORTEN, rij["soort"]), f"/datums/{rij['id']}")
    for rij in conn.execute("SELECT * FROM documenten"):
        voeg(rij["verval"], rij["titel"], "Document", f"/documenten/{rij['id']}")
    items.sort(key=lambda item: (item["iso"], item["soort"], item["titel"]))
    return items


def verzekering_kaarttitel(rij):
    delen = [bijschrift(VERZEKERING_SOORTEN, rij["soort"])]
    if rij["maatschappij"]:
        delen.append(rij["maatschappij"])
    if rij["plan"]:
        delen.append(rij["plan"])
    return " · ".join(delen)


def verzekering_lastnaam(rij):
    return ("Verzekering " + verzekering_kaarttitel(rij))[:200]


def voertuig_titel(rij):
    naam = " ".join(deel for deel in (rij["merk"], rij["model"]) if deel).strip()
    return naam or bijschrift(VOERTUIG_SOORTEN, rij["soort"])


def sync_last_van_verzekering(conn, verz_id):
    verz = conn.execute("SELECT * FROM verzekeringen WHERE id=?", (verz_id,)).fetchone()
    if verz is None:
        return
    bestaand = conn.execute("SELECT * FROM vaste_lasten WHERE verzekering_id=?", (verz_id,)).fetchone()
    if not verz["telt_mee"]:
        if bestaand:
            wis_koppelingen(conn, "last", bestaand["id"])
            conn.execute("DELETE FROM vaste_lasten WHERE id=?", (bestaand["id"],))
        return
    naam = verzekering_lastnaam(verz)
    bedrag = verz["premie_cent"] or 0
    freq = verz["frequentie"] if verz["frequentie"] in MAAL_PER_JAAR else "maand"
    if bestaand:
        conn.execute(
            """UPDATE vaste_lasten
               SET naam=?, categorie='Verzekering', bedrag_cent=?, frequentie=?
               WHERE id=?""",
            (naam, bedrag, freq, bestaand["id"]),
        )
        if verz["looptijd_tot"]:
            conn.execute(
                "UPDATE vaste_lasten SET contract_eind=? WHERE id=?",
                (verz["looptijd_tot"], bestaand["id"]),
            )
        zorg_koppeling(conn, "last", bestaand["id"], "verzekering", verz_id, vast=1)
        return
    last_id = conn.execute(
        """INSERT INTO vaste_lasten
           (naam, categorie, bedrag_cent, frequentie, contract_eind, automatisch,
            notitie, link, verzekering_id, aangemaakt)
           VALUES (?, 'Verzekering', ?, ?, ?, 0, '', '', ?, ?)""",
        (naam, bedrag, freq, verz["looptijd_tot"], verz_id, vandaag().isoformat()),
    ).lastrowid
    zorg_koppeling(conn, "last", last_id, "verzekering", verz_id, vast=1)


def sync_voertuig_verzekering(conn, voertuig_id, oud_id, nieuw_id):
    """De gekozen verzekering blijft een klikbare koppeling, beide kanten op."""
    if oud_id and oud_id != nieuw_id:
        wis_vast_paar(conn, "voertuig", voertuig_id, "verzekering", oud_id)
    if nieuw_id:
        zorg_koppeling(conn, "voertuig", voertuig_id, "verzekering", nieuw_id, vast=1)


def _kolom_ok(naam):
    return bool(re.fullmatch(r"[a-z_]+", naam or ""))


def koppel_titel(conn, soort, id_):
    spec = KOPPEL_SOORTEN.get(soort)
    if spec is None or not _kolom_ok(spec["tabel"]):
        return None
    try:
        id_ = int(id_)
    except (TypeError, ValueError):
        return None
    if soort == "gezondheid":
        return "Gezondheid / noodinfo" if id_ == 1 else None
    rij = conn.execute(f"SELECT * FROM {spec['tabel']} WHERE id=?", (id_,)).fetchone()
    if rij is None:
        return None
    if soort == "verzekering":
        return verzekering_kaarttitel(rij)
    if soort == "voertuig":
        return voertuig_titel(rij)
    if soort == "inkomen":
        return rij["werkgever"]
    if soort == "document":
        return rij["titel"]
    return rij["naam"]


def koppel_pad(soort, id_):
    spec = KOPPEL_SOORTEN.get(soort)
    if spec is None:
        return None
    return spec["pad"].format(id=int(id_))


def orden_paar(soort_a, id_a, soort_b, id_b):
    if soort_a not in KOPPEL_SOORTEN or soort_b not in KOPPEL_SOORTEN:
        return None
    links = (soort_a, int(id_a))
    rechts = (soort_b, int(id_b))
    if links == rechts:
        return None
    if links > rechts:
        links, rechts = rechts, links
    return links[0], links[1], rechts[0], rechts[1]


def zorg_koppeling(conn, soort_a, id_a, soort_b, id_b, vast=0):
    paar = orden_paar(soort_a, id_a, soort_b, id_b)
    if paar is None:
        return None
    bestaand = conn.execute(
        "SELECT id, vast FROM koppelingen WHERE type_a=? AND id_a=? AND type_b=? AND id_b=?",
        paar,
    ).fetchone()
    if bestaand:
        if vast and not bestaand["vast"]:
            conn.execute("UPDATE koppelingen SET vast=1 WHERE id=?", (bestaand["id"],))
        return bestaand["id"]
    return conn.execute(
        "INSERT INTO koppelingen (type_a, id_a, type_b, id_b, vast) VALUES (?, ?, ?, ?, ?)",
        (*paar, 1 if vast else 0),
    ).lastrowid


def wis_koppelingen(conn, soort, id_):
    conn.execute(
        "DELETE FROM koppelingen WHERE (type_a=? AND id_a=?) OR (type_b=? AND id_b=?)",
        (soort, int(id_), soort, int(id_)),
    )


def wis_vast_paar(conn, soort_a, id_a, soort_b, id_b):
    paar = orden_paar(soort_a, id_a, soort_b, id_b)
    if paar is None:
        return
    conn.execute(
        """DELETE FROM koppelingen
           WHERE type_a=? AND id_a=? AND type_b=? AND id_b=? AND vast=1""",
        paar,
    )


def koppelingen_van(conn, soort, id_):
    rijen = conn.execute(
        """SELECT * FROM koppelingen
           WHERE (type_a=? AND id_a=?) OR (type_b=? AND id_b=?)
           ORDER BY id""",
        (soort, int(id_), soort, int(id_)),
    ).fetchall()
    uit = []
    gezien = set()
    for rij in rijen:
        if rij["type_a"] == soort and rij["id_a"] == int(id_):
            ander, ander_id = rij["type_b"], rij["id_b"]
        else:
            ander, ander_id = rij["type_a"], rij["id_a"]
        sleutel = (ander, ander_id)
        if sleutel in gezien or ander not in KOPPEL_SOORTEN:
            continue
        gezien.add(sleutel)
        titel = koppel_titel(conn, ander, ander_id)
        if not titel:
            continue
        uit.append({
            "koppel_id": rij["id"],
            "soort": ander,
            "id": ander_id,
            "soort_label": KOPPEL_SOORTEN[ander]["label"],
            "titel": titel,
            "url": koppel_pad(ander, ander_id),
            "vast": bool(rij["vast"]),
        })
    return uit


def chip_index(conn):
    index = {}
    for rij in conn.execute("SELECT * FROM koppelingen ORDER BY id"):
        kanten = (
            ((rij["type_a"], rij["id_a"]), (rij["type_b"], rij["id_b"])),
            ((rij["type_b"], rij["id_b"]), (rij["type_a"], rij["id_a"])),
        )
        for eigen, ander in kanten:
            if ander[0] not in KOPPEL_SOORTEN:
                continue
            titel = koppel_titel(conn, ander[0], ander[1])
            if not titel:
                continue
            emmer = index.setdefault(eigen, [])
            if any(chip["soort"] == ander[0] and chip["id"] == ander[1] for chip in emmer):
                continue
            emmer.append({
                "soort": ander[0],
                "id": ander[1],
                "soort_label": KOPPEL_SOORTEN[ander[0]]["label"],
                "titel": titel,
                "url": koppel_pad(ander[0], ander[1]),
            })
    return index


def hang_chips(conn, items, soort):
    index = chip_index(conn)
    for item in items:
        item["koppelingen"] = index.get((soort, item["id"]), [])
    return items


def koppel_leeg(soort):
    return {
        "koppelingen": [],
        "koppel_type": soort,
        "koppel_id": None,
        "kies": "",
        "kies_resultaten": [],
        "kies_te_kort": False,
    }


def koppel_extra(conn, soort, id_):
    if id_ is None:
        return koppel_leeg(soort)
    kies = tekst(request.args.get("kies", ""), 80) if request.method == "GET" else ""
    return {
        "koppelingen": koppelingen_van(conn, soort, id_),
        "koppel_type": soort,
        "koppel_id": id_,
        "kies": kies,
        "kies_resultaten": zoek_kandidaten(conn, kies, soort, id_) if len(kies) >= 2 else [],
        "kies_te_kort": bool(kies) and len(kies) < 2,
    }


def zoek_kandidaten(conn, q, eigen_soort, eigen_id):
    patroon = like_patroon(q)
    bezet = {(item["soort"], item["id"]) for item in koppelingen_van(conn, eigen_soort, eigen_id)}
    bezet.add((eigen_soort, int(eigen_id)))
    uit = []
    for soort, spec in KOPPEL_SOORTEN.items():
        if not _kolom_ok(spec["tabel"]) or not all(_kolom_ok(kolom) for kolom in spec["zoek"]):
            continue
        if soort == "gezondheid":
            if ("gezondheid", 1) in bezet:
                continue
            rij = conn.execute("SELECT * FROM noodinfo WHERE id=1").fetchone()
            woorden = ("gezond", "nood", "bloed", "medicijn", "allerg")
            treffer = any(woord in q.lower() for woord in woorden)
            if rij is not None and not treffer:
                treffer = any(q.lower() in (rij[kolom] or "").lower() for kolom in spec["zoek"])
            if treffer:
                uit.append({
                    "soort": "gezondheid",
                    "soort_label": spec["label"],
                    "id": 1,
                    "titel": "Gezondheid / noodinfo",
                })
            continue
        where = " OR ".join(f"{kolom} LIKE ? ESCAPE '\\'" for kolom in spec["zoek"])
        sql = f"SELECT * FROM {spec['tabel']} WHERE {where} ORDER BY id LIMIT 8"
        for rij in conn.execute(sql, (patroon,) * len(spec["zoek"])):
            if (soort, rij["id"]) in bezet:
                continue
            uit.append({
                "soort": soort,
                "soort_label": spec["label"],
                "id": rij["id"],
                "titel": koppel_titel(conn, soort, rij["id"]),
            })
            if len(uit) >= 24:
                return uit
    return uit


def herstel_koppelingen():
    """Bestaande premie- en voertuigkoppelingen ook als klikbare link tonen."""
    conn = verbind()
    for rij in conn.execute(
        "SELECT id, verzekering_id FROM vaste_lasten WHERE verzekering_id IS NOT NULL"
    ):
        zorg_koppeling(conn, "last", rij["id"], "verzekering", rij["verzekering_id"], vast=1)
    for rij in conn.execute(
        "SELECT id, verzekering_id FROM voertuigen WHERE verzekering_id IS NOT NULL"
    ):
        zorg_koppeling(conn, "voertuig", rij["id"], "verzekering", rij["verzekering_id"], vast=1)
    conn.commit()
    conn.close()


def sniff(data):
    if data.startswith(b"%PDF-"):
        return ".pdf"
    if data.startswith(b"\xff\xd8\xff"):
        return ".jpg"
    if data.startswith(b"\x89PNG\r\n\x1a\n"):
        return ".png"
    if data.startswith((b"GIF87a", b"GIF89a")):
        return ".gif"
    if len(data) >= 12 and data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return ".webp"
    if len(data) >= 12 and data[4:8] == b"ftyp":
        grootte = int.from_bytes(data[0:4], "big")
        einde = grootte if 16 <= grootte <= len(data) else min(len(data), 64)
        venster = data[8:einde]
        merken = {venster[i:i + 4] for i in range(0, max(0, len(venster) - 3), 4)}
        if merken & HEIC_MERKEN:
            return ".heic"
    return None


def toon_naam(naam, ext):
    basis = os.path.basename((naam or "").replace("\\", "/"))
    basis = re.sub(r"[\x00-\x1f]", "", basis).strip().strip(".")
    if not basis or basis in {".", ".."}:
        basis = "bijlage"
    stam = os.path.splitext(basis)[0]
    stam = re.sub(r"[\r\n\"<>:/\\]", "", stam).strip() or "bijlage"
    return (stam + ext)[:120]


def bestand_pad(opslag):
    if not re.fullmatch(r"[0-9a-f]{32}\.[a-z0-9]{2,4}", opslag or ""):
        return None
    basis = os.path.realpath(BESTAND_DIR)
    pad = os.path.realpath(os.path.join(BESTAND_DIR, opslag))
    if os.path.dirname(pad) != basis or not os.path.isfile(pad):
        return None
    return pad


def lees_beperkt(bestand):
    data = bestand.read(MAX_BESTAND + 1)
    if not data:
        return None
    if len(data) > MAX_BESTAND:
        return None
    return data


def bewaar_uploads(conn, eigenaar, eigenaar_id, veld, rol):
    if eigenaar not in EIGENAARS:
        raise ValueError(eigenaar)
    erbij, geweigerd = 0, []
    for bestand in request.files.getlist(veld):
        if not bestand or not bestand.filename:
            continue
        data = lees_beperkt(bestand)
        ext = sniff(data) if data else None
        if ext is None:
            geweigerd.append(bestand.filename)
            continue
        opslag = secrets.token_hex(16) + ext
        with open(os.path.join(BESTAND_DIR, opslag), "wb") as doel:
            doel.write(data)
        _chmod(os.path.join(BESTAND_DIR, opslag), 0o600)
        conn.execute(
            """INSERT INTO bestanden (eigenaar, eigenaar_id, rol, opslag, naam, toegevoegd)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (eigenaar, eigenaar_id, rol, opslag, toon_naam(bestand.filename, ext), vandaag().isoformat()),
        )
        erbij += 1
    return erbij, geweigerd


def verrijk_bestand(rij):
    item = dict(rij)
    ext = os.path.splitext(item["opslag"])[1].lower()
    item["is_plaatje"] = ext in PLAATJES
    item["is_pdf"] = ext == ".pdf"
    return item


def bestanden_van(conn, eigenaar, eigenaar_id):
    rijen = conn.execute(
        "SELECT * FROM bestanden WHERE eigenaar=? AND eigenaar_id=? ORDER BY rol, id",
        (eigenaar, eigenaar_id),
    ).fetchall()
    return [verrijk_bestand(rij) for rij in rijen]


def wis_bestand_rij(conn, rij):
    pad = os.path.join(BESTAND_DIR, rij["opslag"])
    if os.path.isfile(pad):
        os.remove(pad)
    conn.execute("DELETE FROM bestanden WHERE id=?", (rij["id"],))


def wis_van(conn, eigenaar, eigenaar_id):
    for rij in conn.execute(
        "SELECT * FROM bestanden WHERE eigenaar=? AND eigenaar_id=?", (eigenaar, eigenaar_id)
    ):
        wis_bestand_rij(conn, rij)


def backup_bytes():
    fd, db_kopie = tempfile.mkstemp(prefix=".backup-", suffix=".db", dir=DATA_DIR)
    os.close(fd)
    bron = verbind()
    try:
        doel = sqlite3.connect(db_kopie)
        try:
            bron.backup(doel)
            # De hash hoort niet in een zip die je ergens anders bewaart.
            doel.execute("UPDATE account SET wachtwoord=''")
            doel.commit()
        finally:
            doel.close()
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w", compression=zipfile.ZIP_DEFLATED) as archief:
            archief.write(db_kopie, "overzicht.db")
            for naam in sorted(os.listdir(BESTAND_DIR)):
                if not re.fullmatch(r"[0-9a-f]{32}\.[a-z0-9]{2,4}", naam):
                    continue
                pad = os.path.join(BESTAND_DIR, naam)
                if os.path.isfile(pad):
                    archief.write(pad, f"bestanden/{naam}")
        return buf.getvalue()
    finally:
        bron.close()
        try:
            os.remove(db_kopie)
        except OSError:
            pass


def like_patroon(q):
    veilig = q.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
    return f"%{veilig}%"


def zoek_items(conn, q):
    patroon = like_patroon(q)
    uit = []

    def toevoeg(sql, params, soort, titel_fn, tekst_fn, url_fn):
        for rij in conn.execute(sql, params):
            uit.append({
                "soort": soort,
                "titel": titel_fn(rij),
                "tekst": tekst_fn(rij) or "",
                "url": url_fn(rij),
            })

    toevoeg(
        """SELECT * FROM vaste_lasten
           WHERE naam LIKE ? ESCAPE '\\' OR categorie LIKE ? ESCAPE '\\'
              OR rekening LIKE ? ESCAPE '\\' OR notitie LIKE ? ESCAPE '\\'
           ORDER BY naam LIMIT 20""",
        (patroon, patroon, patroon, patroon),
        "Vaste last", lambda r: r["naam"], lambda r: r["categorie"], lambda r: f"/lasten/{r['id']}",
    )
    toevoeg(
        """SELECT * FROM verzekeringen
           WHERE maatschappij LIKE ? ESCAPE '\\' OR plan LIKE ? ESCAPE '\\'
              OR polisnummer LIKE ? ESCAPE '\\' OR dekking LIKE ? ESCAPE '\\'
              OR notitie LIKE ? ESCAPE '\\' OR soort LIKE ? ESCAPE '\\'
           ORDER BY maatschappij LIMIT 20""",
        (patroon,) * 6,
        "Verzekering", verzekering_kaarttitel, lambda r: r["polisnummer"], lambda r: f"/verzekeringen/{r['id']}",
    )
    toevoeg(
        """SELECT * FROM voertuigen
           WHERE merk LIKE ? ESCAPE '\\' OR model LIKE ? ESCAPE '\\'
              OR kenteken LIKE ? ESCAPE '\\' OR notitie LIKE ? ESCAPE '\\'
           ORDER BY merk LIMIT 20""",
        (patroon,) * 4,
        "Voertuig", voertuig_titel, lambda r: r["kenteken"], lambda r: f"/voertuigen/{r['id']}",
    )
    toevoeg(
        """SELECT * FROM bezittingen
           WHERE naam LIKE ? ESCAPE '\\' OR winkel LIKE ? ESCAPE '\\' OR notitie LIKE ? ESCAPE '\\'
           ORDER BY naam LIMIT 20""",
        (patroon,) * 3,
        "Bezit", lambda r: r["naam"], lambda r: r["winkel"], lambda r: f"/bezittingen/{r['id']}",
    )
    toevoeg(
        """SELECT * FROM inkomens
           WHERE werkgever LIKE ? ESCAPE '\\' OR notitie LIKE ? ESCAPE '\\'
           ORDER BY werkgever LIMIT 20""",
        (patroon, patroon),
        "Inkomen", lambda r: r["werkgever"], lambda r: r["notitie"], lambda r: f"/inkomen/{r['id']}",
    )
    toevoeg(
        """SELECT * FROM datums
           WHERE naam LIKE ? ESCAPE '\\' OR soort LIKE ? ESCAPE '\\' OR notitie LIKE ? ESCAPE '\\'
           ORDER BY datum LIMIT 20""",
        (patroon, patroon, patroon),
        "Datum", lambda r: r["naam"], lambda r: bijschrift(DATUM_SOORTEN, r["soort"]), lambda r: f"/datums/{r['id']}",
    )
    toevoeg(
        """SELECT * FROM contacten
           WHERE naam LIKE ? ESCAPE '\\' OR telefoon LIKE ? ESCAPE '\\'
              OR email LIKE ? ESCAPE '\\' OR notitie LIKE ? ESCAPE '\\' OR rol LIKE ? ESCAPE '\\'
           ORDER BY naam LIMIT 20""",
        (patroon,) * 5,
        "Contact", lambda r: r["naam"], lambda r: bijschrift(CONTACT_ROLLEN, r["rol"]), lambda r: f"/contacten/{r['id']}",
    )
    toevoeg(
        """SELECT * FROM documenten
           WHERE titel LIKE ? ESCAPE '\\' OR notitie LIKE ? ESCAPE '\\' OR link LIKE ? ESCAPE '\\'
           ORDER BY titel LIMIT 20""",
        (patroon, patroon, patroon),
        "Document", lambda r: r["titel"], lambda r: r["notitie"], lambda r: f"/documenten/{r['id']}",
    )
    rij = conn.execute(
        """SELECT * FROM noodinfo WHERE id=1 AND (
               bloedgroep LIKE ? ESCAPE '\\' OR medicijnen LIKE ? ESCAPE '\\'
            OR allergieen LIKE ? ESCAPE '\\' OR nood_naam LIKE ? ESCAPE '\\'
            OR nood_telefoon LIKE ? ESCAPE '\\' OR notitie LIKE ? ESCAPE '\\')""",
        (patroon,) * 6,
    ).fetchone()
    if rij:
        uit.append({"soort": "Noodinfo", "titel": "Gezondheid", "tekst": rij["bloedgroep"], "url": "/gezondheid"})
    return uit


def leeg_last():
    return {
        "naam": "", "categorie": "Overig", "bedrag": "", "frequentie": "maand",
        "afschrijfdag": "", "rekening": "", "contract_eind": "",
        "opzegtermijn_dagen": "", "automatisch": False, "notitie": "", "link": "",
    }


def last_formulier(rij):
    return {
        "naam": rij["naam"],
        "categorie": rij["categorie"],
        "bedrag": format_bedrag(rij["bedrag_cent"]),
        "frequentie": rij["frequentie"],
        "afschrijfdag": "" if rij["afschrijfdag"] is None else str(rij["afschrijfdag"]),
        "rekening": rij["rekening"],
        "contract_eind": rij["contract_eind"] or "",
        "opzegtermijn_dagen": "" if rij["opzegtermijn_dagen"] is None else str(rij["opzegtermijn_dagen"]),
        "automatisch": bool(rij["automatisch"]),
        "notitie": rij["notitie"],
        "link": rij["link"],
    }


def lees_last(gekoppeld):
    fouten = []
    ruw = {
        "naam": request.form.get("naam", ""),
        "categorie": request.form.get("categorie", ""),
        "bedrag": request.form.get("bedrag", ""),
        "frequentie": request.form.get("frequentie", ""),
        "afschrijfdag": request.form.get("afschrijfdag", ""),
        "rekening": request.form.get("rekening", ""),
        "contract_eind": request.form.get("contract_eind", ""),
        "opzegtermijn_dagen": request.form.get("opzegtermijn_dagen", ""),
        "notitie": request.form.get("notitie", ""),
        "link": request.form.get("link", ""),
        "automatisch": request.form.get("automatisch") == "ja",
    }
    gegevens = {
        "rekening": tekst(ruw["rekening"], 120),
        "contract_eind": datum_veld(ruw["contract_eind"], "Contract einddatum", fouten),
        "opzegtermijn_dagen": heel_getal(ruw["opzegtermijn_dagen"], "Opzegtermijn", fouten, 0, 3650),
        "automatisch": 1 if ruw["automatisch"] else 0,
        "notitie": tekst(ruw["notitie"], 4000),
        "link": link_veld(ruw["link"], fouten),
        "afschrijfdag": heel_getal(ruw["afschrijfdag"], "Afschrijfdag", fouten, 1, 31),
    }
    if not gekoppeld:
        gegevens["naam"] = tekst(ruw["naam"], 200)
        if not gegevens["naam"]:
            fouten.append("Vul een naam in.")
        gegevens["categorie"] = keuze(ruw["categorie"], LAST_CATEGORIEEN, "categorie", fouten)
        bedrag = naar_centen(ruw["bedrag"], "Bedrag", fouten, leeg_is_nul=True)
        gegevens["bedrag_cent"] = 0 if bedrag is None else bedrag
        gegevens["frequentie"] = keuze(ruw["frequentie"], [code for code, _ in FREQUENTIES], "frequentie", fouten)
    return gegevens, ruw, fouten


def voeg_last_in(conn, gegevens):
    return conn.execute(
        """INSERT INTO vaste_lasten
           (naam, categorie, bedrag_cent, frequentie, afschrijfdag, rekening, contract_eind,
            opzegtermijn_dagen, automatisch, notitie, link, verzekering_id, aangemaakt)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, NULL, ?)""",
        (
            gegevens["naam"], gegevens["categorie"], gegevens["bedrag_cent"], gegevens["frequentie"],
            gegevens["afschrijfdag"], gegevens["rekening"], gegevens["contract_eind"],
            gegevens["opzegtermijn_dagen"], gegevens["automatisch"], gegevens["notitie"],
            gegevens["link"], vandaag().isoformat(),
        ),
    ).lastrowid


def werk_last_bij(conn, last_id, gegevens, gekoppeld):
    if gekoppeld:
        conn.execute(
            """UPDATE vaste_lasten
               SET afschrijfdag=?, rekening=?, contract_eind=?, opzegtermijn_dagen=?,
                   automatisch=?, notitie=?, link=?
               WHERE id=?""",
            (
                gegevens["afschrijfdag"], gegevens["rekening"], gegevens["contract_eind"],
                gegevens["opzegtermijn_dagen"], gegevens["automatisch"], gegevens["notitie"],
                gegevens["link"], last_id,
            ),
        )
        return
    conn.execute(
        """UPDATE vaste_lasten
           SET naam=?, categorie=?, bedrag_cent=?, frequentie=?, afschrijfdag=?, rekening=?,
               contract_eind=?, opzegtermijn_dagen=?, automatisch=?, notitie=?, link=?
           WHERE id=?""",
        (
            gegevens["naam"], gegevens["categorie"], gegevens["bedrag_cent"], gegevens["frequentie"],
            gegevens["afschrijfdag"], gegevens["rekening"], gegevens["contract_eind"],
            gegevens["opzegtermijn_dagen"], gegevens["automatisch"], gegevens["notitie"],
            gegevens["link"], last_id,
        ),
    )


def last_kaart(rij):
    item = dict(rij)
    item["per"] = FREQUENTIE_PER.get(item["frequentie"], "")
    item["gekoppeld"] = item["verzekering_id"] is not None
    item["link_ok"] = toon_link(item["link"])
    if item["gekoppeld"]:
        item["vraag"] = "Deze premie niet meer meetellen bij vaste lasten? De verzekering zelf blijft staan."
    else:
        item["vraag"] = f"{item['naam']} weghalen?"
    return item


@app.route("/")
def index():
    conn = verbind()
    lasten_rijen = [dict(rij) for rij in conn.execute("SELECT * FROM vaste_lasten")]
    maand, jaar = totalen(lasten_rijen)
    netto_rij = conn.execute(
        "SELECT COALESCE(SUM(netto_cent), 0), COUNT(netto_cent) FROM inkomens"
    ).fetchone()
    context = {
        "maand": maand,
        "jaar": jaar,
        "aantal_lasten": len(lasten_rijen),
        "agenda_items": agenda(conn),
        "opzeggen": opzeg_lijst(conn),
        "netto": netto_rij[0] if netto_rij[1] else None,
        "via_opties": optie_wachtwoord_actief(),
        "minimum": WACHTWOORD_MINIMUM,
    }
    conn.close()
    return pagina("dashboard.html", "dashboard", **context)


@app.route("/lasten")
def lasten():
    conn = verbind()
    items = [last_kaart(rij) for rij in conn.execute("SELECT * FROM vaste_lasten ORDER BY categorie, naam")]
    maand, jaar = totalen(items)
    groepen = per_categorie(items)
    hang_chips(conn, items, "last")
    conn.close()
    return pagina("lasten.html", "lasten", items=items, maand=maand, jaar=jaar, groepen=groepen)


@app.route("/lasten/nieuw", methods=["GET", "POST"])
def last_nieuw():
    if request.method == "POST":
        gegevens, ruw, fouten = lees_last(False)
        if fouten:
            return weiger("last_form.html", "lasten", fouten, titel="Nieuwe vaste last",
                          waarden=ruw, gekoppeld=False, verzekering_id=None, **koppel_leeg("last"))
        conn = verbind()
        last_id = voeg_last_in(conn, gegevens)
        conn.commit()
        conn.close()
        melding("Opgeslagen.")
        return redirect(url_for("last_bewerk", last_id=last_id))
    return pagina("last_form.html", "lasten", titel="Nieuwe vaste last",
                  waarden=leeg_last(), gekoppeld=False, verzekering_id=None, **koppel_leeg("last"))


@app.route("/lasten/<int:last_id>", methods=["GET", "POST"])
def last_bewerk(last_id):
    conn = verbind()
    rij = conn.execute("SELECT * FROM vaste_lasten WHERE id=?", (last_id,)).fetchone()
    if rij is None:
        conn.close()
        abort(404)
    gekoppeld = rij["verzekering_id"] is not None
    if request.method == "POST":
        gegevens, ruw, fouten = lees_last(gekoppeld)
        if gekoppeld:
            ruw["naam"] = rij["naam"]
            ruw["categorie"] = rij["categorie"]
            ruw["bedrag"] = format_bedrag(rij["bedrag_cent"])
            ruw["frequentie"] = rij["frequentie"]
        if fouten:
            extra = koppel_extra(conn, "last", last_id)
            conn.close()
            return weiger(
                "last_form.html", "lasten", fouten, titel="Vaste last",
                waarden=ruw, gekoppeld=gekoppeld, verzekering_id=rij["verzekering_id"], **extra,
            )
        werk_last_bij(conn, last_id, gegevens, gekoppeld)
        conn.commit()
        conn.close()
        melding("Opgeslagen.")
        return redirect(url_for("last_bewerk", last_id=last_id))
    waarden = last_formulier(rij)
    verz_id = rij["verzekering_id"]
    extra = koppel_extra(conn, "last", last_id)
    conn.close()
    return pagina("last_form.html", "lasten", titel="Vaste last",
                  waarden=waarden, gekoppeld=gekoppeld, verzekering_id=verz_id, **extra)


@app.route("/lasten/<int:last_id>/verwijder", methods=["POST"])
def last_weg(last_id):
    conn = verbind()
    rij = conn.execute("SELECT * FROM vaste_lasten WHERE id=?", (last_id,)).fetchone()
    if rij is None:
        conn.close()
        abort(404)
    wis_koppelingen(conn, "last", last_id)
    if rij["verzekering_id"]:
        conn.execute("UPDATE verzekeringen SET telt_mee=0 WHERE id=?", (rij["verzekering_id"],))
    conn.execute("DELETE FROM vaste_lasten WHERE id=?", (last_id,))
    conn.commit()
    conn.close()
    melding("Weggehaald.")
    return redirect(url_for("lasten"))


def leeg_verzekering():
    return {
        "soort": "", "maatschappij": "", "plan": "", "eigen_risico": "", "dekking": "",
        "polisnummer": "", "premie": "", "frequentie": "maand", "telt_mee": False,
        "hulpnummer": "", "looptijd_van": "", "looptijd_tot": "", "notitie": "",
    }


def verzekering_formulier(rij):
    return {
        "soort": rij["soort"],
        "maatschappij": rij["maatschappij"],
        "plan": rij["plan"],
        "eigen_risico": rij["eigen_risico"],
        "dekking": rij["dekking"],
        "polisnummer": rij["polisnummer"],
        "premie": format_bedrag(rij["premie_cent"]),
        "frequentie": rij["frequentie"],
        "telt_mee": bool(rij["telt_mee"]),
        "hulpnummer": rij["hulpnummer"],
        "looptijd_van": rij["looptijd_van"] or "",
        "looptijd_tot": rij["looptijd_tot"] or "",
        "notitie": rij["notitie"],
    }


def lees_verzekering():
    fouten = []
    ruw = {
        "soort": request.form.get("soort", ""),
        "maatschappij": request.form.get("maatschappij", ""),
        "plan": request.form.get("plan", ""),
        "eigen_risico": request.form.get("eigen_risico", ""),
        "dekking": request.form.get("dekking", ""),
        "polisnummer": request.form.get("polisnummer", ""),
        "premie": request.form.get("premie", ""),
        "frequentie": request.form.get("frequentie", "") or "maand",
        "telt_mee": request.form.get("telt_mee") == "ja",
        "hulpnummer": request.form.get("hulpnummer", ""),
        "looptijd_van": request.form.get("looptijd_van", ""),
        "looptijd_tot": request.form.get("looptijd_tot", ""),
        "notitie": request.form.get("notitie", ""),
    }
    maatschappij = tekst(ruw["maatschappij"], 160)
    if not maatschappij:
        fouten.append("Vul de maatschappij in.")
    gegevens = {
        "soort": keuze(ruw["soort"], [code for code, _ in VERZEKERING_SOORTEN], "soort", fouten),
        "maatschappij": maatschappij,
        "plan": tekst(ruw["plan"], 160),
        "eigen_risico": tekst(ruw["eigen_risico"], 120),
        "dekking": tekst(ruw["dekking"], 2000),
        "polisnummer": tekst(ruw["polisnummer"], 80),
        "premie_cent": naar_centen(ruw["premie"], "Premie", fouten, leeg_is_nul=False),
        "frequentie": keuze(ruw["frequentie"], [code for code, _ in FREQUENTIES], "frequentie", fouten),
        "telt_mee": 1 if ruw["telt_mee"] else 0,
        "hulpnummer": tekst(ruw["hulpnummer"], 40),
        "looptijd_van": datum_veld(ruw["looptijd_van"], "Looptijd van", fouten),
        "looptijd_tot": datum_veld(ruw["looptijd_tot"], "Looptijd tot", fouten),
        "notitie": tekst(ruw["notitie"], 4000),
    }
    if gegevens["looptijd_van"] and gegevens["looptijd_tot"] and gegevens["looptijd_van"] > gegevens["looptijd_tot"]:
        fouten.append("De looptijd begint na de einddatum.")
    return gegevens, ruw, fouten


def schrijf_verzekering(conn, gegevens, verz_id=None):
    kolommen = (
        gegevens["soort"], gegevens["maatschappij"], gegevens["plan"], gegevens["eigen_risico"],
        gegevens["dekking"], gegevens["polisnummer"], gegevens["premie_cent"], gegevens["frequentie"],
        gegevens["telt_mee"], gegevens["hulpnummer"], gegevens["looptijd_van"], gegevens["looptijd_tot"],
        gegevens["notitie"],
    )
    if verz_id is None:
        return conn.execute(
            """INSERT INTO verzekeringen
               (soort, maatschappij, plan, eigen_risico, dekking, polisnummer, premie_cent,
                frequentie, telt_mee, hulpnummer, looptijd_van, looptijd_tot, notitie, aangemaakt)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (*kolommen, vandaag().isoformat()),
        ).lastrowid
    conn.execute(
        """UPDATE verzekeringen
           SET soort=?, maatschappij=?, plan=?, eigen_risico=?, dekking=?, polisnummer=?,
               premie_cent=?, frequentie=?, telt_mee=?, hulpnummer=?, looptijd_van=?,
               looptijd_tot=?, notitie=?
           WHERE id=?""",
        (*kolommen, verz_id),
    )
    return verz_id


def verzekering_kaart(rij):
    item = dict(rij)
    item["titel"] = verzekering_kaarttitel(rij)
    item["per"] = FREQUENTIE_PER.get(item["frequentie"], "")
    item["tel"] = tel_link(item["hulpnummer"])
    item["vraag"] = f"{item['titel']} weghalen?"
    return item


@app.route("/verzekeringen")
def verzekeringen():
    conn = verbind()
    items = [verzekering_kaart(rij) for rij in conn.execute(
        "SELECT * FROM verzekeringen ORDER BY soort, maatschappij"
    )]
    hang_chips(conn, items, "verzekering")
    conn.close()
    return pagina("verzekeringen.html", "verzekeringen", items=items)


@app.route("/verzekeringen/nieuw", methods=["GET", "POST"])
def verzekering_nieuw():
    if request.method == "POST":
        gegevens, ruw, fouten = lees_verzekering()
        if fouten:
            return weiger("verzekering_form.html", "verzekeringen", fouten, titel="Nieuwe verzekering",
                          waarden=ruw, bestanden=[], **koppel_leeg("verzekering"))
        conn = verbind()
        verz_id = schrijf_verzekering(conn, gegevens)
        erbij_polis, geweigerd_polis = bewaar_uploads(conn, "verzekering", verz_id, "polis", "polis")
        erbij_rest, geweigerd_rest = bewaar_uploads(conn, "verzekering", verz_id, "bestanden", "overig")
        sync_last_van_verzekering(conn, verz_id)
        conn.commit()
        conn.close()
        meld_bestanden(erbij_polis + erbij_rest, geweigerd_polis + geweigerd_rest)
        return redirect(url_for("verzekering_bewerk", verzekering_id=verz_id))
    return pagina("verzekering_form.html", "verzekeringen", titel="Nieuwe verzekering",
                  waarden=leeg_verzekering(), bestanden=[], **koppel_leeg("verzekering"))


@app.route("/verzekeringen/<int:verzekering_id>", methods=["GET", "POST"])
def verzekering_bewerk(verzekering_id):
    conn = verbind()
    rij = conn.execute("SELECT * FROM verzekeringen WHERE id=?", (verzekering_id,)).fetchone()
    if rij is None:
        conn.close()
        abort(404)
    if request.method == "POST":
        gegevens, ruw, fouten = lees_verzekering()
        if fouten:
            bestanden = bestanden_van(conn, "verzekering", verzekering_id)
            extra = koppel_extra(conn, "verzekering", verzekering_id)
            conn.close()
            return weiger("verzekering_form.html", "verzekeringen", fouten, titel="Verzekering",
                          waarden=ruw, bestanden=bestanden, **extra)
        schrijf_verzekering(conn, gegevens, verzekering_id)
        erbij_polis, geweigerd_polis = bewaar_uploads(conn, "verzekering", verzekering_id, "polis", "polis")
        erbij_rest, geweigerd_rest = bewaar_uploads(conn, "verzekering", verzekering_id, "bestanden", "overig")
        sync_last_van_verzekering(conn, verzekering_id)
        conn.commit()
        conn.close()
        meld_bestanden(erbij_polis + erbij_rest, geweigerd_polis + geweigerd_rest)
        return redirect(url_for("verzekering_bewerk", verzekering_id=verzekering_id))
    waarden = verzekering_formulier(rij)
    bestanden = bestanden_van(conn, "verzekering", verzekering_id)
    extra = koppel_extra(conn, "verzekering", verzekering_id)
    conn.close()
    return pagina("verzekering_form.html", "verzekeringen", titel="Verzekering",
                  waarden=waarden, bestanden=bestanden, **extra)


@app.route("/verzekeringen/<int:verzekering_id>/verwijder", methods=["POST"])
def verzekering_weg(verzekering_id):
    return _verwijder("verzekeringen", verzekering_id, "verzekering", "verzekeringen")


def verzekering_keuze(conn, waarde, fouten):
    ruw = (waarde or "").strip()
    if not ruw:
        return None
    if not re.fullmatch(r"\d+", ruw):
        fouten.append("Kies een verzekering uit de lijst.")
        return None
    id_ = int(ruw)
    if conn.execute("SELECT id FROM verzekeringen WHERE id=?", (id_,)).fetchone() is None:
        fouten.append("Die verzekering bestaat niet.")
        return None
    return id_


def verzekering_opties(conn):
    return [
        {"id": rij["id"], "label": verzekering_kaarttitel(rij)}
        for rij in conn.execute("SELECT * FROM verzekeringen ORDER BY maatschappij, plan")
    ]


def leeg_voertuig():
    return {
        "soort": "", "merk": "", "model": "", "kenteken": "", "bouwjaar": "",
        "apk_tot": "", "verzekering_id": "", "bandenmaat": "", "notitie": "",
    }


def voertuig_formulier(rij):
    return {
        "soort": rij["soort"],
        "merk": rij["merk"],
        "model": rij["model"],
        "kenteken": rij["kenteken"],
        "bouwjaar": "" if rij["bouwjaar"] is None else str(rij["bouwjaar"]),
        "apk_tot": rij["apk_tot"] or "",
        "verzekering_id": "" if rij["verzekering_id"] is None else str(rij["verzekering_id"]),
        "bandenmaat": rij["bandenmaat"],
        "notitie": rij["notitie"],
    }


def lees_voertuig(conn):
    fouten = []
    ruw = {
        "soort": request.form.get("soort", ""),
        "merk": request.form.get("merk", ""),
        "model": request.form.get("model", ""),
        "kenteken": request.form.get("kenteken", ""),
        "bouwjaar": request.form.get("bouwjaar", ""),
        "apk_tot": request.form.get("apk_tot", ""),
        "verzekering_id": request.form.get("verzekering_id", ""),
        "bandenmaat": request.form.get("bandenmaat", ""),
        "notitie": request.form.get("notitie", ""),
    }
    kenteken, kenteken_fout = net_kenteken(ruw["kenteken"])
    if kenteken_fout:
        fouten.append(kenteken_fout)
    else:
        ruw["kenteken"] = kenteken
    merk = tekst(ruw["merk"], 80)
    if not merk:
        fouten.append("Vul het merk in.")
    gegevens = {
        "soort": keuze(ruw["soort"], [code for code, _ in VOERTUIG_SOORTEN], "soort", fouten),
        "merk": merk,
        "model": tekst(ruw["model"], 80),
        "kenteken": kenteken if not kenteken_fout else "",
        "bouwjaar": heel_getal(ruw["bouwjaar"], "Bouwjaar", fouten, 1900, 2100),
        "apk_tot": datum_veld(ruw["apk_tot"], "APK-vervaldatum", fouten),
        "verzekering_id": verzekering_keuze(conn, ruw["verzekering_id"], fouten),
        "bandenmaat": tekst(ruw["bandenmaat"], 40),
        "notitie": tekst(ruw["notitie"], 4000),
    }
    return gegevens, ruw, fouten


def schrijf_voertuig(conn, gegevens, voertuig_id=None):
    kolommen = (
        gegevens["soort"], gegevens["merk"], gegevens["model"], gegevens["kenteken"],
        gegevens["bouwjaar"], gegevens["apk_tot"], gegevens["verzekering_id"],
        gegevens["bandenmaat"], gegevens["notitie"],
    )
    if voertuig_id is None:
        return conn.execute(
            """INSERT INTO voertuigen
               (soort, merk, model, kenteken, bouwjaar, apk_tot, verzekering_id,
                bandenmaat, notitie, aangemaakt)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (*kolommen, vandaag().isoformat()),
        ).lastrowid
    conn.execute(
        """UPDATE voertuigen
           SET soort=?, merk=?, model=?, kenteken=?, bouwjaar=?, apk_tot=?,
               verzekering_id=?, bandenmaat=?, notitie=?
           WHERE id=?""",
        (*kolommen, voertuig_id),
    )
    return voertuig_id


@app.route("/voertuigen")
def voertuigen():
    conn = verbind()
    namen = {rij["id"]: verzekering_kaarttitel(rij) for rij in conn.execute("SELECT * FROM verzekeringen")}
    items = []
    for rij in conn.execute("SELECT * FROM voertuigen ORDER BY soort, merk, model"):
        item = dict(rij)
        item["titel"] = voertuig_titel(rij)
        item["soort_label"] = bijschrift(VOERTUIG_SOORTEN, rij["soort"])
        item["verzekering_naam"] = namen.get(rij["verzekering_id"], "")
        item["vraag"] = f"{item['titel']} weghalen?"
        items.append(item)
    hang_chips(conn, items, "voertuig")
    conn.close()
    return pagina("voertuigen.html", "voertuigen", items=items)


@app.route("/voertuigen/nieuw", methods=["GET", "POST"])
def voertuig_nieuw():
    conn = verbind()
    opties = verzekering_opties(conn)
    if request.method == "POST":
        gegevens, ruw, fouten = lees_voertuig(conn)
        if fouten:
            conn.close()
            return weiger("voertuig_form.html", "voertuigen", fouten, titel="Nieuw voertuig",
                          waarden=ruw, verzekeringen=opties, bestanden=[], **koppel_leeg("voertuig"))
        voertuig_id = schrijf_voertuig(conn, gegevens)
        sync_voertuig_verzekering(conn, voertuig_id, None, gegevens["verzekering_id"])
        erbij, geweigerd = bewaar_uploads(conn, "voertuig", voertuig_id, "bestanden", "overig")
        conn.commit()
        conn.close()
        meld_bestanden(erbij, geweigerd)
        return redirect(url_for("voertuig_bewerk", voertuig_id=voertuig_id))
    conn.close()
    return pagina("voertuig_form.html", "voertuigen", titel="Nieuw voertuig",
                  waarden=leeg_voertuig(), verzekeringen=opties, bestanden=[], **koppel_leeg("voertuig"))


@app.route("/voertuigen/<int:voertuig_id>", methods=["GET", "POST"])
def voertuig_bewerk(voertuig_id):
    conn = verbind()
    rij = conn.execute("SELECT * FROM voertuigen WHERE id=?", (voertuig_id,)).fetchone()
    if rij is None:
        conn.close()
        abort(404)
    opties = verzekering_opties(conn)
    if request.method == "POST":
        gegevens, ruw, fouten = lees_voertuig(conn)
        if fouten:
            bestanden = bestanden_van(conn, "voertuig", voertuig_id)
            extra = koppel_extra(conn, "voertuig", voertuig_id)
            conn.close()
            return weiger("voertuig_form.html", "voertuigen", fouten, titel="Voertuig",
                          waarden=ruw, verzekeringen=opties, bestanden=bestanden, **extra)
        oud_verzekering = rij["verzekering_id"]
        schrijf_voertuig(conn, gegevens, voertuig_id)
        sync_voertuig_verzekering(conn, voertuig_id, oud_verzekering, gegevens["verzekering_id"])
        erbij, geweigerd = bewaar_uploads(conn, "voertuig", voertuig_id, "bestanden", "overig")
        conn.commit()
        conn.close()
        meld_bestanden(erbij, geweigerd)
        return redirect(url_for("voertuig_bewerk", voertuig_id=voertuig_id))
    waarden = voertuig_formulier(rij)
    bestanden = bestanden_van(conn, "voertuig", voertuig_id)
    extra = koppel_extra(conn, "voertuig", voertuig_id)
    conn.close()
    return pagina("voertuig_form.html", "voertuigen", titel="Voertuig",
                  waarden=waarden, verzekeringen=opties, bestanden=bestanden, **extra)


@app.route("/voertuigen/<int:voertuig_id>/verwijder", methods=["POST"])
def voertuig_weg(voertuig_id):
    return _verwijder("voertuigen", voertuig_id, "voertuig", "voertuigen")


def leeg_bezit():
    return {
        "naam": "", "aankoop": "", "winkel": "", "prijs": "",
        "garantie_maanden": "", "garantie_tot": "", "notitie": "",
    }


def bezit_formulier(rij):
    return {
        "naam": rij["naam"],
        "aankoop": rij["aankoop"] or "",
        "winkel": rij["winkel"],
        "prijs": format_bedrag(rij["prijs_cent"]),
        "garantie_maanden": "" if rij["garantie_maanden"] is None else str(rij["garantie_maanden"]),
        "garantie_tot": rij["garantie_tot"] or "",
        "notitie": rij["notitie"],
    }


def lees_bezit():
    fouten = []
    ruw = {
        "naam": request.form.get("naam", ""),
        "aankoop": request.form.get("aankoop", ""),
        "winkel": request.form.get("winkel", ""),
        "prijs": request.form.get("prijs", ""),
        "garantie_maanden": request.form.get("garantie_maanden", ""),
        "garantie_tot": request.form.get("garantie_tot", ""),
        "notitie": request.form.get("notitie", ""),
    }
    naam = tekst(ruw["naam"], 200)
    if not naam:
        fouten.append("Vul een naam in.")
    gegevens = {
        "naam": naam,
        "aankoop": datum_veld(ruw["aankoop"], "Aankoopdatum", fouten),
        "winkel": tekst(ruw["winkel"], 160),
        "prijs_cent": naar_centen(ruw["prijs"], "Prijs", fouten, leeg_is_nul=False),
        "garantie_maanden": heel_getal(ruw["garantie_maanden"], "Garantie in maanden", fouten, 0, 600),
        "garantie_tot": datum_veld(ruw["garantie_tot"], "Garantie tot", fouten),
        "notitie": tekst(ruw["notitie"], 4000),
    }
    if (gegevens["garantie_maanden"] is not None and not gegevens["aankoop"] and not gegevens["garantie_tot"]):
        fouten.append("Vul een aankoopdatum of een garantie-einddatum in.")
    return gegevens, ruw, fouten


def schrijf_bezit(conn, gegevens, bezit_id=None):
    kolommen = (
        gegevens["naam"], gegevens["aankoop"], gegevens["winkel"], gegevens["prijs_cent"],
        gegevens["garantie_maanden"], gegevens["garantie_tot"], gegevens["notitie"],
    )
    if bezit_id is None:
        return conn.execute(
            """INSERT INTO bezittingen
               (naam, aankoop, winkel, prijs_cent, garantie_maanden, garantie_tot, notitie, aangemaakt)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            (*kolommen, vandaag().isoformat()),
        ).lastrowid
    conn.execute(
        """UPDATE bezittingen
           SET naam=?, aankoop=?, winkel=?, prijs_cent=?, garantie_maanden=?, garantie_tot=?, notitie=?
           WHERE id=?""",
        (*kolommen, bezit_id),
    )
    return bezit_id


def bezit_kaart(rij, op):
    item = dict(rij)
    item["badge"] = garantie_badge(item["aankoop"], item["garantie_maanden"], item["garantie_tot"], op)
    item["vraag"] = f"{item['naam']} weghalen?"
    return item


def sorteer_bezit(items):
    verlopen = [item for item in items if item["badge"] and item["badge"]["soort"] == "verlopen"]
    lopend = [item for item in items if item["badge"] and item["badge"]["soort"] != "verlopen"]
    geen = [item for item in items if not item["badge"]]
    verlopen.sort(key=lambda item: item["badge"]["eind"], reverse=True)
    lopend.sort(key=lambda item: item["badge"]["eind"])
    geen.sort(key=lambda item: item["naam"].lower())
    return verlopen + lopend + geen


@app.route("/bezittingen")
def bezittingen():
    conn = verbind()
    op = vandaag()
    items = sorteer_bezit([
        bezit_kaart(rij, op) for rij in conn.execute("SELECT * FROM bezittingen")
    ])
    hang_chips(conn, items, "bezit")
    conn.close()
    return pagina("bezittingen.html", "bezittingen", items=items)


@app.route("/bezittingen/nieuw", methods=["GET", "POST"])
def bezit_nieuw():
    if request.method == "POST":
        gegevens, ruw, fouten = lees_bezit()
        if fouten:
            return weiger("bezit_form.html", "bezittingen", fouten, titel="Nieuw bezit",
                          waarden=ruw, bestanden=[], badge=None, **koppel_leeg("bezit"))
        conn = verbind()
        bezit_id = schrijf_bezit(conn, gegevens)
        erbij_bon, geweigerd_bon = bewaar_uploads(conn, "bezit", bezit_id, "bon", "bon")
        erbij_rest, geweigerd_rest = bewaar_uploads(conn, "bezit", bezit_id, "bestanden", "overig")
        conn.commit()
        conn.close()
        meld_bestanden(erbij_bon + erbij_rest, geweigerd_bon + geweigerd_rest)
        return redirect(url_for("bezit_bewerk", bezit_id=bezit_id))
    return pagina("bezit_form.html", "bezittingen", titel="Nieuw bezit",
                  waarden=leeg_bezit(), bestanden=[], badge=None, **koppel_leeg("bezit"))


@app.route("/bezittingen/<int:bezit_id>", methods=["GET", "POST"])
def bezit_bewerk(bezit_id):
    conn = verbind()
    rij = conn.execute("SELECT * FROM bezittingen WHERE id=?", (bezit_id,)).fetchone()
    if rij is None:
        conn.close()
        abort(404)
    if request.method == "POST":
        gegevens, ruw, fouten = lees_bezit()
        if fouten:
            bestanden = bestanden_van(conn, "bezit", bezit_id)
            badge = garantie_badge(rij["aankoop"], rij["garantie_maanden"], rij["garantie_tot"])
            extra = koppel_extra(conn, "bezit", bezit_id)
            conn.close()
            return weiger("bezit_form.html", "bezittingen", fouten, titel="Bezit",
                          waarden=ruw, bestanden=bestanden, badge=badge, **extra)
        schrijf_bezit(conn, gegevens, bezit_id)
        erbij_bon, geweigerd_bon = bewaar_uploads(conn, "bezit", bezit_id, "bon", "bon")
        erbij_rest, geweigerd_rest = bewaar_uploads(conn, "bezit", bezit_id, "bestanden", "overig")
        conn.commit()
        conn.close()
        meld_bestanden(erbij_bon + erbij_rest, geweigerd_bon + geweigerd_rest)
        return redirect(url_for("bezit_bewerk", bezit_id=bezit_id))
    waarden = bezit_formulier(rij)
    bestanden = bestanden_van(conn, "bezit", bezit_id)
    badge = garantie_badge(rij["aankoop"], rij["garantie_maanden"], rij["garantie_tot"])
    extra = koppel_extra(conn, "bezit", bezit_id)
    conn.close()
    return pagina("bezit_form.html", "bezittingen", titel="Bezit",
                  waarden=waarden, bestanden=bestanden, badge=badge, **extra)


@app.route("/bezittingen/<int:bezit_id>/verwijder", methods=["POST"])
def bezit_weg(bezit_id):
    return _verwijder("bezittingen", bezit_id, "bezit", "bezittingen")


def leeg_inkomen():
    return {"werkgever": "", "uren": "", "netto": "", "betaaldag": "", "notitie": ""}


def inkomen_formulier(rij):
    return {
        "werkgever": rij["werkgever"],
        "uren": format_uren(rij["uren"]),
        "netto": format_bedrag(rij["netto_cent"]),
        "betaaldag": "" if rij["betaaldag"] is None else str(rij["betaaldag"]),
        "notitie": rij["notitie"],
    }


def lees_inkomen():
    fouten = []
    ruw = {
        "werkgever": request.form.get("werkgever", ""),
        "uren": request.form.get("uren", ""),
        "netto": request.form.get("netto", ""),
        "betaaldag": request.form.get("betaaldag", ""),
        "notitie": request.form.get("notitie", ""),
    }
    werkgever = tekst(ruw["werkgever"], 160)
    if not werkgever:
        fouten.append("Vul de werkgever in.")
    gegevens = {
        "werkgever": werkgever,
        "uren": naar_uren(ruw["uren"], fouten),
        "netto_cent": naar_centen(ruw["netto"], "Netto per maand", fouten, leeg_is_nul=False),
        "betaaldag": heel_getal(ruw["betaaldag"], "Betaaldag", fouten, 1, 31),
        "notitie": tekst(ruw["notitie"], 4000),
    }
    return gegevens, ruw, fouten


def schrijf_inkomen(conn, gegevens, inkomen_id=None):
    kolommen = (
        gegevens["werkgever"], gegevens["uren"], gegevens["netto_cent"],
        gegevens["betaaldag"], gegevens["notitie"],
    )
    if inkomen_id is None:
        return conn.execute(
            """INSERT INTO inkomens (werkgever, uren, netto_cent, betaaldag, notitie, aangemaakt)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (*kolommen, vandaag().isoformat()),
        ).lastrowid
    conn.execute(
        """UPDATE inkomens SET werkgever=?, uren=?, netto_cent=?, betaaldag=?, notitie=? WHERE id=?""",
        (*kolommen, inkomen_id),
    )
    return inkomen_id


@app.route("/inkomen")
def inkomen():
    conn = verbind()
    items = []
    for rij in conn.execute("SELECT * FROM inkomens ORDER BY werkgever"):
        item = dict(rij)
        item["vraag"] = f"{item['werkgever']} weghalen?"
        items.append(item)
    hang_chips(conn, items, "inkomen")
    netto_waarden = [item["netto_cent"] for item in items if item["netto_cent"] is not None]
    uren = sum(item["uren"] or 0 for item in items)
    conn.close()
    return pagina(
        "inkomen.html", "inkomen", items=items,
        netto=sum(netto_waarden) if netto_waarden else None,
        uren=uren if uren else None,
    )


@app.route("/inkomen/nieuw", methods=["GET", "POST"])
def inkomen_nieuw():
    if request.method == "POST":
        gegevens, ruw, fouten = lees_inkomen()
        if fouten:
            return weiger("inkomen_form.html", "inkomen", fouten, titel="Nieuwe werkgever",
                          waarden=ruw, **koppel_leeg("inkomen"))
        conn = verbind()
        inkomen_id = schrijf_inkomen(conn, gegevens)
        conn.commit()
        conn.close()
        melding("Opgeslagen.")
        return redirect(url_for("inkomen_bewerk", inkomen_id=inkomen_id))
    return pagina("inkomen_form.html", "inkomen", titel="Nieuwe werkgever",
                  waarden=leeg_inkomen(), **koppel_leeg("inkomen"))


@app.route("/inkomen/<int:inkomen_id>", methods=["GET", "POST"])
def inkomen_bewerk(inkomen_id):
    conn = verbind()
    rij = conn.execute("SELECT * FROM inkomens WHERE id=?", (inkomen_id,)).fetchone()
    if rij is None:
        conn.close()
        abort(404)
    if request.method == "POST":
        gegevens, ruw, fouten = lees_inkomen()
        if fouten:
            extra = koppel_extra(conn, "inkomen", inkomen_id)
            conn.close()
            return weiger("inkomen_form.html", "inkomen", fouten, titel="Werkgever", waarden=ruw, **extra)
        schrijf_inkomen(conn, gegevens, inkomen_id)
        conn.commit()
        conn.close()
        melding("Opgeslagen.")
        return redirect(url_for("inkomen_bewerk", inkomen_id=inkomen_id))
    waarden = inkomen_formulier(rij)
    extra = koppel_extra(conn, "inkomen", inkomen_id)
    conn.close()
    return pagina("inkomen_form.html", "inkomen", titel="Werkgever", waarden=waarden, **extra)


@app.route("/inkomen/<int:inkomen_id>/verwijder", methods=["POST"])
def inkomen_weg(inkomen_id):
    return _verwijder("inkomens", inkomen_id, None, "inkomen")


def leeg_datum():
    return {"soort": "", "naam": "", "datum": "", "notitie": ""}


def lees_datum():
    fouten = []
    ruw = {
        "soort": request.form.get("soort", ""),
        "naam": request.form.get("naam", ""),
        "datum": request.form.get("datum", ""),
        "notitie": request.form.get("notitie", ""),
    }
    naam = tekst(ruw["naam"], 200)
    if not naam:
        fouten.append("Vul een naam in.")
    gegevens = {
        "soort": keuze(ruw["soort"], [code for code, _ in DATUM_SOORTEN], "soort", fouten),
        "naam": naam,
        "datum": datum_veld(ruw["datum"], "Datum", fouten, verplicht=True),
        "notitie": tekst(ruw["notitie"], 4000),
    }
    return gegevens, ruw, fouten


@app.route("/datums")
def datums():
    conn = verbind()
    items = []
    for rij in conn.execute("SELECT * FROM datums ORDER BY datum, naam"):
        item = dict(rij)
        item["soort_label"] = bijschrift(DATUM_SOORTEN, rij["soort"])
        item["vraag"] = f"{item['naam']} weghalen?"
        items.append(item)
    hang_chips(conn, items, "datum")
    conn.close()
    return pagina("datums.html", "datums", items=items)


@app.route("/datums/nieuw", methods=["GET", "POST"])
def datum_nieuw():
    if request.method == "POST":
        gegevens, ruw, fouten = lees_datum()
        if fouten:
            return weiger("datum_form.html", "datums", fouten, titel="Nieuwe datum",
                          waarden=ruw, **koppel_leeg("datum"))
        conn = verbind()
        datum_id = conn.execute(
            "INSERT INTO datums (soort, naam, datum, notitie, aangemaakt) VALUES (?, ?, ?, ?, ?)",
            (gegevens["soort"], gegevens["naam"], gegevens["datum"], gegevens["notitie"], vandaag().isoformat()),
        ).lastrowid
        conn.commit()
        conn.close()
        melding("Opgeslagen.")
        return redirect(url_for("datum_bewerk", datum_id=datum_id))
    return pagina("datum_form.html", "datums", titel="Nieuwe datum",
                  waarden=leeg_datum(), **koppel_leeg("datum"))


@app.route("/datums/<int:datum_id>", methods=["GET", "POST"])
def datum_bewerk(datum_id):
    conn = verbind()
    rij = conn.execute("SELECT * FROM datums WHERE id=?", (datum_id,)).fetchone()
    if rij is None:
        conn.close()
        abort(404)
    if request.method == "POST":
        gegevens, ruw, fouten = lees_datum()
        if fouten:
            extra = koppel_extra(conn, "datum", datum_id)
            conn.close()
            return weiger("datum_form.html", "datums", fouten, titel="Datum", waarden=ruw, **extra)
        conn.execute(
            "UPDATE datums SET soort=?, naam=?, datum=?, notitie=? WHERE id=?",
            (gegevens["soort"], gegevens["naam"], gegevens["datum"], gegevens["notitie"], datum_id),
        )
        conn.commit()
        conn.close()
        melding("Opgeslagen.")
        return redirect(url_for("datum_bewerk", datum_id=datum_id))
    waarden = {"soort": rij["soort"], "naam": rij["naam"], "datum": rij["datum"], "notitie": rij["notitie"]}
    extra = koppel_extra(conn, "datum", datum_id)
    conn.close()
    return pagina("datum_form.html", "datums", titel="Datum", waarden=waarden, **extra)


@app.route("/datums/<int:datum_id>/verwijder", methods=["POST"])
def datum_weg(datum_id):
    return _verwijder("datums", datum_id, None, "datums")


def leeg_contact():
    return {"naam": "", "rol": "overig", "telefoon": "", "email": "", "notitie": ""}


def lees_contact():
    fouten = []
    ruw = {
        "naam": request.form.get("naam", ""),
        "rol": request.form.get("rol", "") or "overig",
        "telefoon": request.form.get("telefoon", ""),
        "email": request.form.get("email", ""),
        "notitie": request.form.get("notitie", ""),
    }
    naam = tekst(ruw["naam"], 160)
    if not naam:
        fouten.append("Vul een naam in.")
    gegevens = {
        "naam": naam,
        "rol": keuze(ruw["rol"], [code for code, _ in CONTACT_ROLLEN], "rol", fouten),
        "telefoon": tekst(ruw["telefoon"], 40),
        "email": email_veld(ruw["email"], fouten),
        "notitie": tekst(ruw["notitie"], 4000),
    }
    return gegevens, ruw, fouten


@app.route("/contacten")
def contacten():
    conn = verbind()
    items = []
    for rij in conn.execute("SELECT * FROM contacten ORDER BY rol, naam"):
        item = dict(rij)
        item["rol_label"] = bijschrift(CONTACT_ROLLEN, rij["rol"])
        item["tel"] = tel_link(rij["telefoon"])
        item["mail"] = mail_link(rij["email"])
        item["vraag"] = f"{item['naam']} weghalen?"
        items.append(item)
    hang_chips(conn, items, "contact")
    conn.close()
    return pagina("contacten.html", "contacten", items=items)


@app.route("/contacten/nieuw", methods=["GET", "POST"])
def contact_nieuw():
    if request.method == "POST":
        gegevens, ruw, fouten = lees_contact()
        if fouten:
            return weiger("contact_form.html", "contacten", fouten, titel="Nieuw contact",
                          waarden=ruw, **koppel_leeg("contact"))
        conn = verbind()
        contact_id = conn.execute(
            """INSERT INTO contacten (naam, rol, telefoon, email, notitie, aangemaakt)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (gegevens["naam"], gegevens["rol"], gegevens["telefoon"], gegevens["email"],
             gegevens["notitie"], vandaag().isoformat()),
        ).lastrowid
        conn.commit()
        conn.close()
        melding("Opgeslagen.")
        return redirect(url_for("contact_bewerk", contact_id=contact_id))
    return pagina("contact_form.html", "contacten", titel="Nieuw contact",
                  waarden=leeg_contact(), **koppel_leeg("contact"))


@app.route("/contacten/<int:contact_id>", methods=["GET", "POST"])
def contact_bewerk(contact_id):
    conn = verbind()
    rij = conn.execute("SELECT * FROM contacten WHERE id=?", (contact_id,)).fetchone()
    if rij is None:
        conn.close()
        abort(404)
    if request.method == "POST":
        gegevens, ruw, fouten = lees_contact()
        if fouten:
            extra = koppel_extra(conn, "contact", contact_id)
            conn.close()
            return weiger("contact_form.html", "contacten", fouten, titel="Contact", waarden=ruw, **extra)
        conn.execute(
            "UPDATE contacten SET naam=?, rol=?, telefoon=?, email=?, notitie=? WHERE id=?",
            (gegevens["naam"], gegevens["rol"], gegevens["telefoon"], gegevens["email"],
             gegevens["notitie"], contact_id),
        )
        conn.commit()
        conn.close()
        melding("Opgeslagen.")
        return redirect(url_for("contact_bewerk", contact_id=contact_id))
    waarden = {
        "naam": rij["naam"], "rol": rij["rol"], "telefoon": rij["telefoon"],
        "email": rij["email"], "notitie": rij["notitie"],
    }
    extra = koppel_extra(conn, "contact", contact_id)
    conn.close()
    return pagina("contact_form.html", "contacten", titel="Contact", waarden=waarden, **extra)


@app.route("/contacten/<int:contact_id>/verwijder", methods=["POST"])
def contact_weg(contact_id):
    return _verwijder("contacten", contact_id, None, "contacten")


def leeg_document():
    return {"titel": "", "link": "", "verval": "", "notitie": ""}


def lees_document():
    fouten = []
    ruw = {
        "titel": request.form.get("titel", ""),
        "link": request.form.get("link", ""),
        "verval": request.form.get("verval", ""),
        "notitie": request.form.get("notitie", ""),
    }
    titel = tekst(ruw["titel"], 200)
    if not titel:
        fouten.append("Vul een titel in.")
    gegevens = {
        "titel": titel,
        "link": link_veld(ruw["link"], fouten),
        "verval": datum_veld(ruw["verval"], "Vervaldatum", fouten),
        "notitie": tekst(ruw["notitie"], 4000),
    }
    return gegevens, ruw, fouten


@app.route("/documenten")
def documenten():
    conn = verbind()
    items = []
    for rij in conn.execute("SELECT * FROM documenten ORDER BY titel"):
        item = dict(rij)
        item["link_ok"] = toon_link(rij["link"])
        item["vraag"] = f"{item['titel']} weghalen?"
        items.append(item)
    hang_chips(conn, items, "document")
    conn.close()
    return pagina("documenten.html", "documenten", items=items)


@app.route("/documenten/nieuw", methods=["GET", "POST"])
def document_nieuw():
    if request.method == "POST":
        gegevens, ruw, fouten = lees_document()
        if fouten:
            return weiger("document_form.html", "documenten", fouten, titel="Nieuw document",
                          waarden=ruw, bestanden=[], **koppel_leeg("document"))
        conn = verbind()
        document_id = conn.execute(
            "INSERT INTO documenten (titel, link, verval, notitie, aangemaakt) VALUES (?, ?, ?, ?, ?)",
            (gegevens["titel"], gegevens["link"], gegevens["verval"], gegevens["notitie"], vandaag().isoformat()),
        ).lastrowid
        erbij, geweigerd = bewaar_uploads(conn, "document", document_id, "bestanden", "overig")
        conn.commit()
        conn.close()
        meld_bestanden(erbij, geweigerd)
        return redirect(url_for("document_bewerk", document_id=document_id))
    return pagina("document_form.html", "documenten", titel="Nieuw document",
                  waarden=leeg_document(), bestanden=[], **koppel_leeg("document"))


@app.route("/documenten/<int:document_id>", methods=["GET", "POST"])
def document_bewerk(document_id):
    conn = verbind()
    rij = conn.execute("SELECT * FROM documenten WHERE id=?", (document_id,)).fetchone()
    if rij is None:
        conn.close()
        abort(404)
    if request.method == "POST":
        gegevens, ruw, fouten = lees_document()
        if fouten:
            bestanden = bestanden_van(conn, "document", document_id)
            extra = koppel_extra(conn, "document", document_id)
            conn.close()
            return weiger("document_form.html", "documenten", fouten, titel="Document",
                          waarden=ruw, bestanden=bestanden, **extra)
        conn.execute(
            "UPDATE documenten SET titel=?, link=?, verval=?, notitie=? WHERE id=?",
            (gegevens["titel"], gegevens["link"], gegevens["verval"], gegevens["notitie"], document_id),
        )
        erbij, geweigerd = bewaar_uploads(conn, "document", document_id, "bestanden", "overig")
        conn.commit()
        conn.close()
        meld_bestanden(erbij, geweigerd)
        return redirect(url_for("document_bewerk", document_id=document_id))
    waarden = {
        "titel": rij["titel"], "link": rij["link"], "verval": rij["verval"] or "", "notitie": rij["notitie"],
    }
    bestanden = bestanden_van(conn, "document", document_id)
    extra = koppel_extra(conn, "document", document_id)
    conn.close()
    return pagina("document_form.html", "documenten", titel="Document",
                  waarden=waarden, bestanden=bestanden, **extra)


@app.route("/documenten/<int:document_id>/verwijder", methods=["POST"])
def document_weg(document_id):
    return _verwijder("documenten", document_id, "document", "documenten")


def leeg_nood():
    return {
        "bloedgroep": "", "medicijnen": "", "allergieen": "", "nood_naam": "",
        "nood_telefoon": "", "nood_relatie": "", "notitie": "",
    }


def lees_nood():
    fouten = []
    ruw = {
        "bloedgroep": request.form.get("bloedgroep", ""),
        "medicijnen": request.form.get("medicijnen", ""),
        "allergieen": request.form.get("allergieen", ""),
        "nood_naam": request.form.get("nood_naam", ""),
        "nood_telefoon": request.form.get("nood_telefoon", ""),
        "nood_relatie": request.form.get("nood_relatie", ""),
        "notitie": request.form.get("notitie", ""),
    }
    if ruw["bloedgroep"] not in BLOEDGROEPEN:
        fouten.append("Kies een bloedgroep uit de lijst.")
        ruw["bloedgroep"] = ""
    gegevens = {
        "bloedgroep": ruw["bloedgroep"],
        "medicijnen": tekst(ruw["medicijnen"], 4000),
        "allergieen": tekst(ruw["allergieen"], 4000),
        "nood_naam": tekst(ruw["nood_naam"], 160),
        "nood_telefoon": tekst(ruw["nood_telefoon"], 40),
        "nood_relatie": tekst(ruw["nood_relatie"], 80),
        "notitie": tekst(ruw["notitie"], 4000),
    }
    return gegevens, ruw, fouten


@app.route("/gezondheid", methods=["GET", "POST"])
def gezondheid():
    conn = verbind()
    if request.method == "POST":
        gegevens, ruw, fouten = lees_nood()
        if fouten:
            extra = koppel_extra(conn, "gezondheid", 1)
            conn.close()
            return weiger("gezondheid.html", "gezondheid", fouten, waarden=ruw, tel="", **extra)
        bestaat = conn.execute("SELECT id FROM noodinfo WHERE id=1").fetchone()
        kolommen = (
            gegevens["bloedgroep"], gegevens["medicijnen"], gegevens["allergieen"],
            gegevens["nood_naam"], gegevens["nood_telefoon"], gegevens["nood_relatie"], gegevens["notitie"],
        )
        if bestaat:
            conn.execute(
                """UPDATE noodinfo SET bloedgroep=?, medicijnen=?, allergieen=?, nood_naam=?,
                   nood_telefoon=?, nood_relatie=?, notitie=? WHERE id=1""",
                kolommen,
            )
        else:
            conn.execute(
                """INSERT INTO noodinfo
                   (id, bloedgroep, medicijnen, allergieen, nood_naam, nood_telefoon, nood_relatie, notitie)
                   VALUES (1, ?, ?, ?, ?, ?, ?, ?)""",
                kolommen,
            )
        conn.commit()
        conn.close()
        melding("Opgeslagen.")
        return redirect(url_for("gezondheid"))
    rij = conn.execute("SELECT * FROM noodinfo WHERE id=1").fetchone()
    extra = koppel_extra(conn, "gezondheid", 1)
    conn.close()
    if rij is None:
        waarden = leeg_nood()
    else:
        waarden = {sleutel: rij[sleutel] or "" for sleutel in leeg_nood()}
    return pagina("gezondheid.html", "gezondheid", waarden=waarden,
                  tel=tel_link(waarden["nood_telefoon"]), **extra)


@app.route("/zoeken")
def zoeken():
    q = tekst(request.args.get("q", ""), 100)
    if len(q) < 2:
        return pagina("zoeken.html", "", q=q, resultaten=[], te_kort=bool(q))
    conn = verbind()
    resultaten = zoek_items(conn, q)
    conn.close()
    return pagina("zoeken.html", "", q=q, resultaten=resultaten, te_kort=False)


@app.route("/bestand/<int:bestand_id>")
def bestand_zien(bestand_id):
    conn = verbind()
    rij = conn.execute("SELECT * FROM bestanden WHERE id=?", (bestand_id,)).fetchone()
    conn.close()
    if rij is None:
        abort(404)
    pad = bestand_pad(rij["opslag"])
    if pad is None:
        abort(404)
    ext = os.path.splitext(rij["opslag"])[1].lower()
    return send_file(
        pad,
        mimetype=MIME.get(ext, "application/octet-stream"),
        as_attachment=False,
        download_name=rij["naam"],
        max_age=0,
        conditional=True,
    )


@app.route("/bestand/<int:bestand_id>/verwijder", methods=["POST"])
def bestand_weg(bestand_id):
    conn = verbind()
    rij = conn.execute("SELECT * FROM bestanden WHERE id=?", (bestand_id,)).fetchone()
    if rij is None:
        conn.close()
        abort(404)
    terug = {
        "bezit": url_for("bezit_bewerk", bezit_id=rij["eigenaar_id"]),
        "voertuig": url_for("voertuig_bewerk", voertuig_id=rij["eigenaar_id"]),
        "verzekering": url_for("verzekering_bewerk", verzekering_id=rij["eigenaar_id"]),
        "document": url_for("document_bewerk", document_id=rij["eigenaar_id"]),
    }.get(rij["eigenaar"], url_for("index"))
    wis_bestand_rij(conn, rij)
    conn.commit()
    conn.close()
    melding("Bestand weggehaald.")
    return redirect(terug_naar(terug))


@app.route("/backup", methods=["POST"])
def backup():
    data = backup_bytes()
    return send_file(
        io.BytesIO(data),
        mimetype="application/zip",
        as_attachment=True,
        download_name=f"mijn-overzicht-{vandaag().isoformat()}.zip",
        max_age=0,
    )


def _verwijder(tabel, id_, eigenaar, terug_endpoint):
    if tabel not in TABELLEN:
        abort(404)
    conn = verbind()
    rij = conn.execute(f"SELECT id FROM {tabel} WHERE id=?", (id_,)).fetchone()
    if rij is None:
        conn.close()
        abort(404)
    if tabel == "verzekeringen":
        for last in conn.execute("SELECT id FROM vaste_lasten WHERE verzekering_id=?", (id_,)):
            wis_koppelingen(conn, "last", last["id"])
    soort = KOPPEL_VAN_TABEL.get(tabel)
    if soort:
        wis_koppelingen(conn, soort, id_)
    if eigenaar:
        wis_van(conn, eigenaar, id_)
    conn.execute(f"DELETE FROM {tabel} WHERE id=?", (id_,))
    conn.commit()
    conn.close()
    melding("Weggehaald.")
    return redirect(url_for(terug_endpoint))


@app.route("/koppelen", methods=["POST"])
def koppelen():
    van_type = request.form.get("van_type", "")
    naar_type = request.form.get("naar_type", "")
    try:
        van_id = int(request.form.get("van_id", ""))
        naar_id = int(request.form.get("naar_id", ""))
    except (TypeError, ValueError):
        abort(400)
    if van_type not in KOPPEL_SOORTEN or naar_type not in KOPPEL_SOORTEN:
        abort(400)
    terug = koppel_pad(van_type, van_id) or url_for("index")
    if orden_paar(van_type, van_id, naar_type, naar_id) is None:
        melding("Een item kan niet naar zichzelf verwijzen.", "fout")
        return redirect(terug)
    conn = verbind()
    if koppel_titel(conn, van_type, van_id) is None or koppel_titel(conn, naar_type, naar_id) is None:
        conn.close()
        abort(404)
    zorg_koppeling(conn, van_type, van_id, naar_type, naar_id, vast=0)
    conn.commit()
    conn.close()
    melding("Gekoppeld.")
    return redirect(terug)


@app.route("/koppelen/<int:koppel_id>/verwijder", methods=["POST"])
def koppeling_weg(koppel_id):
    conn = verbind()
    rij = conn.execute("SELECT * FROM koppelingen WHERE id=?", (koppel_id,)).fetchone()
    if rij is None:
        conn.close()
        abort(404)
    van_type = request.form.get("van_type", "") or rij["type_a"]
    try:
        van_id = int(request.form.get("van_id", "") or rij["id_a"])
    except (TypeError, ValueError):
        van_type, van_id = rij["type_a"], rij["id_a"]
    if van_type not in KOPPEL_SOORTEN:
        van_type, van_id = rij["type_a"], rij["id_a"]
    terug = koppel_pad(van_type, van_id) or url_for("index")
    if rij["vast"]:
        conn.close()
        melding("Deze koppeling hoort bij een veld. Haal hem daar weg.", "fout")
        return redirect(terug)
    conn.execute("DELETE FROM koppelingen WHERE id=?", (koppel_id,))
    conn.commit()
    conn.close()
    melding("Koppeling weggehaald.")
    return redirect(terug)


init_db()
herstel_koppelingen()
synchroniseer_wachtwoord()
activeer_https_vlag()


def _nginx_quotatie(pad):
    return '"' + pad.replace("\\", "/").replace('"', "") + '"'


def nginx_werkmap():
    """Config en pid staan buiten /data, zodat een back-up ze niet meeneemt."""
    return os.path.join(tempfile.gettempdir(), "mijn-overzicht-nginx")


def nginx_gebruiker():
    try:
        return pwd.getpwnam("nginx")
    except KeyError:
        return None


def bouw_nginx_config(poort, intern, cert, sleutel, pid, werkmap, foutlog=None):
    foutlog = foutlog or os.path.join(werkmap, "error.log")
    pagina_413 = (
        "<!DOCTYPE html><html lang=\"nl\"><head><meta charset=\"utf-8\">"
        "<title>Te groot</title></head><body><p>Dat is te veel in een keer.</p></body></html>"
    )
    return "\n".join([
        "worker_processes 1;",
        f"error_log {foutlog} warn;",
        f"pid {pid};",
        "events { worker_connections 256; }",
        "http {",
        "    server_tokens off;",
        "    access_log off;",
        "    client_max_body_size 32m;",
        "    charset utf-8;",
        f"    client_body_temp_path {werkmap}/client;",
        f"    proxy_temp_path {werkmap}/proxy;",
        "    server {",
        f"        listen {poort} ssl;",
        "        server_name _;",
        f"        ssl_certificate {_nginx_quotatie(cert)};",
        f"        ssl_certificate_key {_nginx_quotatie(sleutel)};",
        "        ssl_protocols TLSv1.2 TLSv1.3;",
        "        error_page 413 @te_groot;",
        "        location @te_groot {",
        "            internal;",
        "            default_type text/html;",
        '            add_header X-Content-Type-Options "nosniff" always;',
        '            add_header Referrer-Policy "same-origin" always;',
        '            add_header X-Frame-Options "DENY" always;',
        '            add_header Content-Security-Policy "default-src \'none\'; frame-ancestors \'none\'" always;',
        '            add_header Cache-Control "no-store" always;',
        f'            add_header Strict-Transport-Security "max-age={HSTS_SECONDEN}" always;',
        f"            return 413 '{pagina_413}';",
        "        }",
        "        location / {",
        f"            proxy_pass http://127.0.0.1:{intern};",
        "            proxy_http_version 1.1;",
        "            proxy_set_header Host $host;",
        "            proxy_set_header X-Real-IP $remote_addr;",
        "            proxy_set_header X-Forwarded-For $remote_addr;",
        "            proxy_set_header X-Forwarded-Proto https;",
        "            proxy_read_timeout 120s;",
        "            proxy_send_timeout 120s;",
        "        }",
        "    }",
        "}",
        "",
    ])


def _kopieer_geheim(bron, doel, uid, gid):
    with open(bron, "rb") as bestand:
        data = bestand.read()
    fd = os.open(doel, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    try:
        os.write(fd, data)
        os.fchown(fd, uid, gid)
        os.fchmod(fd, 0o600)
    finally:
        os.close(fd)


def _volg_nginx_log(pad):
    """Nginx draait zonder root en kan /dev/stderr niet openen. Dit kopieert zijn log."""
    while True:
        try:
            with open(pad, "r", encoding="utf-8", errors="replace") as bron:
                while True:
                    regel = bron.readline()
                    if not regel:
                        time.sleep(0.2)
                        continue
                    sys.stderr.write(regel)
                    sys.stderr.flush()
        except OSError:
            time.sleep(0.1)


def _sterf_met_ouder():
    """Nginx stopt mee als Python verdwijnt, ook zonder opruimen."""
    try:
        import ctypes

        libc = ctypes.CDLL(None)
        prctl = getattr(libc, "prctl", None)
        if prctl is not None:
            prctl(1, int(signal.SIGTERM), 0, 0, 0)
    except Exception:
        return None
    return None


def bewaak_nginx(proc, afsluiten, pid, stop=os._exit):
    code = proc.wait()
    if afsluiten.is_set():
        return
    logging.getLogger(__name__).error(
        "nginx is gestopt (code %s). De add-on stopt zodat hij opnieuw kan starten.",
        code,
    )
    try:
        os.remove(pid)
    except OSError:
        pass
    stop(1)


def stop_nginx(proc, afsluiten, pid):
    afsluiten.set()
    if proc.poll() is None:
        proc.terminate()
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait(timeout=5)
    try:
        os.remove(pid)
    except OSError:
        pass


def start_nginx(poort, intern, cert, sleutel):
    """TLS eindigt in nginx. Waitress ziet alleen http op localhost."""
    log = logging.getLogger(__name__)
    if not shutil_which("nginx"):
        log.error("nginx ontbreekt in de container. Https kan niet starten.")
        sys.exit(1)
    gebruiker = nginx_gebruiker()
    if gebruiker is None:
        log.error("De gebruiker nginx ontbreekt. Https kan niet starten.")
        sys.exit(1)
    werkmap = nginx_werkmap()
    os.makedirs(os.path.join(werkmap, "client"), mode=0o700, exist_ok=True)
    os.makedirs(os.path.join(werkmap, "proxy"), mode=0o700, exist_ok=True)
    for mapnaam in (werkmap, os.path.join(werkmap, "client"), os.path.join(werkmap, "proxy")):
        os.chown(mapnaam, gebruiker.pw_uid, gebruiker.pw_gid)
        os.chmod(mapnaam, 0o700)
    cert_kopie = os.path.join(werkmap, "cert.pem")
    sleutel_kopie = os.path.join(werkmap, "key.pem")
    _kopieer_geheim(cert, cert_kopie, gebruiker.pw_uid, gebruiker.pw_gid)
    _kopieer_geheim(sleutel, sleutel_kopie, gebruiker.pw_uid, gebruiker.pw_gid)
    pid = os.path.join(werkmap, "nginx.pid")
    foutlog = os.path.join(werkmap, "error.log")
    config_pad = os.path.join(werkmap, "nginx.conf")
    config = bouw_nginx_config(poort, intern, cert_kopie, sleutel_kopie, pid, werkmap, foutlog)
    fd = os.open(config_pad, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    try:
        os.write(fd, config.encode("utf-8"))
        os.fchown(fd, gebruiker.pw_uid, gebruiker.pw_gid)
        os.fchmod(fd, 0o600)
    finally:
        os.close(fd)
    threading.Thread(target=_volg_nginx_log, args=(foutlog,), name="nginx-log", daemon=True).start()
    test = subprocess.run(
        ["nginx", "-t", "-c", config_pad],
        capture_output=True,
        text=True,
        user=gebruiker.pw_uid,
        group=gebruiker.pw_gid,
    )
    if test.returncode != 0:
        extra = ""
        try:
            with open(foutlog, encoding="utf-8", errors="replace") as bestand:
                extra = bestand.read()[-2000:]
        except OSError:
            extra = ""
        log.error("nginx kan niet starten: %s %s", (test.stderr or test.stdout or "").strip(), extra.strip())
        sys.exit(1)
    proc = subprocess.Popen(
        ["nginx", "-c", config_pad, "-g", "daemon off;"],
        user=gebruiker.pw_uid,
        group=gebruiker.pw_gid,
        preexec_fn=_sterf_met_ouder,
    )
    deadline = time.time() + 5
    while time.time() < deadline:
        if proc.poll() is not None:
            log.error("nginx stopte meteen (code %s).", proc.returncode)
            sys.exit(1)
        try:
            with socket.create_connection(("127.0.0.1", poort), timeout=0.2):
                if os.path.exists(pid):
                    os.chmod(pid, 0o600)
                return proc, pid
        except OSError:
            time.sleep(0.05)
    log.error("nginx luistert niet op poort %s.", poort)
    proc.terminate()
    sys.exit(1)


def shutil_which(naam):
    for mapnaam in os.environ.get("PATH", "").split(os.pathsep):
        kandidaat = os.path.join(mapnaam, naam)
        if os.path.isfile(kandidaat) and os.access(kandidaat, os.X_OK):
            return kandidaat
    return None


def start_server(poort):
    log = logging.getLogger(__name__)
    # Waitress meldt anders het interne adres. De regel hieronder is de URL voor de browser.
    logging.getLogger("waitress").setLevel(logging.WARNING)
    if HTTPS_ACTIEF:
        if maak_ssl_context() is None:
            sys.exit(1)
        cert, sleutel = ssl_paden()
        intern = INTERN_POORT if poort != INTERN_POORT else INTERN_POORT + 1
        proc, pid = start_nginx(poort, intern, cert, sleutel)
        afsluiten = threading.Event()
        threading.Thread(
            target=bewaak_nginx,
            args=(proc, afsluiten, pid),
            name="nginx-bewaker",
            daemon=True,
        ).start()

        def bij_stop(signum, _frame):
            log.info("Stopverzoek ontvangen (%s). De add-on stopt.", signum)
            stop_nginx(proc, afsluiten, pid)
            sys.exit(0)

        signal.signal(signal.SIGTERM, bij_stop)
        atexit.register(lambda: stop_nginx(proc, afsluiten, pid))
        log.info("Mijn Overzicht %s is bereikbaar op https://0.0.0.0:%s", VERSIE, poort)
        from waitress import serve

        code = 1
        try:
            serve(app, host="127.0.0.1", port=intern, threads=8, url_scheme="https")
            log.error("De webserver is gestopt. De add-on stopt zodat hij opnieuw kan starten.")
        except SystemExit as einde:
            code = einde.code if isinstance(einde.code, int) else 0
        finally:
            stop_nginx(proc, afsluiten, pid)
        sys.exit(code)
    log.warning(
        "ssl staat uit. Het verkeer op poort %s is onversleuteld http. "
        "Zet deze poort niet open naar internet; gebruik het eigen netwerk, een VPN, of zet ssl aan.",
        poort,
    )
    log.info("Mijn Overzicht %s is bereikbaar op http://0.0.0.0:%s", VERSIE, poort)
    try:
        from waitress import serve

        serve(app, host="0.0.0.0", port=poort, threads=4)
        log.error("De webserver is gestopt. De add-on stopt zodat hij opnieuw kan starten.")
        sys.exit(1)
    except ImportError:
        app.run(host="0.0.0.0", port=poort)
        log.error("De webserver is gestopt. De add-on stopt zodat hij opnieuw kan starten.")
        sys.exit(1)


if __name__ == "__main__":
    niveaus = {
        "trace": logging.DEBUG,
        "debug": logging.DEBUG,
        "info": logging.INFO,
        "notice": logging.INFO,
        "warning": logging.WARNING,
        "error": logging.ERROR,
        "fatal": logging.CRITICAL,
    }
    logging.basicConfig(
        level=niveaus.get(os.environ.get("LOG_LEVEL", "info").lower(), logging.INFO),
        format="[%(asctime)s] %(levelname)s: %(message)s",
    )
    activeer_https_vlag()
    if not heeft_account():
        zorg_setup_code()
    poort = int(os.environ.get("PORT", "8320"))
    start_server(poort)
