"""
test_tunnel_node.py — the ambient + vibration node.

The node measures air density, and Cp goes as 1/ρ. This rig has computed every
Cp from an assumed 1.204 kg/m³, and the node's own sensor self-heats to ~42 °C
on a powered board — a 6.5% density error, half the size of the entire
Ra20-vs-Ra80 result. So "is it plugged in" is not the interesting question;
"is the number it gives trustworthy, and does the code say when it is not" is.
"""

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "webapp"))

import tunnel_node as tn                                    # noqa: E402

NODE = (ROOT / "src" / "tunnel_node.py").read_text()
CONTROLLER = (ROOT / "webapp" / "controller.py").read_text()
APP = (ROOT / "webapp" / "app.py").read_text()
JS = (ROOT / "webapp" / "static" / "app.js").read_text()
HTML = (ROOT / "webapp" / "templates" / "index.html").read_text()


class TestItNeverDisturbsTheDrive:
    """
    On macOS a /dev/cu.* device can be opened by more than one process, so
    probing for the node can open the DRIVE's port while the dashboard holds
    it — two readers taking each other's replies, mid-sweep, with a 15 HP fan
    running.
    """

    def test_autodetect_excludes_the_configured_drive_port(self):
        assert "_drive_port()" in NODE
        i = NODE.index("def resolve_port")
        body = NODE[i:i + 1400]
        assert "p != drive" in body, \
            "autodetect does not exclude the drive's port"

    def test_it_refuses_rather_than_guessing(self):
        i = NODE.index("def resolve_port")
        body = NODE[i:i + 1400]
        assert "several candidate ports" in body, \
            "an ambiguous choice is resolved by guessing"

    def test_it_listens_before_it_writes(self):
        """
        Excluding by config is not enough — transport.port has gone stale
        repeatedly. What can be relied on is what a port says unprompted.
        """
        i = NODE.index("def connect")
        body = NODE[i:i + 2200]
        assert "sniff" in body, "connect writes before listening"
        assert body.index("sniff") < body.index('self.command("ID")'), \
            "the sniff happens after the first write, which is too late"


class TestTheNodeIsOptional:
    """A missing ambient sensor must never stop a run. It costs a line in a
    CSV; refusing to sweep over it costs the session."""

    def test_ambient_meta_never_raises(self):
        import sweep_core as sc

        class Broken:
            def ambient(self):
                raise RuntimeError("bus error")

        assert "not recorded" in sc.ambient_meta(None)["air"]
        assert "not recorded" in sc.ambient_meta(Broken())["air"]

    def test_the_dashboard_connect_never_raises(self):
        i = CONTROLLER.index("def connect_node")
        body = CONTROLLER[i:i + 900]
        assert "except Exception" in body, "connect_node can raise"

    def test_the_cli_continues_without_it(self):
        cli = (ROOT / "src" / "blade_sweep.py").read_text()
        i = cli.index("from tunnel_node import TunnelNode")
        assert "except Exception" in cli[i - 200:i + 400], \
            "a missing node would abort the sweep"


class TestOneSpeakerPerPort:
    def test_burst_and_the_poll_thread_are_locked_against_each_other(self):
        """
        Unlocked, the two interleave and pyserial reports "device reports
        readiness to read but returned no data" — which reads like a
        disconnected board and is not. Observed before the lock existed.
        """
        assert "_node_lock" in CONTROLLER
        i = CONTROLLER.index("def node_burst")
        assert "self._node_lock" in CONTROLLER[i:i + 900], \
            "a burst does not hold the port"

    def test_the_poll_skips_rather_than_blocks(self):
        """Waiting behind a multi-second burst would stall the drive poll,
        which is what feeds the PMC's host watchdog."""
        assert "acquire(blocking=False)" in CONTROLLER, \
            "the ambient poll can block behind a burst"


class TestSpectrum:
    def test_it_resamples_because_the_capture_is_unpaced(self):
        """The firmware runs the capture loop flat out and timestamps each
        sample; an FFT of a non-uniform series smears every line."""
        assert "np.interp" in NODE, "spectrum does not resample"
        assert "jitter" in NODE, "it does not report the jitter it corrected"

    def test_a_known_tone_lands_on_the_right_bin(self):
        import numpy as np
        fs, f0 = 1000.0, 37.0
        n = 2048
        t = np.arange(n) / fs
        sig = 0.05 * np.sin(2 * np.pi * f0 * t) + 1.0      # +1 g of gravity
        rows = [(int(t[i] * 1e6), sig[i], 0.0, 0.0, 0, 0, 0) for i in range(n)]
        freqs, amp, got_fs, _ = tn.spectrum(rows, axis="x")
        a = np.array(amp); f = np.array(freqs)
        peak = f[np.argmax(a)]
        assert abs(peak - f0) < 1.0, f"tone at {f0} Hz found at {peak:.1f}"
        assert abs(got_fs - fs) < 1.0
        # Hann coherent gain is 0.5; without correcting it every amplitude
        # reads half what it is.
        assert 0.04 < a.max() < 0.06, f"amplitude {a.max():.4f}, expected ~0.05"

    def test_gravity_does_not_appear_as_a_signal(self):
        """DC is 1 g of gravity. Left in, it dwarfs everything structural."""
        import numpy as np
        rows = [(i * 1000, 1.0, 0.0, 0.0, 0, 0, 0) for i in range(512)]
        freqs, amp, _, _ = tn.spectrum(rows, axis="x")
        assert max(amp) < 1e-6, "the DC term was not removed"

    def test_blade_pass_is_distinguishable_from_imbalance(self):
        assert tn.blade_pass_hz(600, blades=3) == pytest.approx(30.0)
        assert tn.blade_pass_hz(600, blades=3) != 600 / 60.0


class TestDashboard:
    def test_the_tab_exists_and_is_wired(self):
        assert 'data-p="node"' in HTML and 'id="p-node"' in HTML
        assert "loadNode" in JS and "node: loadNode" in JS
        for cv in ("cv-nd-amb", "cv-nd-t", "cv-nd-fft"):
            assert f'id="{cv}"' in HTML, f"#{cv} missing"
        for route in ("/api/node/state", "/api/node/burst"):
            assert route in APP, f"{route} missing"

    def test_self_heating_is_surfaced_not_buried(self):
        """
        The whole reason this board matters is density, and a self-heated
        reading gives a wrong one that looks perfectly plausible.
        """
        i = JS.index("async function loadNode")
        body = JS[i:i + 3000]
        assert "SELF-HEATING" in body, "the UI never warns about self-heating"
        assert "OFFSET" in body, "it does not say how to fix it"

    def test_the_spectrum_is_drawn_on_a_log_frequency_axis(self):
        i = JS.index("async function runBurst")
        body = JS[i:i + 3000]
        assert "logX: true" in body, \
            "on a linear axis everything below 20 Hz — where blade passing " \
            "and imbalance live — is squeezed into the first tenth"
