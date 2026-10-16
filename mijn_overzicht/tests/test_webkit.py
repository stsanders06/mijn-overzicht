"""Echte WebKit-meting: geen horizontale scroll, menu in beeld, tikvlakken."""
import threading

import pytest
from werkzeug.serving import make_server

import main as overzicht
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


def _wacht_menu_dicht(page):
    page.wait_for_function(
        """() => {
          const stijl = getComputedStyle(document.querySelector('details.meer'), '::details-content');
          return parseFloat(stijl.opacity) === 0 && stijl.contentVisibility === 'hidden';
        }""",
        timeout=1000,
    )


def _wacht_menu_open(page):
    page.wait_for_function(
        """() => {
          const stijl = getComputedStyle(document.querySelector('details.meer'), '::details-content');
          return stijl.contentVisibility === 'visible' && parseFloat(stijl.opacity) > 0.9;
        }""",
        timeout=1000,
    )


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
    server = make_server("127.0.0.1", 0, app, threaded=True)
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
                        assert page.is_hidden("#afschrijfdag")
                        assert page.is_visible("#referentie")
                        na = page.eval_on_selector("form.kaart", "el => el.getBoundingClientRect().height")
                        assert abs(na - voor) <= 48, (breedte, voor, na)
                        maten = page.evaluate(
                            "() => ({w: document.documentElement.scrollWidth, c: document.documentElement.clientWidth})"
                        )
                        assert maten["w"] <= maten["c"] + 1, (pad, breedte, maten)
                        slecht = _tikvlakken(page)
                        assert not slecht, (pad, breedte, slecht)
                        page.select_option("#frequentie", "week")
                        assert page.is_hidden("#afschrijfdag")
                        assert page.is_visible("#referentie")
                        page.select_option("#frequentie", "twee_weken")
                        assert page.is_hidden("#afschrijfdag")
                        assert page.is_visible("#referentie")
                        page.select_option("#frequentie", "maand")
                        assert page.is_visible("#afschrijfdag")
                        assert page.is_hidden("#referentie")
                if breedte < 800:
                    page.goto(basis + "/")
                    _wacht_menu_dicht(page)
                    page.click(".meer > summary")
                    _wacht_menu_open(page)
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
                    _wacht_menu_dicht(page)
                    page.click(".meer > summary")
                    assert page.eval_on_selector("details.meer", "el => el.open")
                    page.keyboard.press("Escape")
                    assert page.eval_on_selector("details.meer", "el => !el.open")
                    _wacht_menu_dicht(page)
                page.close()
            browser.close()
    finally:
        server.shutdown()


def test_webkit_meer_sluit_op_aanraking(app):
    playwright_sync = pytest.importorskip("playwright.sync_api")
    server = make_server("127.0.0.1", 0, app, threaded=True)
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
                _wacht_menu_open(page)
                if breedte == 390:
                    duur = page.evaluate(
                        "() => getComputedStyle(document.querySelector('details.meer'), '::details-content').transitionDuration"
                    )
                    assert "0.2s" in duur
                    page.tap(".meer-vel a[href$='/voertuigen']")
                    page.wait_for_selector("h1")
                    assert "Voertuigen" in page.inner_text("h1")
                    page.goto(basis + "/")
                    page.tap(".meer > summary")
                    _wacht_menu_open(page)
                vak = page.locator("h1").bounding_box()
                page.touchscreen.tap(vak["x"] + vak["width"] / 2, vak["y"] + min(12, vak["height"] / 2))
                assert page.eval_on_selector("details.meer", "el => !el.open")
                _wacht_menu_dicht(page)
                page.tap(".meer > summary")
                assert page.eval_on_selector("details.meer", "el => el.open")
                page.keyboard.press("Escape")
                assert page.eval_on_selector("details.meer", "el => !el.open")
                _wacht_menu_dicht(page)
                context.close()
            stil = browser.new_context(
                viewport={"width": 390, "height": 800},
                has_touch=True,
                reduced_motion="reduce",
            )
            page = stil.new_page()
            page.goto(basis + "/inloggen")
            page.fill("#wachtwoord", TEST_WACHTWOORD)
            page.tap("button[type=submit]")
            page.wait_for_selector("h1")
            page.tap(".meer > summary")
            duur = page.evaluate(
                "() => getComputedStyle(document.querySelector('details.meer'), '::details-content').transitionDuration"
            )
            assert "0.2" not in duur
            page.tap(".meer-vel a[href$='/voertuigen']")
            page.wait_for_selector("h1")
            assert "Voertuigen" in page.inner_text("h1")
            stil.close()
            browser.close()
    finally:
        server.shutdown()


