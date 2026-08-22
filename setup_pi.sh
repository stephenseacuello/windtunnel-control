#!/usr/bin/env bash
# Bootstrap a Raspberry Pi to talk to the ACS550.
# Run once, then log out and back in for the group change to take effect.
set -euo pipefail

echo "==> serial port permissions"
sudo usermod -aG dialout "$USER"

echo "==> disabling ModemManager"
# On Pi OS Desktop, ModemManager sees a new USB serial device, assumes it is a
# cellular modem, and starts firing AT commands at it. Aimed at a VFD that is
# both useless and rude. This is the single most common cause of a port that
# opens but never answers.
sudo systemctl disable --now ModemManager 2>/dev/null || echo "    (not installed)"

echo "==> udev rule for a stable device name"
# Without this the cable is /dev/ttyUSB0 until someone plugs in a second USB
# serial device, at which point it silently becomes ttyUSB1 and your scripts
# talk to the wrong thing. Keyed to the FTDI cable's own serial number.
SERIAL=$(udevadm info -a -n /dev/ttyUSB0 2>/dev/null \
         | grep -m1 'ATTRS{serial}' | cut -d'"' -f2 || true)
if [ -n "$SERIAL" ]; then
  echo "    found FTDI serial: $SERIAL"
  echo "SUBSYSTEM==\"tty\", ATTRS{idVendor}==\"0403\", ATTRS{serial}==\"$SERIAL\", SYMLINK+=\"ttyVFD\"" \
    | sudo tee /etc/udev/rules.d/99-windtunnel.rules > /dev/null
  sudo udevadm control --reload-rules && sudo udevadm trigger
  echo "    cable will appear as /dev/ttyVFD"
else
  echo "    no FTDI cable found on ttyUSB0 — plug it in and re-run to get /dev/ttyVFD"
fi

echo "==> python environment"
# Bookworm enforces PEP 668, so a bare pip install into the system python is
# refused. A venv is the correct answer, not --break-system-packages.
python3 -m venv ~/tunnel
source ~/tunnel/bin/activate
pip install --upgrade pip --quiet
pip install -r "$(dirname "$0")/requirements.txt"

cat <<'DONE'

Setup complete.

  Log out and back in (the dialout group change needs a new session).
  Then:

    source ~/tunnel/bin/activate
    cd src
    python run.py --port /dev/ttyVFD monitor

  Note: do NOT put the Pi on a UPS. If it loses power you want it to die
  hard, so the drive's comm watchdog stops the fan. Battery-backing the
  controller defeats that safety property.
DONE
