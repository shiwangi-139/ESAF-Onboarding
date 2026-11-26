"""Upload pipeline: check what the file really is, rebuild it as a clean JPEG, optionally virus-scan it.

Re-encoding from decoded pixels is the main defence: scripts, polyglot files and metadata can't survive it.
"""
import io
import subprocess

from PIL import Image, ImageOps

import config

try:
    import pillow_heif
    pillow_heif.register_heif_opener()
except ImportError:
    pass

Image.MAX_IMAGE_PIXELS = 50_000_000  # blocks decompression bombs
ALLOWED_FORMATS = {"JPEG", "MPO", "PNG", "WEBP", "HEIF"}
MAX_SIDE = 2000


class UploadRejected(Exception):
    def __init__(self, code):
        super().__init__(code)
        self.code = code


def _gps(img):
    try:
        gps = img.getexif().get_ifd(0x8825)
        if not gps or 2 not in gps or 4 not in gps:
            return None

        def deg(values, ref):
            d, m, s = (float(v) for v in values)
            value = d + m / 60 + s / 3600
            return -value if ref in ("S", "W") else value

        return deg(gps[2], gps.get(1, "N")), deg(gps[4], gps.get(3, "E"))
    except Exception:
        return None


def process_image(raw: bytes):
    if len(raw) > config.MAX_UPLOAD_MB * 1024 * 1024:
        raise UploadRejected("too_large")
    try:
        probe = Image.open(io.BytesIO(raw))
        fmt = probe.format
        probe.verify()
        img = Image.open(io.BytesIO(raw))
        img.load()
    except Exception:
        raise UploadRejected("not_an_image")
    if fmt not in ALLOWED_FORMATS:
        raise UploadRejected("not_an_image")

    gps = _gps(img)
    img = ImageOps.exif_transpose(img).convert("RGB")
    img.thumbnail((MAX_SIDE, MAX_SIDE))
    out = io.BytesIO()
    img.save(out, "JPEG", quality=85, optimize=True)  # no exif= argument, so all metadata is dropped
    data = out.getvalue()
    return {"data": data, "width": img.width, "height": img.height, "gps": gps, "scan_status": scan(data)}


def scan(data: bytes) -> str:
    if not config.CLAMAV_ENABLED:
        return "skipped"
    try:
        result = subprocess.run(["clamdscan", "--no-summary", "--fdpass", "-"], input=data,
                                capture_output=True, timeout=60)
    except (OSError, subprocess.TimeoutExpired):
        raise UploadRejected("scan_unavailable")
    if result.returncode == 0:
        return "clean"
    if result.returncode == 1:
        raise UploadRejected("infected")
    raise UploadRejected("scan_unavailable")
