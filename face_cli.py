#!/usr/bin/env python3
"""Watch-face builder for MoYoung / Da Fit "type C" 240x280 faces (Noise Icon Buzz).

ONE COMMAND: builds the face, packs it with dawft (auto-cloned/built on first run) and
uploads it to the watch over Bluetooth LE (protocol from DaFup by Vic, GPL-3.0).

  python face_cli.py --bg original.png --cutout cutout.png \
      --clock-color 255,200,0 --hr-color "#ff3355" --clock-size 64 --out face_out

  --no-upload            build only (face_out/face.bin + preview.png)
  --upload-file X.bin    upload an existing face (e.g. from a laptop with Bluetooth)
  --address F8:1D:...    skip scanning; --yes skips the confirmation prompt
  requires: Pillow; for upload: bleak (pip install bleak). No compiler needed (built-in packer).

DEPTH EFFECT (no transparency needed): this face format has no alpha channel, so a
"subject layer above the clock" can't be a real layer. Instead each clock slot (H1,H2,
M1,M2) has its own 10 digit sprites, and every sprite is baked as
    background crop -> digit -> subject pixels pasted back on top
so the live clock appears to pass behind your subject.

Heart-rate digits share ONE sprite set across all positions, so they are drawn on a
flat fill (--hr-fill, default = average background colour of that corner).

Outputs in --out:
  dawft/            watchface.txt + BMP sprites (feed to `dawft create`)
  preview.png       exactly what the watch will draw for --time-sample / --hr-sample
  preview_140x163.png  (also stored inside dawft/ as the last blob)
"""
import argparse, asyncio, os, re, shutil, subprocess, sys
from PIL import Image, ImageDraw, ImageFont, ImageStat

W, H = 240, 280


# ---------- helpers ----------
def parse_color(s):
    s = s.strip()
    m = re.fullmatch(r"#?([0-9a-fA-F]{6})", s)
    if m:
        h = m.group(1)
        return tuple(int(h[i:i + 2], 16) for i in (0, 2, 4))
    p = re.split(r"[,\s]+", s)
    if len(p) == 3 and all(x.isdigit() and 0 <= int(x) <= 255 for x in p):
        return tuple(int(x) for x in p)
    sys.exit(f"bad colour '{s}': use R,G,B (0-255) or #RRGGBB")


def fit_cover(im, w=W, h=H):
    sc = max(w / im.width, h / im.height)
    nw, nh = round(im.width * sc), round(im.height * sc)
    im = im.resize((nw, nh), Image.LANCZOS)
    l, t = (nw - w) // 2, (nh - h) // 2
    return im.crop((l, t, l + w, t + h))


ORBITRON_URL = ("https://raw.githubusercontent.com/google/fonts/main/ofl/orbitron/"
                "Orbitron%5Bwght%5D.ttf")


def ensure_orbitron():
    cache = os.path.join(os.path.expanduser("~"), ".cache", "face_cli")
    path = os.path.join(cache, "Orbitron.ttf")
    if os.path.exists(path) and os.path.getsize(path) > 10000:
        return path
    print("downloading Orbitron font (one time)...")
    try:
        import urllib.request
        os.makedirs(cache, exist_ok=True)
        urllib.request.urlretrieve(ORBITRON_URL, path)
        if os.path.getsize(path) > 10000:
            return path
    except Exception as e:
        print(f"WARNING: could not download Orbitron ({e}). Falling back to a default font; "
              "download Orbitron yourself and pass --font /path/Orbitron.ttf")
    return None


def load_font(path, size, weight=None):
    if path and path.lower() == "orbitron":
        path = ensure_orbitron()
    for c in ([path] if path else []) + [
            "DejaVuSans-Bold.ttf", "/system/fonts/Roboto-Bold.ttf",
            "/system/fonts/DroidSans-Bold.ttf",
            "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"]:
        try:
            f = ImageFont.truetype(c, size)
        except (OSError, TypeError):
            continue
        if weight and c == path:
            try:
                f.set_variation_by_axes([weight])  # variable fonts (Orbitron: 400..900, Black=900)
            except Exception:
                print("note: this font/Pillow build can't set weight; using the font's default weight")
        return f
    try:
        return ImageFont.load_default(size)
    except TypeError:
        return ImageFont.load_default()


