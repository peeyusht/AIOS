"""
A release of the device agent, and how anyone checks that it is ours.

A release is three things: the installer (an .msi), a manifest (a short JSON text naming the version, the
file, its size and its SHA-256) and a signature over the exact bytes of the manifest, made with the release
key. The private half of that key is kept off the server (`release-key.private.pem`, never committed, never
in an image); the public halves are the constants below, built into every agent.

So a fleet server only passes a release on. A server that was broken into can withhold an update, but it
cannot make a PC install something else: the agent installs only what `verify()` accepts, only a version
higher than its own, and only a file whose size and hash are the ones the signed manifest states.

Used by the agent (selfupdate.py), the build (build/make_release.py) and the server (`manage release`,
which refuses to publish what it cannot verify).
"""
import base64
import hashlib
import json

PRODUCT = "ShadowFiler Agent"
MAX_PACKAGE = 200 * 1024 * 1024
# Ed25519 public keys, base64 of the 32 raw bytes. More than one only while a key is being replaced.
RELEASE_KEYS = ("2YHYy2zf+Zp5vxh+DMhYZsjG/zKm8ewub7SaprpAMgo=",)


def version_tuple(v) -> tuple | None:
    """'1.4.2' -> (1, 4, 2). Three plain numbers and nothing else, which is also what Windows Installer compares."""
    parts = str(v or "").split(".")
    if len(parts) != 3 or not all(p.isascii() and p.isdigit() and len(p) <= 5 for p in parts):
        return None
    return tuple(int(p) for p in parts)


def newer(candidate, installed) -> bool:
    a, b = version_tuple(candidate), version_tuple(installed)
    return a is not None and b is not None and a > b


def manifest(version: str, file_name: str, data: bytes) -> str:
    if version_tuple(version) is None:
        raise ValueError("A version is three numbers, like 1.4.2.")
    return json.dumps({"product": PRODUCT, "version": version, "file": file_name, "size": len(data),
                       "sha256": hashlib.sha256(data).hexdigest()}, sort_keys=True)


def sign(manifest_text: str, private_pem: bytes) -> str:
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
    from cryptography.hazmat.primitives.serialization import load_pem_private_key
    key = load_pem_private_key(private_pem, password=None)
    if not isinstance(key, Ed25519PrivateKey):
        raise ValueError("The release key must be an Ed25519 key.")
    return base64.b64encode(key.sign(manifest_text.encode("utf-8"))).decode("ascii")


def public_of(private_pem: bytes) -> str:
    from cryptography.hazmat.primitives import serialization
    key = serialization.load_pem_private_key(private_pem, password=None)
    return base64.b64encode(key.public_key().public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw)).decode("ascii")


def verify(manifest_text: str, signature: str, keys=None) -> dict:
    """The manifest as a dict, if one of our release keys signed exactly this text. ValueError otherwise."""
    from cryptography.exceptions import InvalidSignature
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
    try:
        sig = base64.b64decode(str(signature or ""), validate=True)
    except ValueError:
        raise ValueError("The release's signature is not readable.") from None
    data = str(manifest_text or "").encode("utf-8")
    for k in keys or RELEASE_KEYS:
        try:
            Ed25519PublicKey.from_public_bytes(base64.b64decode(k)).verify(sig, data)
            break
        except (InvalidSignature, ValueError):
            continue
    else:
        raise ValueError("The release is not signed with a release key this agent knows.")
    try:
        m = json.loads(manifest_text)
    except ValueError:
        raise ValueError("The release's manifest is not readable.") from None
    name = m.get("file") if isinstance(m, dict) else None
    if (not isinstance(m, dict) or m.get("product") != PRODUCT or version_tuple(m.get("version")) is None
            or not isinstance(name, str) or not name.endswith(".msi") or name != name.strip() or len(name) > 100
            or any(ch in name for ch in '/\\:*?"<>|%') or name.startswith(".")
            or not isinstance(m.get("size"), int) or isinstance(m.get("size"), bool) or not 0 < m["size"] <= MAX_PACKAGE
            or not isinstance(m.get("sha256"), str) or len(m["sha256"]) != 64):
        raise ValueError("The release's manifest does not describe an installer of this agent.")
    return m


def check_package(m: dict, data: bytes) -> None:
    if len(data) != m["size"] or hashlib.sha256(data).hexdigest() != m["sha256"]:
        raise ValueError("The installer is not the file the signed manifest describes.")
