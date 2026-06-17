# Enabling Developer / LAN Mode on a Bambu printer

Third-party LAN printing (what this skill does) needs the printer's legacy
local control path. Since **January 2025**, Bambu firmware ships an
**Authorization Control System** that gates *starting a print* (and motion / fan
/ hotend / AMS control) behind Bambu's own client. To restore scriptable LAN
control you must enable **Developer Mode** (a.k.a. "LAN Mode (Developer)").

- **Status/monitoring** over MQTT is *not* gated — `monitor.py` works regardless.
- **Starting a print** *is* gated — `send.py` needs Developer Mode (or it will
  fail to initiate the print).
- Developer Mode is **LAN-only**: the printer will not be cloud-connected while
  it is on. That is expected and fine for this skill.

## How to enable

The exact menu wording varies by model and firmware. General path:

1. On the printer touchscreen: **Settings → General** (or **Network**).
2. Find **"LAN Mode" / "LAN Only Mode"** and enable it. Note the **Access Code**
   shown — that is your `access_code`.
3. If present, enable **"Developer Mode"** / **"LAN Mode (Developer)"**. On some
   firmware this is a separate toggle that appears once LAN Mode is on.
4. Note the printer **IP** (Settings → WLAN) and **serial** (Settings → Device).

### Model notes

- **X1 / X1C / X1E:** Settings → General → "LAN Only Mode"; Developer Mode toggle
  appears alongside it on recent firmware.
- **P1P / P1S:** Settings → (gear) → "LAN Only Mode" + access code.
- **A1 / A1 mini:** Settings → LAN Only Mode + access code.
- **H2 series / X2D (2026):** the LAN settings live under **Settings → LAN Mode**
  (not under WLAN). Concrete steps:
  1. On the touchscreen: **Settings → LAN Mode**.
  2. Toggle **LAN Only Mode** on. **Power-cycle the printer** the first time.
  3. Back in **Settings → LAN Mode**, toggle **Developer Mode** on. Read the
     **Important Notice / risk warning**, check "I confirm reading and
     understanding…", then **Enable Developer Mode**. (Developer Mode opens the
     MQTT control channel + FTP that this skill needs to *start* a print.)
  4. The **Access Code** is shown on that same LAN Mode screen — copy it into
     `BAMBU_ACCESS_CODE` / `bambu.toml`. If it shows all zeros, toggle LAN Only
     Mode off and on to refresh it.

  Official references: <https://wiki.bambulab.com/en/knowledge-sharing/enable-lan-mode>
  and <https://wiki.bambulab.com/en/knowledge-sharing/enable-developer-mode>

## If `send.py` still fails to start a print

- Confirm Developer Mode is actually ON (not just LAN Mode).
- Confirm the **access code** matches what the screen shows now (it can rotate).
- Confirm `ip` and `serial` are correct and the printer is on the same subnet.
- As a fallback, Bambu's own **Bambu Connect** client can initiate prints, but it
  is not scriptable from this skill.