def test_webkit_kaart_groep_en_weghalen(app, post):
    playwright_sync = pytest.importorskip("playwright.sync_api")
    post("/lasten/nieuw", data={"naam": "Netflix", "categorie": "Abonnement", "bedrag": "15", "frequentie": "maand"})
    post("/lasten/nieuw", data={"naam": "CZ", "categorie": "Verzekering", "bedrag": "40", "frequentie": "maand"})
    post("/contacten/nieuw", data={"naam": "Huisarts", "rol": "huisarts", "telefoon": "0612345678"})
    post("/verzekeringen/nieuw", data={"soort": "auto", "maatschappij": "ANWB", "premie": "20", "frequentie": "maand"})
    conn = overzicht.verbind()
    netflix = conn.execute("SELECT id FROM vaste_lasten WHERE naam='Netflix'").fetchone()["id"]
    contact = conn.execute("SELECT id FROM contacten WHERE naam='Huisarts'").fetchone()["id"]
    conn.execute(
        "INSERT INTO koppelingen (type_a, id_a, type_b, id_b, vast) VALUES ('last', ?, 'contact', ?, 0)",
        (netflix, contact),
    )
    conn.commit()
    conn.close()
    server = make_server("127.0.0.1", 0, app, threaded=True)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    basis = f"http://127.0.0.1:{server.server_port}"
    try:
        with playwright_sync.sync_playwright() as pw:
            browser = pw.webkit.launch()
            page = browser.new_page(viewport={"width": 390, "height": 800})
            page.goto(basis + "/inloggen")
            page.fill("#wachtwoord", TEST_WACHTWOORD)
            page.click("form button[type=submit]")
            page.wait_for_selector("h1")
            page.goto(basis + "/lasten")
            page.evaluate("() => document.querySelector('article.kaart').scrollIntoView({block: 'center'})")
            volgorde = page.evaluate(
                """() => [...document.querySelectorAll("main .groep-kop, main article.kaart")].map(el => ({
                  kop: el.classList.contains("groep-kop"),
                  groep: el.getAttribute("data-groep"),
                  top: el.getBoundingClientRect().top
                }))"""
            )
            assert [stuk["groep"] for stuk in volgorde] == ["Abonnement", "Abonnement", "Verzekering", "Verzekering"]
            assert [stuk["kop"] for stuk in volgorde] == [True, False, True, False]
            assert volgorde[0]["top"] < volgorde[1]["top"] < volgorde[2]["top"] < volgorde[3]["top"]
            geraakt = page.evaluate(
                """() => {
                  const kaart = document.querySelector('article.kaart');
                  const tekst = kaart.querySelector('p.stil');
                  const chip = kaart.querySelector('a.chip');
                  const tr = tekst.getBoundingClientRect();
                  const cr = chip.getBoundingClientRect();
                  const tx = tr.left + tr.width / 2;
                  const ty = tr.top + tr.height / 2;
                  const cx = cr.left + cr.width / 2;
                  const cy = cr.top + cr.height / 2;
                  const op_tekst = document.elementFromPoint(tx, ty);
                  const op_chip = document.elementFromPoint(cx, cy);
                  return {
                    tekst: op_tekst && op_tekst.className,
                    href: op_tekst && op_tekst.getAttribute('href'),
                    chip: op_chip === chip,
                    tx, ty, cx, cy,
                  };
                }"""
            )
            assert geraakt["tekst"] == "rij-link"
            assert geraakt["href"].endswith(f"/lasten/{netflix}")
            assert geraakt["chip"] is True
            page.mouse.click(geraakt["tx"], geraakt["ty"])
            page.wait_for_url(f"**/lasten/{netflix}")
            page.goto(basis + "/lasten")
            chip = page.locator("article.kaart a.chip").bounding_box()
            page.mouse.click(chip["x"] + chip["width"] / 2, chip["y"] + chip["height"] / 2)
            page.wait_for_url(f"**/contacten/{contact}")
            assert "/lasten/" not in page.url
            page.goto(basis + f"/lasten/{netflix}")
            for breedte in (320, 390, 1280):
                page.set_viewport_size({"width": breedte, "height": 800})
                maten = page.evaluate(
                    """() => {
                      const knop = document.querySelector("main.hoofd > form button.knop.gevaar");
                      const formulier = knop.closest("form");
                      const kaart = formulier.previousElementSibling;
                      const volgende = formulier.nextElementSibling;
                      const b = knop.getBoundingClientRect();
                      const k = kaart.getBoundingClientRect();
                      const n = volgende.getBoundingClientRect();
                      return {boven: b.top - k.bottom, onder: n.top - b.bottom, links: b.left - k.left, rechts: k.right - b.right};
                    }"""
                )
                assert maten["boven"] >= 16, (breedte, maten)
                assert maten["onder"] >= 16, (breedte, maten)
                assert maten["links"] >= 12, (breedte, maten)
                assert maten["rechts"] >= 0, (breedte, maten)
            page.goto(basis + "/lasten")
            doel = page.eval_on_selector(
                "article.kaart a.rij-link", "el => { el.focus(); return el.getAttribute('href'); }"
            )
            assert page.evaluate("() => document.activeElement.classList.contains('rij-link')")
            page.keyboard.press("Enter")
            page.wait_for_url(f"**{doel}", timeout=8000)
            page.goto(basis + "/verzekeringen")
            polis = page.locator("article.kaart", has_text="ANWB")
            polis.scroll_into_view_if_needed()
            vak = polis.bounding_box()
            page.mouse.click(vak["x"] + 24, vak["y"] + vak["height"] - 12)
            page.wait_for_url("**/verzekeringen/*")
            browser.close()
    finally:
        server.shutdown()