def cap_metrics(font):
    """(max digit advance width, cap height) for 0-9."""
    ws, tops, bots = [], [], []
    for c in "0123456789":
        l, t, r, b = font.getbbox(c, anchor="ls")  # relative to baseline
        ws.append(r - l)
        tops.append(t)
        bots.append(b)
    return max(ws), -min(tops), max(bots)  # width, ascent above baseline, descent below


def bake(bg, fg, rect, painter):
    """bg crop -> painter draws on it -> subject pasted on top -> opaque RGB."""
    x, y, w, h = rect
    tile = bg.crop((x, y, x + w, y + h)).convert("RGBA")
    painter(tile)
    if fg is not None:
        tile.alpha_composite(fg.crop((x, y, x + w, y + h)))
    return tile.convert("RGB")


def _alpha(op):
    return max(0, min(255, round(255 * op)))


def digit_painter(ch, font, color, base_y, opacity=1.0, native_w=None):
    """Draw one glyph with opacity; native_w lets us render wide then squeeze (condensed look)."""
    def paint(tile):
        w, h = tile.size
        nw = native_w or w
        layer = Image.new("RGBA", (nw, h), (0, 0, 0, 0))
        ImageDraw.Draw(layer).text((nw / 2, base_y), ch, font=font,
                                   fill=color + (_alpha(opacity),), anchor="ms")
        if nw != w:
            layer = layer.resize((w, h), Image.LANCZOS)
        tile.alpha_composite(layer)
    return paint


def colon_painter(color, r, opacity=1.0):
    def paint(tile):
        w, h = tile.size
        layer = Image.new("RGBA", (w, h), (0, 0, 0, 0))
        d = ImageDraw.Draw(layer)
        cx = w / 2
        for cy in (h * 0.34, h * 0.66):
            d.rectangle((cx - r, cy - r, cx + r, cy + r), fill=color + (_alpha(opacity),))
        tile.alpha_composite(layer)
    return paint


def heart_painter(color, opacity=1.0):
    def paint(tile):
        w, h = tile.size
        s = min(w, h)
        r = s // 4
        layer = Image.new("RGBA", (w, h), (0, 0, 0, 0))
        d = ImageDraw.Draw(layer)
        c = color + (_alpha(opacity),)
        d.ellipse((s * .08, s * .1, s * .08 + 2 * r + 2, s * .1 + 2 * r + 2), fill=c)
        d.ellipse((s * .92 - 2 * r - 2, s * .1, s * .92, s * .1 + 2 * r + 2), fill=c)
        d.polygon([(s * .06, s * .38), (s * .94, s * .38), (s * .5, s * .92)], fill=c)
        tile.alpha_composite(layer)
    return paint


def flat_tile(size, fill, painter):
    t = Image.new("RGBA", size, tuple(fill) + (255,))
    painter(t)
    return t.convert("RGB")


# ---------- pure-Python packer (replaces dawft `create`, type C, uncompressed) ----------
HEADER_SIZE = 1900


def rgb565_be(im):
    """RGB image -> raw RGB565 bytes, high byte first, rows top-down (what dawft writes)."""
    im = im.convert("RGB")
    d = im.tobytes()
    out = bytearray(im.width * im.height * 2)
    j = 0
    for i in range(0, len(d), 3):
        v = ((d[i] & 0xF8) << 8) | ((d[i + 1] & 0xFC) << 3) | (d[i + 2] >> 3)
        out[j] = v >> 8
        out[j + 1] = v & 0xFF
        j += 2
    return bytes(out)


