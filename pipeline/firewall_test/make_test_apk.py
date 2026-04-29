"""Create a minimal valid APK for firewall blocking tests.

Purpose: lets the boss try downloading an .apk file from a URL to determine
whether his corporate firewall / EDR / MDM blocks APK downloads. The file is
intentionally empty -- it has the right ZIP magic, the right .apk extension,
a stub AndroidManifest.xml, and a stub META-INF directory so any "looks like
an APK" filter triggers, but it's not a runnable Android app.

Output: firewall_test.apk in the same folder. ~1.2 KB.

Usage:
    python make_test_apk.py
"""
from __future__ import annotations

import hashlib
import zipfile
from pathlib import Path

OUTPUT_NAME = "firewall_test.apk"

# Minimal binary AndroidManifest.xml stub. Not a valid AXML resource, but enough
# bytes that magic-byte and extension scanners both fire. The real Android binary
# XML format starts with 03 00 08 00; we set that prefix so the magic detector
# triggers, then fill with neutral bytes.
ANDROID_MANIFEST = (
    b"\x03\x00\x08\x00"   # AXML magic
    b"\x60\x01\x00\x00"   # file size placeholder
    b"firewall-test-stub-this-apk-is-empty-and-does-nothing-when-installed"
)

# Minimal META-INF manifest. Real APKs sign their contents; an unsigned APK
# still scans as APK to anything looking at extension or zip-with-AndroidManifest.
META_INF_MANIFEST = (
    b"Manifest-Version: 1.0\r\n"
    b"Created-By: stock-firewall-test 1.0\r\n"
    b"\r\n"
    b"Name: AndroidManifest.xml\r\n"
    b"SHA-256-Digest: " + hashlib.sha256(ANDROID_MANIFEST).hexdigest().encode() + b"\r\n"
    b"\r\n"
)


def main() -> None:
    """Build firewall_test.apk in the script's directory."""
    out_path = Path(__file__).parent / OUTPUT_NAME
    with zipfile.ZipFile(out_path, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        # Order matters for some scanners: AndroidManifest first, then META-INF.
        zf.writestr("AndroidManifest.xml", ANDROID_MANIFEST)
        zf.writestr("META-INF/MANIFEST.MF", META_INF_MANIFEST)
        # Empty resources.arsc so apk-aware scanners see the third standard file.
        zf.writestr("resources.arsc", b"")

    size = out_path.stat().st_size
    sha = hashlib.sha256(out_path.read_bytes()).hexdigest()
    print(f"Wrote {out_path} ({size} bytes)")
    print(f"SHA-256: {sha}")
    print()
    print("This file is intentionally empty -- it cannot install anything.")
    print("Use it only to test whether a network/firewall blocks APK downloads.")


if __name__ == "__main__":
    main()
