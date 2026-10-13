"""
The device agent updates itself, and this is all of it.

After a report the server names the newest agent version it offers. If that is higher than the version
running, the agent fetches the release's manifest and checks it the way release.py describes: signed with the
release key (whose private half is on no server), for this product, for a version higher than its own. Only
then does it fetch the installer, check its size and SHA-256 against the signed manifest, and hand it to
Windows Installer, which stops the service, replaces the files and starts it again.

What a server can do with this, even one that was broken into: offer a real release, or none. It cannot make
the agent install anything else, and it cannot take the agent back to an older release.

Limits on purpose: a version is tried at most three times, six hours apart; `sfagent updates off` stops it;
it runs only in the installed service, never in a development run.
"""
import json
import os
import subprocess
from datetime import datetime, timedelta
from pathlib import Path

import fleet
import release

TRIES, WAIT_HOURS = 3, 6


def run_installer(package: Path, log_file: Path) -> None:
    """Hand the installer to Windows Installer, silently, and let go: it will stop this service."""
    msiexec = os.path.join(os.environ.get("SystemRoot", r"C:\Windows"), "System32", "msiexec.exe")
    args = [msiexec, "/i", str(package), "/qn", "/norestart", "/l*v", str(log_file)]
    flags = 0x00000008 | 0x00000200          # no console of ours, a process group of its own
    try:
        subprocess.Popen(args, creationflags=flags | 0x01000000, close_fds=True)       # and outside the service's job, if allowed
    except OSError:
        subprocess.Popen(args, creationflags=flags, close_fds=True)


def tidy(folder: Path) -> None:
    """Installers of earlier updates are not kept."""
    for f in folder.glob("*.msi") if folder.is_dir() else []:
        try:
            f.unlink()
        except OSError:
            pass


def maybe(cfg: dict, version: str, folder: Path, log=None, installed: bool = True, install=run_installer,
          call=None, now: datetime | None = None, keys=None) -> str:
    """Update if the server offers a newer, properly signed release. Says what it did, in a word or two."""
    now = now or datetime.now()
    s = fleet.state(cfg)
    offered = s.get("release")
    if not offered or not release.newer(offered, version):
        return "up to date"
    if s.get("updates") == "off":
        return "off"
    if not installed:
        return f"version {offered} is offered; a development run does not install it"
    try:
        tried = json.loads(s.get("update_try") or "{}")
    except ValueError:
        tried = {}
    if tried.get("version") == offered:
        if tried.get("count", 0) >= TRIES:
            return f"version {offered} was tried {TRIES} times and did not take; left alone"
        if now - datetime.fromisoformat(tried.get("at") or "2000-01-01") < timedelta(hours=WAIT_HOURS):
            return "waiting before trying again"
    count = tried.get("count", 0) + 1 if tried.get("version") == offered else 1
    fleet._save(cfg, update_try=json.dumps({"version": offered, "count": count, "at": now.isoformat(timespec="seconds")}))
    call = call or fleet.call
    try:
        sign = fleet.own_signer(cfg)
        got = call(s["server"], "/api/v1/agent/release", None, sign)
        m = release.verify(got.get("manifest"), got.get("signature"), keys)       # raises unless a release key signed it
        if not release.newer(m["version"], version):
            raise ValueError(f"the signed release is {m['version']}, which is not newer than this agent ({version})")
        data = call(s["server"], f"/api/v1/agent/package/{m['version']}", None, sign, limit=m["size"])
        release.check_package(m, data)
        folder.mkdir(parents=True, exist_ok=True)
        tidy(folder)
        package = folder / m["file"]
        package.write_bytes(data)
        install(package, folder / "install.log")
    except (RuntimeError, ValueError, OSError, AttributeError, TypeError) as e:
        fleet._save(cfg, update_error=str(e)[:300])
        if log:
            log.warning("update to %s not installed: %s", offered, e)
        return f"failed: {e}"
    fleet._save(cfg, update_error=None)
    if log:
        log.info("update: installing version %s over %s (signature and file checked)", m["version"], version)
    return f"installing {m['version']}"