def pack_face(path, file_id, face_number, entries, images):
    """entries: [(type, blob_idx, x, y, w, h)], images: PIL images in blob-index order."""
    import struct
    if len(entries) > 39 or len(images) > 250:
        sys.exit("too many elements/blobs for this face format")
    hdr = bytearray(HEADER_SIZE)
    hdr[0], hdr[1], hdr[2] = file_id & 0xFF, len(entries), len(images)
    struct.pack_into("<H", hdr, 3, face_number)
    for i, (t, idx, x, y, w, h) in enumerate(entries):
        struct.pack_into("<BBHHHH", hdr, 5 + 10 * i, t, idx, x, y, w, h)
    blobs, off = [], 0
    for i, im in enumerate(images):
        raw = rgb565_be(im)
        struct.pack_into("<I", hdr, 400 + 4 * i, off)
        blobs.append(raw)
        off += len(raw)
    with open(path, "wb") as f:
        f.write(hdr)
        for b in blobs:
            f.write(b)
    return HEADER_SIZE + off


# ---------- dawft (optional cross-check) ----------
DAWFT_URL = "https://github.com/david47k/dawft"


def ensure_dawft(path=None):
    """Return a runnable dawft binary: given path, PATH, cache, or clone+build it."""
    if path:
        if os.path.exists(path):
            return os.path.abspath(path)
        sys.exit(f"--dawft path not found: {path}")
    found = shutil.which("dawft")
    if found:
        return found
    cache = os.path.join(os.path.expanduser("~"), ".cache", "face_cli", "dawft")
    exe = os.path.join(cache, "dawft")
    if os.path.exists(exe):
        return exe
    print("dawft not found -> cloning and building it (one time)...")
    for tool in ("git", "make"):
        if not shutil.which(tool):
            sys.exit(f"need '{tool}' to build dawft (Termux: pkg install git make clang)")
    os.makedirs(os.path.dirname(cache), exist_ok=True)
    shutil.rmtree(cache, ignore_errors=True)
    subprocess.run(["git", "clone", "--depth", "1", DAWFT_URL, cache], check=True)
    target = "release" if shutil.which("clang") else "release-gcc"
    if target == "release-gcc" and not shutil.which("gcc"):
        sys.exit("need clang or gcc to build dawft (Termux: pkg install clang)")
    r = subprocess.run(["make", target], cwd=cache, capture_output=True, text=True)
    if r.returncode != 0:
        sys.exit("dawft build failed:\n" + (r.stdout + r.stderr)[-1200:])
    if not os.path.exists(exe):
        sys.exit("dawft build finished but binary not found")
    return exe


# ---------- BLE upload (protocol from DaFup by Vic, GPL-3.0) ----------
def _uuid16(n):
    return f"0000{n:04x}-0000-1000-8000-00805f9b34fb"


CTRCHAR, SNDCHAR, MANCHAR, NTYCHAR = _uuid16(0xFEE2), _uuid16(0xFEE6), _uuid16(0x2A29), _uuid16(0xFEE3)


async def _pick_device(address):
    """Scan and return the BLEDevice object (more reliable than an address string, esp. on Windows)."""
    from bleak import BleakScanner
    print("scanning for the watch (8 s)...")
    found = await BleakScanner.discover(timeout=8, return_adv=True)
    devs = [(d, d.name or adv.local_name or "?") for d, adv in found.values()]
    if address:
        for d, _ in devs:
            if d.address.lower() == address.lower():
                return d
        print("address not seen in the scan; trying a direct connect")
        return address
    keys = ("buzz", "noise", "icon", "moy")
    cands = [x for x in devs if any(k in x[1].lower() for k in keys)]
    pool = cands if cands else devs
    if len(cands) == 1:
        print(f"using {cands[0][1]} [{cands[0][0].address}]")
        return cands[0][0]
    if not pool:
        sys.exit("no Bluetooth LE devices found. Is the watch awake and the phone's Bluetooth off?")
    for i, (d, name) in enumerate(pool):
        print(f"  [{i}] {name}  {d.address}")
    n = input("pick device number (q to quit): ").strip()
    if not n.isdigit() or int(n) >= len(pool):
        sys.exit("cancelled")
    return pool[int(n)][0]


