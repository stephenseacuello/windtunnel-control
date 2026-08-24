"""
test_dashboard.py — static checks on the web dashboard.

There were no frontend tests at all, and the two worst bugs this project has
had were both statically detectable:

  · `$('#cfg-reload')` referenced a button that has never existed in the
    template. `null.onclick = ...` threw, and in a classic non-deferred script
    that ABORTS THE WHOLE FILE — so connectStream() never ran and the
    dashboard displayed its static zeros indefinitely while START and E-STOP
    stayed live. A calm, plausible, permanently stale control panel.

  · `sw-step` and `sw-dwell` each appeared on two tabs. `document.querySelector`
    returns the first match, so the Profiles stepped sweep silently submitted
    the Turbine tab's values.

Neither needs a browser to catch. Both are a selector that does not resolve
and an id that appears twice.

No JS runtime is required for most of this; where `node` is available the
syntax check runs too, and is skipped where it is not.
"""

import json
import re
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
WEB = ROOT / "webapp"
HTML = (WEB / "templates" / "index.html").read_text()
JS = (WEB / "static" / "app.js").read_text()
CSS = (WEB / "static" / "uri.css").read_text()
APP = (WEB / "app.py").read_text()

# ids present in the template
HTML_IDS = set(re.findall(r'id="([^"]+)"', HTML))


def strip_js_comments(src):
    """Doc comments carry illustrative selectors that are not real lookups."""
    src = re.sub(r"/\*.*?\*/", "", src, flags=re.S)
    return re.sub(r"^\s*//.*$", "", src, flags=re.M)


def js_selectors():
    """
    Every #id the script looks up, from $(), bind() and getElementById.

    Comments are stripped first, and selectors built by concatenation
    (`$('#p-' + name)`) are skipped — they cannot be resolved statically and
    are covered by the tab/page test instead.
    """
    src = strip_js_comments(JS)
    out = set()
    pats = [
        r"\$\(\s*'#([A-Za-z0-9_-]+)'\s*\)",
        r'\$\(\s*"#([A-Za-z0-9_-]+)"\s*\)',
        r"bind\(\s*'#([A-Za-z0-9_-]+)'\s*,",
        r'bind\(\s*"#([A-Za-z0-9_-]+)"\s*,',
        r"getElementById\(\s*'([A-Za-z0-9_-]+)'\s*\)",
    ]
    for pat in pats:
        out.update(m.group(1) for m in re.finditer(pat, src))
    return out


# ═══════════════════════════════════════════════════════════════════════════
# THE TWO BUGS THAT ACTUALLY HAPPENED
# ═══════════════════════════════════════════════════════════════════════════

def test_no_duplicate_element_ids():
    """
    `$` is document.querySelector, which returns the FIRST match. A duplicate
    id means one tab's control silently reads another tab's input, and
    nothing anywhere reports it.
    """
    ids = re.findall(r'id="([^"]+)"', HTML)
    dupes = sorted({i for i in ids if ids.count(i) > 1})
    assert not dupes, f"duplicate ids in index.html: {dupes}"


def test_every_selector_the_script_uses_exists():
    """
    A selector that resolves to nothing is how the dashboard died: one stale
    id aborted app.js and the page never received a telemetry frame.

    `$()` now returns an inert node rather than null, so a miss no longer
    kills the boot — but a miss is still a control that does nothing, and
    that is worth failing over.
    """
    # Built at runtime rather than present in the template.
    DYNAMIC = {"live-plot"}
    missing = sorted(s for s in js_selectors()
                     if s not in HTML_IDS and s not in DYNAMIC)
    assert not missing, (
        "app.js looks up ids that are not in index.html: " + ", ".join(missing))


# ═══════════════════════════════════════════════════════════════════════════
# THE API CONTRACT
# ═══════════════════════════════════════════════════════════════════════════

def flask_routes():
    return set(re.findall(r"@app\.route\(\s*[\"']([^\"']+)", APP))


def test_every_api_path_the_script_calls_is_routed():
    """
    A typo in a fetch path is a 404 the operator sees as a button that does
    nothing. The routes and the calls are in different files and nothing
    else keeps them in step.
    """
    routes = flask_routes()
    src = strip_js_comments(JS)
    called = set()
    for m in re.finditer(r"""['"](/api/[A-Za-z0-9_/-]+)['"]""", src):
        called.add(m.group(1))          # plain string: the whole path
    # A template literal must be matched WHOLE — its static tail carries
    # segments too. `/api/blades/${n}/stl` is four segments, not two.
    for m in re.finditer(r"`(/api/[^`]*)`", src):
        called.add(re.sub(r"\$\{[^}]*\}", "X", m.group(1)))
    # Flask <converters> match any single segment.
    patterns = [re.compile("^" + re.sub(r"<[^>]+>", r"[^/]+", r) + "$")
                for r in routes]
    missing = sorted(p for p in called
                     if not any(rx.match(p) for rx in patterns))
    assert not missing, f"app.js calls unrouted paths: {missing}"


