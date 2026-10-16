"""Gemeenschappelijke opzet voor de tests.

De app leest DATA_DIR bij het importeren en maakt daar meteen de database aan.
Die map moet daarom vóór de import naar een tijdelijke map wijzen.
"""
import os
import pathlib
import sys
import tempfile

import pytest

APP_DIR = pathlib.Path(__file__).resolve().parent.parent / "app"
sys.path.insert(0, str(APP_DIR))

os.environ["DATA_DIR"] = tempfile.mkdtemp(prefix="overzicht-tests-")
os.environ["SECRET_KEY"] = "sleutel-voor-de-tests"

import main as overzicht  # noqa: E402

TEST_WACHTWOORD = "geheim-wachtwoord"
TEST_HASH = overzicht.generate_password_hash(TEST_WACHTWOORD)

TABELLEN = [
    "bestanden",
    "koppelingen",
    "voertuigen",
    "vaste_lasten",
    "verzekeringen",
    "bezittingen",
    "inkomens",
    "datums",
    "contacten",
    "documenten",
    "noodinfo",
]


@pytest.fixture
def app():
    overzicht.app.config["TESTING"] = True
    overzicht.MISLUKTE_POGINGEN.clear()
    opties = pathlib.Path(overzicht.OPTIONS_PATH)
    if opties.exists():
        opties.unlink()
    conn = overzicht.verbind()
    conn.execute("DELETE FROM account")
    conn.execute(
        "INSERT INTO account (id, wachtwoord, aangemaakt) VALUES (1, ?, '2026-01-01')",
        (TEST_HASH,),
    )
    for tabel in TABELLEN:
        conn.execute(f"DELETE FROM {tabel}")
    conn.commit()
    conn.close()
    for pad in pathlib.Path(overzicht.BESTAND_DIR).iterdir():
        if pad.is_file():
            pad.unlink()
    yield overzicht.app
    overzicht.MISLUKTE_POGINGEN.clear()


@pytest.fixture
def client(app):
    with app.test_client() as browser:
        with browser.session_transaction() as sessie:
            sessie["csrf_token"] = "test-token"
            sessie["ingelogd"] = True
        yield browser


@pytest.fixture
def uitgelogde_client(app):
    with app.test_client() as browser:
        with browser.session_transaction() as sessie:
            sessie["csrf_token"] = "test-token"
        yield browser


@pytest.fixture
def zonder_account(app):
    conn = overzicht.verbind()
    conn.execute("DELETE FROM account")
    conn.commit()
    conn.close()
    with app.test_client() as browser:
        with browser.session_transaction() as sessie:
            sessie["csrf_token"] = "test-token"
        yield browser


@pytest.fixture
def post(client):
    def _post(url, data=None, **kwargs):
        gegevens = dict(data or {})
        gegevens.setdefault("csrf_token", "test-token")
        return client.post(url, data=gegevens, **kwargs)

    return _post