CHUNK = 244                          # bytes per chunk the watch asks for
PREP = bytes.fromhex("feea200974")   # start transfer / "all done" (+ 4-byte size or checksum)
REQ = bytes.fromhex("feea200774")    # watch -> host: ready for chunk N (u16 big-endian)


async def _send(c, data, set_face):
    """Flow-controlled upload as in dawfu (MIT, david47k): the WATCH requests each chunk."""
    try:
        man = bytes(await c.read_gatt_char(MANCHAR)).decode("utf-8", "replace")
    except Exception:
        sys.exit("not a MoYoung device (manufacturer characteristic missing)")
    if man != "MOYOUNG-V2":
        sys.exit(f"watch reports '{man}', this uploader supports MOYOUNG-V2 only")
    q = asyncio.Queue()
    await c.start_notify(NTYCHAR, lambda _s, d: q.put_nowait(bytes(d)))
    try:
        mtu = int(getattr(c, "mtu_size", 23) or 23)
    except Exception:
        mtu = 23
    max_write = max(20, min(CHUNK, mtu - 3))
    nchunks = (len(data) + CHUNK - 1) // CHUNK
    print(f"connected, MOYOUNG-V2. link MTU={mtu}; {len(data)} bytes = {nchunks} chunks of {CHUNK}"
          + (f" (each split into {max_write}-byte writes)" if max_write < CHUNK else ""))
    await c.write_gatt_char(CTRCHAR, PREP + len(data).to_bytes(4, "big"), response=False)
    expected, shown = 0, -1
    while True:
        try:
            msg = await asyncio.wait_for(q.get(), timeout=30)
        except asyncio.TimeoutError:
            raise TimeoutError("the watch stopped requesting data for 30 s")
        if msg[:5] == PREP:
            if expected < nchunks - 1:
                print(f"\nwarning: received PREP when only {expected}/{nchunks} chunks sent; ignoring stale notification")
                continue
            print(f"\r100%  watch received everything (checksum {msg[5:9].hex() or 'n/a'})")
            await c.write_gatt_char(CTRCHAR, PREP + b"\x00\x00\x00\x00", response=False)
            break
        if msg[:5] == REQ and len(msg) >= 7:
            n = int.from_bytes(msg[5:7], "big")
            if n != expected:
                print(f"\nwarning: expected a request for chunk {expected}, watch asked for {n}")
            expected = n + 1
            part = data[n * CHUNK:(n + 1) * CHUNK]
            for off in range(0, len(part), max_write):
                await c.write_gatt_char(SNDCHAR, part[off:off + max_write], response=False)
            pct = int(100 * n / max(1, nchunks))
            if pct != shown:
                shown = pct
                print(f"\r{pct:3d}%", end="", flush=True)
        else:
            print(f"\nnote: unexpected message from watch: {msg.hex()}")
    if set_face:
        await c.write_gatt_char(CTRCHAR, bytes.fromhex("feea2006190d"), response=False)  # select the face
    await asyncio.sleep(1)


async def _upload(binpath, address, set_face=True):
    from bleak import BleakClient
    from bleak.exc import BleakError
    data = open(binpath, "rb").read()
    last = None
    for attempt in range(1, 4):
        dev = await _pick_device(address)   # fresh scan each try
        try:
            async with BleakClient(dev, timeout=25) as c:
                await _send(c, data, set_face)
            print("upload finished. Open the watch's face list and look at the last face.")
            return
        except (BleakError, asyncio.TimeoutError, OSError) as e:
            last = e
            print(f"\nattempt {attempt}/3 failed: {type(e).__name__}: {e}")
            await asyncio.sleep(3)
    raise last


def upload(binpath, address=None):
    try:
        import bleak  # noqa: F401
    except ImportError:
        sys.exit("upload needs the 'bleak' package:  pip install bleak\n"
                 "(on Termux, Bluetooth LE is usually unavailable -> run this from a laptop with "
                 f"--upload-file {binpath})")
    try:
        asyncio.run(_upload(binpath, address))
    except SystemExit:
        raise
    except Exception as e:
        sys.exit(f"upload failed: {type(e).__name__}: {e}\n"
                 "Turn OFF the phone's Bluetooth (or forget 'Icon Buzz_Phone'), keep the watch awake and near, "
                 f"then retry with:  python face_cli.py --upload-file {binpath}")


