"""Echte WebKit-meting: geen horizontale scroll, menu in beeld, tikvlakken."""
import threading

import pytest
from werkzeug.serving import make_server

from conftest import TEST_WACHTWOORD

PAGINAS = [
    "/",
    "/lasten",
    "/lasten/nieuw",
    "/verzekeringen",
    "/verzekeringen/nieuw",
    "/voertuigen",
    "/voertuigen/nieuw",
    "/bezittingen",
    "/bezittingen/nieuw",
    "/inkomen",
    "/inkomen/nieuw",
    "/datums",
    "/datums/nieuw",
    "/contacten",
    "/contacten/nieuw",
    "/documenten",
    "/documenten/nieuw",
    "/gezondheid",
    "/zoeken",
]


def _tikvlakken(page):
    return page.evaluate(
        """() => {
          const slecht = [];
          const nodes = document.querySelectorAll("a, button, input, select, textarea, summary");
          for (const el of nodes) {
            const stijl = getComputedStyle(el);
            if (stijl.display === "none" || stijl.visibility === "hidden") continue;
            const rect = el.getBoundingClientRect();
            if (rect.width < 1 || rect.height < 1) continue;
            if (el.type === "checkbox" || el.type === "hidden") {
              const label = el.closest("label");
              if (!label) continue;
              const vak = label.getBoundingClientRect();
              if (vak.height >= 44 && vak.width >= 44) continue;
            }
            if (rect.height < 44 || rect.width < 44) {
              slecht.push((el.getAttribute("aria-label") || el.textContent || el.name || el.tagName).trim().slice(0, 40)
                + " " + Math.round(rect.width) + "x" + Math.round(rect.height));
            }
          }
          return slecht;
        }"""
    )


def test_webkit_breedtes_menu_en_tikvlakken(app):
    playwright_sync = pytest.importorskip("playwright.sync_api")
    server = make_server("127.0.0.1", 0, app)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    basis = f"http://127.0.0.1:{server.server_port}"
    try:
        with playwright_sync.sync_playwright() as pw:
            browser = pw.webkit.launch()
            for breedte in (320, 390, 1280):
                page = browser.new_page(viewport={"width": breedte, "height": 800})
                page.goto(basis + "/inloggen")
                page.fill("#wachtwoord", TEST_WACHTWOORD)
                page.click("button[type=submit]")
                page.wait_for_selector("h1")
                for pad in PAGINAS:
                    page.goto(basis + pad)
                    page.wait_for_selector("h1")
                    maten = page.evaluate(
                        "() => ({w: document.documentElement.scrollWidth, c: document.documentElement.clientWidth})"
                    )
                    assert maten["w"] <= maten["c"] + 1, (pad, breedte, maten)
                    slecht = _tikvlakken(page)
                    assert not slecht, (pad, breedte, slecht)
                    if pad == "/lasten/nieuw":
                        voor = page.eval_on_selector("form.kaart", "el => el.getBoundingClientRect().height")
                        page.select_option("#frequentie", "vier_weken")
                        assert page.is_hidden("#afschrijfdag-veld")
                        assert page.is_visible("#referentie")
                        na = page.eval_on_selector("form.kaart", "el => el.getBoundingClientRect().height")
                        assert abs(na - voor) <= 24, (breedte, voor, na)
                        maten = page.evaluate(
                            "() => ({w: document.documentElement.scrollWidth, c: document.documentElement.clientWidth})"
                        )
                        assert maten["w"] <= maten["c"] + 1, (pad, breedte, maten)
                        slecht = _tikvlakken(page)
                        assert not slecht, (pad, breedte, slecht)
                        page.select_option("#frequentie", "week")
                        assert page.is_visible("#referentie")
                        page.select_option("#frequentie", "twee_weken")
                        assert page.is_visible("#referentie")
                        page.select_option("#frequentie", "maand")
                        assert page.is_visible("#afschrijfdag")
                        assert page.is_hidden("#referentie-veld")
                if breedte < 800:
                    page.goto(basis + "/")
                    assert page.eval_on_selector(
                        ".meer-vel", "el => getComputedStyle(el).display === 'none'"
                    )
                    page.click(".meer > summary")
                    vak = page.eval_on_selector(
                        ".meer-vel",
                        """el => {
                          const r = el.getBoundingClientRect();
                          return {left: r.left, right: r.right, top: r.top, bottom: r.bottom,
                                  w: window.innerWidth, h: window.innerHeight};
                        }""",
                    )
                    assert vak["left"] >= 0
                    assert vak["right"] <= vak["w"] + 1
                    assert vak["top"] >= 0
                    assert vak["bottom"] <= vak["h"] + 1
                    page.click("h1")
                    assert page.eval_on_selector("details.meer", "el => !el.open")
                    assert page.eval_on_selector(
                        ".meer-vel", "el => getComputedStyle(el).display === 'none'"
                    )
                    page.click(".meer > summary")
                    assert page.eval_on_selector("details.meer", "el => el.open")
                    page.keyboard.press("Escape")
                    assert page.eval_on_selector("details.meer", "el => !el.open")
                    assert page.eval_on_selector(
                        ".meer-vel", "el => getComputedStyle(el).display === 'none'"
                    )
                page.close()
            browser.close()
    finally:
        server.shutdown()


def test_webkit_meer_sluit_op_aanraking(app):
    playwright_sync = pytest.importorskip("playwright.sync_api")
    server = make_server("127.0.0.1", 0, app)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    basis = f"http://127.0.0.1:{server.server_port}"
    try:
        with playwright_sync.sync_playwright() as pw:
            browser = pw.webkit.launch()
            for breedte in (320, 390):
                context = browser.new_context(
                    viewport={"width": breedte, "height": 800},
                    has_touch=True,
                )
                page = context.new_page()
                page.goto(basis + "/inloggen")
                page.fill("#wachtwoord", TEST_WACHTWOORD)
                page.tap("button[type=submit]")
                page.wait_for_selector("h1")
                uitlijning = page.evaluate(
                    """() => {
                      const meer = document.querySelector(".meer > summary").getBoundingClientRect();
                      const buur = document.querySelector(".balk > a").getBoundingClientRect();
                      return {
                        dy: Math.abs((meer.top + meer.bottom) / 2 - (buur.top + buur.bottom) / 2),
                        dh: Math.abs(meer.height - buur.height),
                      };
                    }"""
                )
                assert uitlijning["dy"] <= 2, (breedte, uitlijning)
                assert uitlijning["dh"] <= 2, (breedte, uitlijning)
                page.tap(".meer > summary")
                assert page.eval_on_selector("details.meer", "el => el.open")
                vak = page.locator("h1").bounding_box()
                page.touchscreen.tap(vak["x"] + vak["width"] / 2, vak["y"] + min(12, vak["height"] / 2))
                assert page.eval_on_selector("details.meer", "el => !el.open")
                assert page.eval_on_selector(
                    ".meer-vel", "el => getComputedStyle(el).display === 'none'"
                )
                page.tap(".meer > summary")
                assert page.eval_on_selector("details.meer", "el => el.open")
                page.keyboard.press("Escape")
                assert page.eval_on_selector("details.meer", "el => !el.open")
                context.close()
            browser.close()
    finally:
        server.shutdown()
