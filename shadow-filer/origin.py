"""
Where a download came from, as a filing signal.

Browsers and mail programs mark every file they save with a small hidden note (the "Zone.Identifier" stream,
the same mark Windows uses for its "this file came from the internet" warning). It holds the address the
file was downloaded from. If the files you've already filed from one website nearly all went to one folder
(a payroll portal, a vendor's support site), a new file from that website very likely belongs there too.

Measured on the filed documents (11 Oct 2026, leave-one-out): a site with 3+ other filed files, 80%+ of them
in one folder, pointed to the right folder 84 times in 87 (97%). Most sites don't qualify (webmail, chat,
drives: files from them go everywhere) and then this says nothing.

SAFETY: read-only. Only the note is read, never the file's content; cloud-only placeholders are skipped;
nothing leaves this PC and nothing is stored: site names are kept in memory only.
"""
import os
from collections import Counter
from urllib.parse import urlparse

FA_CLOUD = 0x1000 | 0x40000 | 0x400000  # offline / recall on open / recall on data access
STREAM = ":Zone.Identifier"


def _site(url: str) -> str | None:
    try:
        host = (urlparse(url).hostname or "").lower()
    except ValueError:
        return None
    host = host.removeprefix("www.")
    return host or None


def read(path: str) -> dict | None:
    """{"host": site the file was downloaded from, "referrer": site of the page that linked to it}, or None
    when the file carries no such note. Never raises."""
    if os.name != "nt":
        return None
    try:
        st = os.stat(path)
        if (getattr(st, "st_file_attributes", 0) or 0) & FA_CLOUD:
            return None
        with open(path + STREAM, encoding="utf-8", errors="replace") as f:
            text = f.read(8192)
    except (OSError, ValueError):
        return None
    fields = {}
    for line in text.splitlines():
        k, sep, v = line.partition("=")
        if sep:
            fields[k.strip()] = v.strip()
    host, ref = _site(fields.get("HostUrl", "")), _site(fields.get("ReferrerUrl", ""))
    if not host and not ref:
        return None
    return {"host": host, "referrer": ref}


def owners(filed, min_files: int = 3, share: float = 0.8) -> dict:
    """Site -> the one folder its files go to. `filed` is (site, folder) for every filed file that has a
    site. A site counts only with at least `min_files` filed files and at least `share` of them in one
    folder; anything else (webmail, chat apps) points nowhere and is left out."""
    by: dict = {}
    for site, folder in filed:
        if site:
            by.setdefault(site, Counter())[folder] += 1
    out = {}
    for site, cnt in by.items():
        total = sum(cnt.values())
        folder, n = cnt.most_common(1)[0]
        if total >= min_files and n / total >= share:
            out[site] = {"folder": folder, "files": n, "total": total, "share": round(n / total, 3)}
    return out