# ---------- main ----------
def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--bg", help="original image path (required unless --upload-file)")
    ap.add_argument("--upload-file", help="skip building; just upload this existing face .bin")
    ap.add_argument("--no-upload", action="store_true", help="build only, don't send to the watch")
    ap.add_argument("--address", help="watch BLE address (default: auto-scan; e.g. F8:1D:5F:5F:17:38)")
    ap.add_argument("--yes", action="store_true", help="don't ask for confirmation before uploading")
    ap.add_argument("--cutout", help="background-removed PNG, same framing as --bg (enables depth effect)")
    ap.add_argument("--clock-color", default="255,255,255")
    ap.add_argument("--clock-opacity", type=float, default=82, help="percent 0-100 (default 82)")
    ap.add_argument("--clock-size", type=int, default=165, help="clock font size px (digit height ~0.72x)")
    ap.add_argument("--clock-condense", type=float, default=0.42,
                    help="squeeze digit width (1.0 = normal, 0.42 = tall/narrow like the reference)")
    ap.add_argument("--clock-y", type=int, default=26, help="top y of clock row")
    ap.add_argument("--font", default="orbitron", help="clock font: 'orbitron' (auto-download) or a .ttf path")
    ap.add_argument("--font-weight", type=int, default=900, help="variable-font weight (Orbitron Black=900)")
    ap.add_argument("--hr-color", default="255,255,255")
    ap.add_argument("--hr-opacity", type=float, default=100)
    ap.add_argument("--hr-fill", help="flat fill behind heart-rate digits R,G,B (default: avg bg colour)")
    ap.add_argument("--hr-font", help="font for heart rate/date (.ttf path; default: bold system font)")
    ap.add_argument("--hr-size", type=int, default=20)
    ap.add_argument("--hr-align", choices=["left", "right"], default="right",
                    help="right = type 0x67 (documented); left = type 0x65 ('assumed' in dawft docs)")
    ap.add_argument("--hr-x", type=int, help="override heart-rate x (see note in output)")
    ap.add_argument("--hr-y", type=int, default=6)
    ap.add_argument("--date", action="store_true", help="add a live date DD-MM-YY (horizontal)")
    ap.add_argument("--date-color", default="255,255,255")
    ap.add_argument("--date-opacity", type=float, default=82)
    ap.add_argument("--date-size", type=int, default=14)
    ap.add_argument("--date-x", type=int, default=6)
    ap.add_argument("--date-y", type=int, default=6)
    ap.add_argument("--time-sample", default="10:55")
    ap.add_argument("--hr-sample", default="72")
    ap.add_argument("--file-type", default="C", help="dawft fileType (A/B/C); only C can be created")
    ap.add_argument("--file-id", default="0x81")
    ap.add_argument("--face-number", type=int, default=50010)
    ap.add_argument("--rle", action="store_true",
                    help="compress sprites with RLE (needs dawft; much smaller file)")
    ap.add_argument("--bg-only", action="store_true",
                    help="TEST MODE: face with only the background image (isolates transfer/format problems)")
    ap.add_argument("--no-preview-blob", action="store_true",
                    help="don't append the 140x163 preview as the last blob")
    ap.add_argument("--dawft", help="path to built dawft binary; if given, also creates face.bin")
    ap.add_argument("--out", default="myface")
    a = ap.parse_args()

    if a.upload_file:
        upload(a.upload_file, a.address)
        return
    if not a.bg:
        ap.error("--bg is required (or use --upload-file)")
    clock_c, hr_c = parse_color(a.clock_color), parse_color(a.hr_color)
    c_op, h_op, d_op = a.clock_opacity / 100, a.hr_opacity / 100, a.date_opacity / 100
    out = os.path.abspath(a.out)
    df = os.path.join(out, "dawft")
    shutil.rmtree(df, ignore_errors=True)
    os.makedirs(df)

    src = Image.open(a.bg)
    bg = fit_cover(src.convert("RGB"))
    fg = None
    if a.cutout:
        cut = Image.open(a.cutout).convert("RGBA")
        if cut.size != src.size:
            print(f"note: cutout {cut.size} != original {src.size}; resizing cutout")
            cut = cut.resize(src.size, Image.LANCZOS)
        fg = fit_cover(cut)

    # --- small font (heart rate + date) ---
    hfont = load_font(a.hr_font, a.hr_size)

    # --- optional live date: static dashes and "20" are drawn into the background ---
    date_info = None
    if a.date:
        dcolor = parse_color(a.date_color)
        dfont = load_font(a.hr_font, a.date_size)
        ddw, dasc, ddesc = cap_metrics(dfont)
        dwd, dht = ddw + 2, dasc + ddesc + 4
        ew = 2 * dwd + 2
        items = [("DD", ew), ("-", dwd), ("MM", ew), ("-", dwd), ("20", ew), ("YY", ew)]
        gap = 2
        dtotal = sum(w for _, w in items) + gap * (len(items) - 1)
        dx, dy = a.date_x, a.date_y
        if dx + dtotal > W or dy + dht > H:
            sys.exit(f"date ({dtotal}px wide) does not fit at x={dx}: lower --date-size or change --date-x/--date-y")
        dfill = tuple(int(v) for v in ImageStat.Stat(bg.crop((dx, dy, dx + dtotal, dy + dht))).mean[:3])
        layer = Image.new("RGBA", bg.size, (0, 0, 0, 0))
        dl = ImageDraw.Draw(layer)
        x, dpos = dx, {}
        for name, w in items:
            if name in ("-", "20"):
                for k, ch in enumerate(name):
                    dl.text((x + k * (dwd + 2) + dwd / 2, dy + 2 + dasc), ch, font=dfont,
                            fill=dcolor + (_alpha(d_op),), anchor="ms")
            else:
                dpos[name] = x
            x += w + gap
        base = bg.convert("RGBA")
        base.alpha_composite(layer)
        bg = base.convert("RGB")
        date_info = dict(color=dcolor, font=dfont, asc=dasc, w=dwd, h=dht, fill=dfill, pos=dpos, y=dy)

    # --- clock layout ---
    cfont = load_font(a.font, a.clock_size, a.font_weight)
    dw, asc, desc = cap_metrics(cfont)
    sw_native = dw + 6
    cond = a.clock_condense
    while True:
        sw = max(8, round(sw_native * cond))           # slot width on screen
        cw = max(round(sw * 0.45), 12)                 # colon width
        total = 4 * sw + cw
        if total <= W - 8 or cond <= 0.1:
            break
        cond *= 0.98
    if cond < a.clock_condense:
        print(f"note: squeezed clock to --clock-condense {cond:.2f} so it fits the 240px screen")
    sh = asc + desc + 8                                # slot height
    base_y = 4 + asc
    x0 = (W - total) // 2
    ys = a.clock_y
    slots = {"H1": (0x40, x0), "H2": (0x41, x0 + sw),
             "M1": (0x43, x0 + 2 * sw + cw), "M2": (0x44, x0 + 3 * sw + cw)}
    colon_x = x0 + 2 * sw
    if ys + sh > H or x0 < 0:
        sys.exit(f"clock ({total}px wide, {sh}px tall) does not fit: lower --clock-size or change --clock-y")
    print(f"clock: digits {sw}x{sh}px, total width {total}px at y={ys}")

    lines, blob = [], 0

    blobs = []

    def add_bmp(name, im):
        im = im.convert("RGB")
        blobs.append(im)                       # blobs are added in blob-index order
        im.save(os.path.join(df, name), format="BMP")

    # blob 0: background
    add_bmp("background000.bmp", bg)
    lines.append(f"faceData       0x01    000      0    0  {W}  {H}    background000.bmp   # BACKGROUND")
    blob = 1
    sprites = {}
    for name, (code, x) in slots.items():
        sprites[name] = []
        for d in range(10):
            im = bake(bg, fg, (x, ys, sw, sh),
                      digit_painter(str(d), cfont, clock_c, base_y, c_op, native_w=sw_native))
            add_bmp(f"{name.lower()}_{d:03d}.bmp", im)
            sprites[name].append(im)
        lines.append(f"faceData       0x{code:02X}    {blob:03d}   {x:4d} {ys:4d}  {sw:3d}  {sh:3d}    "
                     f"{name.lower()}_000.bmp   # TIME_{name}")
        blob += 10
    colon = bake(bg, fg, (colon_x, ys, cw, sh), colon_painter(clock_c, max(3, round(a.clock_size * 0.04)), c_op))
    add_bmp("colon_000.bmp", colon)
    lines.append(f"faceData       0xF0    {blob:03d}   {colon_x:4d} {ys:4d}  {cw:3d}  {sh:3d}    colon_000.bmp   # SEPERATOR")
    blob += 1

    # --- heart rate digits (shared set -> flat fill) ---
    hdw, hasc, hdesc = cap_metrics(hfont)
    hw, hh = hdw + 2, hasc + hdesc + 4
    spacing = 2
    three = 3 * hw + 2 * spacing
    hx = a.hr_x if a.hr_x is not None else W - 8 - three
    hy = a.hr_y
    if a.hr_fill:
        fill = parse_color(a.hr_fill)
    else:
        region = bg.crop((max(0, hx - hh - 6), hy, W, hy + hh))
        fill = tuple(int(v) for v in ImageStat.Stat(region).mean[:3])
    hr_sprites = []
    for d in range(10):
        t = flat_tile((hw, hh), fill, digit_painter(str(d), hfont, hr_c, 2 + hasc, h_op))
        add_bmp(f"hr_{d:03d}.bmp", t)
        hr_sprites.append(t)
    hcode = 0x67 if a.hr_align == "right" else 0x65
    lines.append(f"faceData       0x{hcode:02X}    {blob:03d}   {hx:4d} {hy:4d}  {hw:3d}  {hh:3d}    hr_000.bmp   # HR digits")
    blob += 10
    lx = max(0, hx - hh - 4)
    logo = bake(bg, fg, (lx, hy, hh, hh), heart_painter(hr_c, h_op))
    add_bmp("logo_000.bmp", logo)
    lines.append(f"faceData       0x81    {blob:03d}   {lx:4d} {hy:4d}  {hh:3d}  {hh:3d}    logo_000.bmp   # HR_LOGO")
    blob += 1

    # --- date digits (one shared set used by day, month and 2-digit year) ---
    date_sprites = []
    if date_info:
        di = date_info
        for d in range(10):
            t = flat_tile((di["w"], di["h"]), di["fill"],
                          digit_painter(str(d), di["font"], di["color"], 2 + di["asc"], d_op))
            add_bmp(f"date_{d:03d}.bmp", t)
            date_sprites.append(t)
        for nm, code in (("DD", 0x30), ("MM", 0x11), ("YY", 0x12)):
            lines.append(f"faceData       0x{code:02X}    {blob:03d}   {di['pos'][nm]:4d} {di['y']:4d}  "
                         f"{di['w']:3d}  {di['h']:3d}    date_000.bmp   # DATE_{nm}")
        blob += 10

    data_count = len(lines)
    # --- preview (exactly what the watch will draw) ---
    prev = bg.copy()
    tstr = re.sub(r"[^0-9]", "", a.time_sample).zfill(4)[:4]
    for i, name in enumerate(["H1", "H2", "M1", "M2"]):
        prev.paste(sprites[name][int(tstr[i])], (slots[name][1], ys))
    prev.paste(colon, (colon_x, ys))
    hs = a.hr_sample[:3]
    px = hx + (three - (len(hs) * hw + (len(hs) - 1) * spacing)) if a.hr_align == "right" else hx
    for ch in hs:
        prev.paste(hr_sprites[int(ch)], (px, hy))
        px += hw + spacing
    prev.paste(logo, (lx, hy))
    if date_info:
        import datetime
        now = datetime.date.today()
        for nm, val in (("DD", f"{now.day:02d}"), ("MM", f"{now.month:02d}"), ("YY", f"{now.year % 100:02d}")):
            xx = date_info["pos"][nm]
            for ch in val:
                prev.paste(date_sprites[int(ch)], (xx, date_info["y"]))
                xx += date_info["w"] + 2
    prev.save(os.path.join(out, "preview.png"))
    pv = fit_cover(prev, 140, 163)
    pv.save(os.path.join(out, "preview_140x163.png"))
    if not a.no_preview_blob:
        add_bmp(f"{blob:03d}.bmp", pv)
        blob += 1

    last_data = blob - (0 if a.no_preview_blob else 1)       # the preview (last blob) stays uncompressed
    comp = "\n".join(f"blobCompression {i:03d}  " + ("TRY_RLE" if (a.rle and 1 <= i < last_data) else "NONE")
                      for i in range(0, blob))
    txt = (f"fileType       {a.file_type}\nfileID         {a.file_id}\n"
           f"dataCount      {data_count}\nblobCount      {blob}\nfaceNumber     {a.face_number}\n\n"
           "#              TYPE  INDEX      X    Y    W    H    FILENAME\n" + "\n".join(lines) +
           "\n\n# uncompressed digits\n#             INDEX  CTYPE\n" + comp + "\n")
    with open(os.path.join(df, "watchface.txt"), "w") as f:
        f.write(txt)
    print(f"wrote {df}  ({blob} blobs)  preview: {out}/preview.png")
    print(f"HR x={hx}, y={hy}, align={a.hr_align}; fill={fill}")

    binp = os.path.join(out, "face.bin")
    entries = []
    for ln in lines:
        p = ln.split("#")[0].split()
        entries.append((int(p[1], 0), int(p[2]), int(p[3]), int(p[4]), int(p[5]), int(p[6])))
    if a.file_type.upper() != "C":
        sys.exit("only file type C can be packed")
    if a.bg_only:
        entries = entries[:1]
        keep = [blobs[0]] + ([] if a.no_preview_blob else [blobs[-1]])
        size = pack_face(binp, int(a.file_id, 0), a.face_number, entries, keep)
        print(f"BG-ONLY test face created ({size} bytes): background" +
              ("" if a.no_preview_blob else " + preview"))
    elif a.rle:
        dawft = ensure_dawft(a.dawft)
        r = subprocess.run([dawft, "create", f"folder={df}", binp], capture_output=True, text=True)
        if not os.path.exists(binp):
            sys.exit("dawft could not create the RLE face:\n" + (r.stdout + r.stderr)[-800:])
        print(f"face.bin created ({os.path.getsize(binp)} bytes) with dawft, RLE-compressed")
    else:
        size = pack_face(binp, int(a.file_id, 0), a.face_number, entries, blobs)
        print(f"face.bin created ({size} bytes) with built-in packer")
    if a.dawft and not (a.rle or a.bg_only):  # optional cross-check with the real dawft tool
        dawft = ensure_dawft(a.dawft)
        chk = os.path.join(out, "face_dawft.bin")
        subprocess.run([dawft, "create", f"folder={df}", chk], capture_output=True, text=True)
        same = os.path.exists(chk) and open(chk, "rb").read() == open(binp, "rb").read()
        print("dawft cross-check:", "IDENTICAL" if same else "DIFFERENT (report this)")

    if a.no_upload:
        print(f"skipped upload. Later: python face_cli.py --upload-file {binp}")
        return
    print("\nThis REPLACES the watch's custom-face slot. Close NoiseFit first (one BLE link at a time).")
    if not a.yes and input("send to the watch now? [y/N] ").strip().lower() != "y":
        print(f"not sent. Later: python face_cli.py --upload-file {binp}")
        return
    upload(binp, a.address)


if __name__ == "__main__":
    main()