INDELING = r"""
() => {
  const app = document.querySelector(".app");
  const nav = document.querySelector("nav.balk");
  const navStijl = nav ? getComputedStyle(nav) : null;
  const navAan = !!(nav && navStijl.display !== "none");
  const appR = app ? app.getBoundingClientRect() : {top: 0, bottom: window.innerHeight, left: 0, right: window.innerWidth};
  const navR = navAan ? nav.getBoundingClientRect() : null;
  const issues = [];
  const doc = document.documentElement;
  if (doc.scrollWidth > doc.clientWidth + 1) issues.push("overflow pagina " + doc.scrollWidth);
  if (app && app.scrollWidth > app.clientWidth + 1) issues.push("overflow app " + app.scrollWidth);
  if (navAan) {
    if (navStijl.position !== "fixed") issues.push("balk niet vast");
    if (Math.abs(navR.bottom - window.innerHeight) > 1) issues.push("balk niet onderaan " + Math.round(navR.bottom));
    const scroller = document.scrollingElement;
    if (scroller !== document.documentElement && scroller !== document.body) issues.push("scroll niet op het document");
    const appScroll = app ? getComputedStyle(app).overflowY : "";
    if (appScroll === "auto" || appScroll === "scroll" || appScroll === "hidden") issues.push("app scrolt zelf " + appScroll);
  }
  const zichtbaar = (el) => {
    const s = getComputedStyle(el);
    if (s.display === "none" || s.visibility === "hidden" || Number(s.opacity) === 0) return false;
    const r = el.getBoundingClientRect();
    return r.width >= 2 && r.height >= 2;
  };
  const vak = (el) => {
    const r = el.getBoundingClientRect();
    const onder = navAan ? navR.top : window.innerHeight;
    const top = Math.max(r.top, appR.top, 0);
    const bottom = Math.min(r.bottom, onder);
    const left = Math.max(r.left, 0);
    const right = Math.min(r.right, window.innerWidth);
    if (bottom - top < 4 || right - left < 4) return null;
    return {top, bottom, left, right};
  };
  const snijdt = (a, b) => {
    const x = Math.min(a.right, b.right) - Math.max(a.left, b.left);
    const y = Math.min(a.bottom, b.bottom) - Math.max(a.top, b.top);
    return x > 4 && y > 4;
  };
  const naam = (el) => (el.innerText || el.getAttribute("aria-label") || el.tagName || "").trim().replace(/\s+/g, " ").slice(0, 36);
  const knopen = [...document.querySelectorAll("a, button, input, select, textarea, summary")].filter(zichtbaar);
  const tekst = [...document.querySelectorAll("h1, h2, h3, p, label, .groep-kop")].filter(zichtbaar);
  for (const el of knopen) {
    if (el.type === "hidden" || el.type === "checkbox") continue;
    if (!vak(el)) continue;
    const r = el.getBoundingClientRect();
    const label = el.closest("label");
    const doel = (label && (el.type === "checkbox" || el.type === "radio")) ? label.getBoundingClientRect() : r;
    if (doel.width < 44 || doel.height < 44) issues.push("tik " + Math.round(doel.width) + "x" + Math.round(doel.height) + " " + naam(el));
  }
  const alles = [...knopen, ...tekst];
  for (let i = 0; i < alles.length; i++) {
    const a = alles[i];
    const va = vak(a);
    if (!va) continue;
    for (let j = i + 1; j < alles.length; j++) {
      const b = alles[j];
      if (a.contains(b) || b.contains(a)) continue;
      const vb = vak(b);
      if (!vb || !snijdt(va, vb)) continue;
      issues.push("overlap " + naam(a) + " ~ " + naam(b));
      if (issues.length > 12) return issues;
    }
  }
  if (navAan && app) {
    const scroller = document.scrollingElement;
    scroller.scrollTop = scroller.scrollHeight;
    let laag = null;
    for (const el of document.querySelectorAll("main.hoofd > *")) {
      const r = el.getBoundingClientRect();
      if (r.height < 2) continue;
      if (laag === null || r.bottom > laag) laag = r.bottom;
    }
    const gat = nav.getBoundingClientRect().top - laag;
    if (gat < 12) issues.push("te krap onderaan " + Math.round(gat));
    scroller.scrollTop = 0;
  }
  return issues;
}
"""


