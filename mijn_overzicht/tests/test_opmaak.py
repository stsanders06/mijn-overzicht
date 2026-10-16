"""De opmaak is van deze app, en de WebKit-regels blijven staan."""
import pathlib


LAYOUT = pathlib.Path(__file__).resolve().parent.parent / "app" / "templates" / "_layout.html"
OPMAAK = pathlib.Path(__file__).resolve().parent.parent / "app" / "static" / "opmaak.css"


def test_geen_facturen_blauw_en_eigen_lettertypen(client):
    css = client.get("/static/opmaak.css").data.decode()
    assert "#03a9f4" not in css
    assert "#0f5c50" in css
    assert "Atelier Serif" in css
    assert "Atelier Sans" in css
    assert "pre-line" not in css
    kop = client.get("/").headers["Content-Security-Policy"]
    assert "unsafe-inline" not in kop
    assert "style-src 'self'" in kop
    assert "script-src 'self'" in kop


def test_mobiele_balk_en_webkit_details(client):
    css = client.get("/static/opmaak.css").data.decode()
    assert ".balk" in css
    assert "details.meer:not([open]) > .meer-vel { display: none; }" in css
    assert "calc(100% - 26px)" in css
    assert "white-space: pre-wrap" in css
    bron = LAYOUT.read_text(encoding="utf-8")
    assert "<style" not in bron
    assert "pre-line" not in bron
    assert OPMAAK.is_file()


def test_notitie_staat_op_een_regel_in_het_sjabloon():
    lasten = (LAYOUT.parent / "lasten.html").read_text(encoding="utf-8")
    assert '<p class="notitie">{{ item.notitie }}</p>' in lasten