def test_snapshot_keys_the_ui_reads_are_produced():
    """
    snapshot() is the UI contract. Adding a key is safe; renaming one breaks
    the frontend silently, because JavaScript reads a missing property as
    undefined and renders it as nothing.
    """
    ctl = (WEB / "controller.py").read_text()
    body = ctl[ctl.index("def snapshot(self):"):]
    for key in ("connected", "dry_run", "estopped", "running", "measured",
                "target", "amps", "interlock", "load", "age_s", "sweep"):
        assert f'"{key}"' in body, f"snapshot() no longer produces '{key}'"


# ═══════════════════════════════════════════════════════════════════════════
# THINGS THE REVIEW PANELS FOUND
# ═══════════════════════════════════════════════════════════════════════════

def test_a_missing_element_cannot_abort_the_script():
    """
    There are ~25 top-level `$('#x').onclick = fn` bindings. Rewriting them
    all is churn; what matters is that a missing element cannot throw, because
    in a classic non-deferred script one TypeError aborts the entire file and
    everything after it — including connectStream() — never runs.

    So the requirement is the safety net, not the call style: $() must return
    an inert node rather than null, and misses must be surfaced.
    """
    assert "NULL_NODE" in JS, "the inert-node fallback in $() is gone"
    assert "MISSING" in JS, "missing selectors are no longer recorded"
    assert "auditDom" in JS, "the DOM audit that surfaces misses is gone"
    body = JS[JS.index("const $ = s =>"):]
    body = body[:body.index("\n};") + 3]
    assert "NULL_NODE" in body, "$() no longer returns the inert node"


def test_setup_canvas_never_feeds_its_own_output_back():
    """
    setupCanvas once fell back to `cv.width` when the element measured 0x0.
    cv.width is the bitmap size in DEVICE pixels — the value the next line
    writes — so each call re-multiplied by devicePixelRatio and a hidden
    canvas grew fourfold in area per frame until the tab died.
    """
    body = JS[JS.index("function setupCanvas"):]
    body = body[:body.index("\n}")]
    assert "cv.width ||" not in body and "cv.height ||" not in body, (
        "setupCanvas is reading cv.width/cv.height as a size fallback again — "
        "that is the runaway-allocation bug")
    assert "return null" in body, (
        "setupCanvas must return null for an unlaid-out canvas so callers "
        "can no-op")


def test_canvases_have_a_size_class():
    """
    A canvas with no sizing class inside a hidden tab measures 0x0 and, once
    drawn, stays blank. That is why the STL viewer never appeared.
    """
    for m in re.finditer(r"<canvas([^>]*)>", HTML):
        attrs = m.group(1)
        cid = re.search(r'id="([^"]+)"', attrs)
        assert "class=" in attrs, (
            f"canvas {cid.group(1) if cid else '?'} has no class — it will "
            f"have no laid-out height")


def test_interlock_is_enforced_server_side_not_only_in_the_ui():
    """
    A greyed-out button is not an interlock. A stale page, a second tab or a
    direct POST all bypass it.
    """
    ctl = (WEB / "controller.py").read_text()
    assert "_authorise" in ctl, "the single authorisation gate is gone"
    gate = ctl[ctl.index("def _authorise"):]
    gate = gate[:gate.index("\n    def ", 10)]
    for must in ("estopped", "load", "sweep"):
        assert must in gate, f"_authorise no longer checks {must}"


def test_stale_telemetry_is_rendered_not_merely_recorded():
    """A frozen panel and a live one must not look identical."""
    assert "markStale" in JS and "is-stale" in JS
    assert ".is-stale" in CSS, "the is-stale class has no styling"


# ═══════════════════════════════════════════════════════════════════════════

@pytest.mark.skipif(not shutil.which("node"), reason="node not installed")
def test_javascript_parses():
    r = subprocess.run(["node", "--check", str(WEB / "static" / "app.js")],
                       capture_output=True, text=True)
    assert r.returncode == 0, r.stderr


def test_html_has_no_unclosed_section():
    assert HTML.count("<section") == HTML.count("</section>")


def test_every_nav_tab_has_a_page():
    tabs = set(re.findall(r'data-p="([^"]+)"', HTML))
    pages = set(re.findall(r'<section class="page[^"]*" id="p-([^"]+)"', HTML))
    assert tabs == pages, (
        f"tabs without a page: {sorted(tabs - pages)}; "
        f"pages without a tab: {sorted(pages - tabs)}")