def _controleer_indeling(page, pad, breedte):
    page.goto(pad)
    page.wait_for_selector("h1")
    problemen = page.evaluate(INDELING)
    assert not problemen, (breedte, pad, problemen)


def test_webkit_indeling(app, post):
    playwright_sync = pytest.importorskip("playwright.sync_api")
    server = make_server("127.0.0.1", 0, app, threaded=True)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    basis = f"http://127.0.0.1:{server.server_port}"
    leeg = [
        "/", "/lasten", "/verzekeringen", "/voertuigen", "/bezittingen", "/inkomen",
        "/datums", "/contacten", "/documenten", "/gezondheid", "/zoeken", "/zoeken?q=a",
        "/lasten/nieuw", "/verzekeringen/nieuw", "/voertuigen/nieuw", "/bezittingen/nieuw",
        "/inkomen/nieuw", "/datums/nieuw", "/contacten/nieuw", "/documenten/nieuw", "/geen-pagina",
    ]
    try:
        with playwright_sync.sync_playwright() as pw:
            browser = pw.webkit.launch()
            for breedte in (320, 390):
                page = browser.new_page(viewport={"width": breedte, "height": 800})
                page.set_default_timeout(8000)
                _controleer_indeling(page, basis + "/inloggen", breedte)
                page.fill("#wachtwoord", "fout-wachtwoord")
                page.click("form button[type=submit]")
                page.wait_for_selector(".toast")
                problemen = page.evaluate(INDELING)
                assert not problemen, (breedte, "login-fout", problemen)
                page.fill("#wachtwoord", TEST_WACHTWOORD)
                page.click("form button[type=submit]")
                page.wait_for_selector("h1")
                for pad in leeg:
                    _controleer_indeling(page, basis + pad, breedte)
                page.close()
            post("/lasten/nieuw", data={"naam": "Netflix", "categorie": "Abonnement", "bedrag": "15", "frequentie": "maand"})
            post("/verzekeringen/nieuw", data={"soort": "auto", "maatschappij": "ANWB", "premie": "20", "frequentie": "maand"})
            post("/voertuigen/nieuw", data={"soort": "auto", "merk": "Fiat", "model": "Panda", "kenteken": "AB-12-CD"})
            post("/bezittingen/nieuw", data={"naam": "Fiets", "categorie": "Vervoer", "waarde": "400"})
            post("/inkomen/nieuw", data={"soort": "toeslag", "toeslag": "zorgtoeslag", "netto": "123", "frequentie": "maand"})
            post("/datums/nieuw", data={"soort": "paspoort", "naam": "Paspoort", "datum": "2030-04-01"})
            post("/contacten/nieuw", data={"naam": "Huisarts", "rol": "huisarts", "telefoon": "0612345678"})
            post("/documenten/nieuw", data={"titel": "Koopcontract"})
            post("/gezondheid", data={"bloedgroep": "O+", "nood_naam": "Sam", "nood_telefoon": "0687654321"})
            conn = overzicht.verbind()
            paden = [
                "/", "/lasten", "/verzekeringen", "/voertuigen", "/bezittingen", "/inkomen",
                "/datums", "/contacten", "/documenten", "/gezondheid", "/zoeken?q=net", "/geen-pagina",
            ]
            for tabel, soort in (
                ("vaste_lasten", "lasten"),
                ("verzekeringen", "verzekeringen"),
                ("voertuigen", "voertuigen"),
                ("bezittingen", "bezittingen"),
                ("inkomens", "inkomen"),
                ("datums", "datums"),
                ("contacten", "contacten"),
                ("documenten", "documenten"),
            ):
                rij = conn.execute(f"SELECT id FROM {tabel} LIMIT 1").fetchone()
                if rij:
                    paden.append(f"/{soort}/{rij['id']}")
            conn.close()
            for breedte in (320, 390):
                page = browser.new_page(viewport={"width": breedte, "height": 800})
                page.set_default_timeout(8000)
                page.goto(basis + "/inloggen")
                page.fill("#wachtwoord", TEST_WACHTWOORD)
                page.click("form button[type=submit]")
                page.wait_for_selector("h1")
                for pad in paden:
                    _controleer_indeling(page, basis + pad, breedte)
                page.goto(basis + "/")
                page.click(".meer > summary")
                _wacht_menu_open(page)
                page.wait_for_function(
                    """() => {
                      const stijl = getComputedStyle(document.querySelector('details.meer'), '::details-content');
                      const t = stijl.transform;
                      return parseFloat(stijl.opacity) === 1 && (t === 'none' || t === 'matrix(1, 0, 0, 1, 0, 0)');
                    }""",
                    timeout=1000,
                )
                menu = page.evaluate(
                    """() => {
                      const items = [...document.querySelectorAll('.meer-vel a, .meer-vel button')];
                      const problemen = [];
                      for (let i = 0; i < items.length; i++) {
                        const a = items[i].getBoundingClientRect();
                        if (a.width < 44 || a.height < 44) problemen.push('tik ' + items[i].innerText);
                        for (let j = i + 1; j < items.length; j++) {
                          const b = items[j].getBoundingClientRect();
                          const x = Math.min(a.right, b.right) - Math.max(a.left, b.left);
                          const y = Math.min(a.bottom, b.bottom) - Math.max(a.top, b.top);
                          if (x > 4 && y > 4) problemen.push(items[i].innerText + ' ~ ' + items[j].innerText);
                        }
                      }
                      const vel = document.querySelector('.meer-vel').getBoundingClientRect();
                      const nav = document.querySelector('nav.balk').getBoundingClientRect();
                      if (vel.bottom > nav.top + 1) problemen.push('menu onder de balk');
                      const link = document.querySelector(".meer-vel a[href$='/voertuigen']");
                      const midden = link.getBoundingClientRect();
                      const doel = document.elementFromPoint(midden.left + midden.width / 2, midden.top + midden.height / 2);
                      return {problemen, tikt: doel === link};
                    }"""
                )
                assert not menu["problemen"], (breedte, menu["problemen"])
                assert menu["tikt"] is True
                if breedte == 390:
                    page.click(".meer-vel a[href$='/voertuigen']")
                    page.wait_for_url("**/voertuigen")
                page.close()
            conn = overzicht.verbind()
            conn.execute("DELETE FROM account")
            conn.commit()
            conn.close()
            page = browser.new_page(viewport={"width": 390, "height": 800})
            _controleer_indeling(page, basis + "/instellen", 390)
            bron = page.evaluate(
                """() => [...document.styleSheets].filter(s => (s.href || '').includes('opmaak.css') || (s.href || '').includes('kaal.css')).flatMap(s => [...s.cssRules].map(r => r.cssText)).join('\\n')"""
            )
            assert "env(safe-area-inset-bottom" in bron
            browser.close()
    finally:
        server.shutdown()


