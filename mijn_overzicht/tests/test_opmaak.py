"""De opmaak is van deze app, en de WebKit-regels blijven staan."""
import pathlib
import re


LAYOUT = pathlib.Path(__file__).resolve().parent.parent / "app" / "templates" / "_layout.html"


def css_van(inhoud):
    return "\n".join(re.findall(r"<style>(.*?)</style>", inhoud, re.S))


def test_geen_facturen_blauw_en_eigen_lettertypen(client):
    css = css_van(client.get("/").data.decode())
    assert "#03a9f4" not in css
    assert "#0f5c50" in css
    assert "Atelier Serif" in css
    assert "Atelier Sans" in css
    assert "pre-line" not in css


def test_mobiele_balk_en_webkit_details(client):
    css = css_van(client.get("/").data.decode())
    assert ".balk" in css
    assert "details.meer:not([open]) > .meer-vel { display: none; }" in css
    assert "calc(100% - 26px)" in css
    bron = LAYOUT.read_text(encoding="utf-8")
    assert "pre-line" not in bron
    assert 'class="notitie"' not in bron or "white-space: pre-wrap" in bron


def test_notitie_staat_op_een_regel_in_het_sjabloon():
    lasten = (LAYOUT.parent / "lasten.html").read_text(encoding="utf-8")
    assert '<p class="notitie">{{ item.notitie }}</p>' in lasten