def _iphone(pw, breedte, hoogte):
    toestel = dict(pw.devices["iPhone 15"])
    toestel.pop("default_browser_type", None)
    toestel["viewport"] = {"width": breedte, "height": hoogte}
    return toestel


def test_webkit_iphone_balk_en_meer(app, post):
    """iPhone-descriptor: balk in beeld, document scrolt, Meer blijft in beeld."""
    playwright_sync = pytest.importorskip("playwright.sync_api")
    for nummer in range(8):
        post("/lasten/nieuw", data={
            "naam": f"Last {nummer}",
            "categorie": "Abonnement",
            "bedrag": "12",
            "frequentie": "maand",
        })
    server = make_server("127.0.0.1", 0, app, threaded=True)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    basis = f"http://127.0.0.1:{server.server_port}"
    try:
        with playwright_sync.sync_playwright() as pw:
            browser = pw.webkit.launch()
            for breedte, hoogte in ((390, 844), (320, 844)):
                toestel = _iphone(pw, breedte, hoogte)
                assert toestel["is_mobile"] is True
                assert toestel["has_touch"] is True
                context = browser.new_context(**toestel)
                page = context.new_page()
                page.set_default_timeout(8000)
                page.goto(basis + "/inloggen")
                assert page.evaluate("() => matchMedia('(hover: none) and (pointer: coarse)').matches")
                page.fill("#wachtwoord", TEST_WACHTWOORD)
                page.locator("form button[type=submit]").tap()
                page.wait_for_selector("h1")
                page.goto(basis + "/bezittingen")
                page.wait_for_selector("h1")
                meting = page.evaluate(
                    """() => {
                      const nav = document.querySelector('nav.balk');
                      const stijl = getComputedStyle(nav);
                      const navR = nav.getBoundingClientRect();
                      const scroller = document.scrollingElement;
                      const app = document.querySelector('.app');
                      const labels = [...document.querySelectorAll('nav.balk > a, nav.balk summary.balk-item')];
                      const labelProblemen = [];
                      for (const el of labels) {
                        const r = el.getBoundingClientRect();
                        const bereik = document.createRange();
                        bereik.selectNodeContents(el);
                        const t = bereik.getBoundingClientRect();
                        const naam = (el.innerText || '').trim();
                        if (r.top < -0.5 || r.left < -0.5 || r.bottom > window.innerHeight + 0.5 || r.right > window.innerWidth + 0.5) {
                          labelProblemen.push(naam + ' vak buiten');
                        }
                        if (t.width < 2 || t.height < 8) labelProblemen.push(naam + ' tekst plat');
                        if (t.top < -0.5 || t.left < -0.5 || t.bottom > window.innerHeight + 0.5 || t.right > window.innerWidth + 0.5) {
                          labelProblemen.push(naam + ' tekst buiten');
                        }
                        if (r.height < 40) labelProblemen.push(naam + ' te laag ' + Math.round(r.height));
                        if (el.scrollWidth > el.clientWidth + 1 && getComputedStyle(el).overflowX !== 'visible') {
                          labelProblemen.push(naam + ' afgeknipt');
                        }
                      }
                      const css = [...document.styleSheets]
                        .filter(s => (s.href || '').includes('opmaak.css'))
                        .flatMap(s => [...s.cssRules].map(r => r.cssText))
                        .join('\\n');
                      return {
                        vast: stijl.position,
                        onder: stijl.bottom,
                        navOnder: Math.abs(navR.bottom - window.innerHeight),
                        navHoog: navR.height,
                        paddingOnder: getComputedStyle(document.body).paddingBottom,
                        appScroll: getComputedStyle(app).overflowY,
                        bodyScroll: getComputedStyle(document.body).overflowY,
                        scroller: scroller === document.documentElement ? 'html' : (scroller === document.body ? 'body' : 'anders'),
                        labels: labels.map(el => (el.innerText || '').trim()),
                        labelProblemen,
                        viewport: document.querySelector('meta[name=viewport]').content,
                        cssVast: css.includes('position: fixed') && css.includes('bottom: 0'),
                        cssSafe: css.includes('env(safe-area-inset-bottom'),
                        cssY: /translateY\\(8px\\)/.test(css),
                        cssOorsprong: (css.match(/transform-origin:[^;]+/) || ['geen'])[0],
                      };
                    }"""
                )
                assert meting["vast"] == "fixed", meting
                assert meting["onder"] == "0px", meting
                assert meting["navOnder"] <= 1, meting
                assert meting["navHoog"] >= 64, meting
                assert meting["paddingOnder"] == "64px", meting
                assert meting["appScroll"] == "visible", meting
                assert meting["bodyScroll"] in ("visible", "auto"), meting
                assert meting["scroller"] in ("html", "body"), meting
                assert meting["labels"] == ["Overzicht", "Lasten", "Polissen", "Spullen", "Meer"], meting
                assert not meting["labelProblemen"], (breedte, meting["labelProblemen"])
                assert "viewport-fit=cover" in meting["viewport"]
                assert meting["cssVast"] and meting["cssSafe"] and meting["cssY"], meting.get("cssOorsprong")
                assert "bottom" in meting["cssOorsprong"] and "right" in meting["cssOorsprong"], meting["cssOorsprong"]
                page.goto(basis + "/lasten")
                page.wait_for_selector("h1")
                scroll = page.evaluate(
                    """() => {
                      const scroller = document.scrollingElement;
                      const voor = scroller.scrollTop;
                      scroller.scrollTop = scroller.scrollHeight;
                      return {
                        voor,
                        na: scroller.scrollTop,
                        hoog: scroller.scrollHeight,
                        zicht: scroller.clientHeight,
                        element: scroller === document.documentElement || scroller === document.body,
                      };
                    }"""
                )
                assert scroll["element"] is True, scroll
                assert scroll["hoog"] > scroll["zicht"] + 40, scroll
                assert scroll["na"] > scroll["voor"] + 40, scroll
                page.evaluate("() => { document.scrollingElement.scrollTop = 0; }")
                page.goto(basis + "/")
                page.wait_for_selector("nav.balk")
                frames = page.evaluate(
                    """() => {
                      const vel = document.querySelector('.meer-vel');
                      const summary = document.querySelector('details.meer > summary');
                      summary.click();
                      const anim = vel.getAnimations().find(a => a.animationName === 'meer-open') || vel.getAnimations()[0];
                      if (!anim) return {fout: 'geen animatie'};
                      anim.pause();
                      const duur = Number(anim.effect.getComputedTiming().duration) || 200;
                      const monsters = [];
                      for (const t of [0, 40, 80, 120, 160, duur]) {
                        anim.currentTime = Math.min(t, duur);
                        const r = vel.getBoundingClientRect();
                        const m = new DOMMatrix(getComputedStyle(vel).transform);
                        monsters.push({
                          t,
                          top: r.top, right: r.right, bottom: r.bottom, left: r.left,
                          width: r.width, height: r.height,
                          tx: m.m41, ty: m.m42,
                          opacity: parseFloat(getComputedStyle(vel).opacity),
                        });
                      }
                      anim.finish();
                      const einde = vel.getBoundingClientRect();
                      const nav = document.querySelector('nav.balk').getBoundingClientRect();
                      const knop = summary.getBoundingClientRect();
                      return {duur, monsters, einde: {top: einde.top, right: einde.right, bottom: einde.bottom, left: einde.left}, navTop: nav.top, knopTop: knop.top, knopRight: knop.right, knopLeft: knop.left};
                    }"""
                )
                assert "fout" not in frames, (breedte, frames)
                assert len(frames["monsters"]) >= 5, frames
                assert frames["duur"] <= 250, frames
                buiten = []
                for monster in frames["monsters"]:
                    if monster["width"] < 8 or monster["height"] < 8:
                        buiten.append(("leeg", monster))
                        continue
                    if monster["top"] < -1 or monster["left"] < -1:
                        buiten.append(("boven", monster))
                    if monster["bottom"] > hoogte + 1 or monster["right"] > breedte + 1:
                        buiten.append(("onder", monster))
                    if abs(monster["ty"]) > 24 or abs(monster["tx"]) > 24:
                        buiten.append(("sprong", monster))
                assert not buiten, (breedte, buiten)
                einde = frames["einde"]
                assert abs(einde["bottom"] - (frames["navTop"] - 8)) <= 2, frames
                assert einde["bottom"] <= frames["knopTop"] + 1, frames
                assert einde["bottom"] >= frames["knopTop"] - 20, frames
                assert einde["right"] >= frames["knopLeft"], frames
                assert einde["right"] <= breedte + 1, frames
                assert einde["right"] >= breedte - 24, frames
                context.close()
            browser.close()
    finally:
        server.shutdown()
