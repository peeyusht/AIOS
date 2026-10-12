"""
Settings form support: turn the form's JSON into a clean, commented config.yaml, with validation.

The form edits a copy of the YAML mapping. On save we:
  1. coerce and validate every known field (types, ranges, regexes, rule shape),
  2. keep any keys the form doesn't know about, untouched,
  3. write a commented config.yaml through web_ui.apply_config, which backs up the old file to
     config.yaml.bak, hot-reloads what it can, and says when a restart is needed.
"""
import copy
import os
import re

import yaml

# (dotted key, kind, min, max)   kinds: int, float, bool, str, path, paths, strs
FIELDS = [
    ("inbox_folders", "paths", None, None),
    ("para_root", "path", None, None),
    ("destination_depth", "int", 1, 5),
    ("exclude_destinations", "strs", None, None),
    ("ollama.url", "str", None, None),
    ("ollama.model", "str", None, None),
    ("ollama.timeout_seconds", "int", 10, 1800),
    ("ollama.think", "bool", None, None),
    ("ollama.startup_wait_seconds", "int", 0, 7200),
    ("extraction.max_chars", "int", 500, 50000),
    ("extraction.max_pdf_pages", "int", 1, 100),
    ("settle_seconds", "int", 1, 600),
    ("hash_max_mb", "int", 1, 100000),
    ("reconcile_minutes", "int", 1, 1440),
    ("history_examples", "int", 0, 100),
    ("catch_up_days", "int", 0, 365),
    ("ui.port", "int", 1024, 65535),
    ("ignore_patterns", "strs", None, None),
    ("cleanup.scan_hours", "int", 0, 720),
    ("cleanup.installer_days", "int", 1, 3650),
    ("cleanup.driver_days", "int", 1, 3650),
    ("cleanup.stale_days", "int", 1, 3650),
    ("cleanup.para_duplicates", "bool", None, None),
    ("ocr.enabled", "bool", None, None),
    ("ocr.max_pdf_pages", "int", 1, 200),
    ("ocr.min_image_kb", "int", 0, 10000),
    ("autofile.enabled", "bool", None, None),
    ("autofile.min_decisions", "int", 20, 500),   # floors: autofile.FLOORS
    ("autofile.min_rate", "float", 0.9, 1.0),
    ("autofile.min_score", "float", 0.5, 1.0),
    ("autofile.delay_minutes", "int", 1, 1440),
    ("library.enabled", "bool", None, None),
    ("library.scan_hours", "int", 0, 720),
    ("library.check_signatures", "bool", None, None),
    ("library.applications", "bool", None, None),
    ("watch.enabled", "bool", None, None),
    ("watch.soon_days", "int", 1, 365),
    ("watch.keep_expired_days", "int", 0, 3650),
    ("search.enabled", "bool", None, None),
    ("search.model", "str", None, None),
    ("search.extra_folders", "paths", None, None),
    ("search.exclude_globs", "strs", None, None),
    ("search.min_similarity", "float", 0.0, 1.0),
    ("search.sweep_minutes", "int", 1, 1440),
]
KEY_ORDER = ["inbox_folders", "para_root", "destination_depth", "exclude_destinations", "ollama", "extraction",
             "settle_seconds", "hash_max_mb", "reconcile_minutes", "history_examples", "catch_up_days", "ui",
             "database", "log_file", "ignore_patterns", "rules", "cleanup", "search", "ocr", "autofile", "watch", "library"]
COMMENTS = {
    "inbox_folders": "Folders to watch for new files (e.g. Downloads). %USERPROFILE% and similar are expanded.",
    "para_root": "Root of your PARA tree: where you file things.",
    "destination_depth": "How deep into the PARA tree the model may choose (2 = e.g. \"1 Projects/Client X\").",
    "exclude_destinations": "PARA folders (relative to para_root) the model may never choose.",
    "ollama": "Local model used to predict destinations.",
    "extraction": "How much text is read from each new file for the prediction.",
    "settle_seconds": "A file must stop growing for this long before it's read.",
    "hash_max_mb": "Bigger files are matched by name and size only.",
    "reconcile_minutes": "How often the PARA tree is swept to catch filings missed by events.",
    "history_examples": "Your recent filing decisions shown to the model as examples (0 = none).",
    "catch_up_days": "On start and every sweep, predict inbox files from the last N days that were missed.",
    "ui": "Local web UI (only reachable from this PC).",
    "ignore_patterns": "Temporary / partial / system files to ignore.",
    "rules": "Deterministic rules, checked top-down before the model. 'destination' is relative to para_root.",
    "cleanup": "Cleanup recommendations (Cleanup page).",
    "search": "Search index (Search page). Changing the model rebuilds the index.",
    "autofile": "Phase 3: file automatically into folders your Inbox decisions have proven. Off until you switch it on.",
    "ocr": "Read scanned PDFs, images and screenshot-only Word files with Windows' built-in OCR.",
    "library": "Library page: firmware and VM images, document versions, look-alike pictures, program signatures, installed applications. Read-only.",
    "watch": "Document watch (Watch page): dates that are coming up in your documents, and sensitive files in Downloads.",
}


class Invalid(ValueError):
    pass


def _get(d, dotted):
    for k in dotted.split("."):
        if not isinstance(d, dict) or k not in d:
            return None
        d = d[k]
    return d


def _set(d, dotted, v):
    ks = dotted.split(".")
    for k in ks[:-1]:
        if not isinstance(d.get(k), dict):
            d[k] = {}
        d = d[k]
    d[ks[-1]] = v


def _coerce(key, kind, lo, hi, v):
    label = key.replace(".", " → ").replace("_", " ")
    if kind == "bool":
        if isinstance(v, bool):
            return v
        raise Invalid(f"{label}: must be on or off")
    if kind in ("int", "float"):
        try:
            n = int(v) if kind == "int" and float(v) == int(float(v)) else float(v)
        except (TypeError, ValueError):
            raise Invalid(f"{label}: must be a number")
        if kind == "int" and not isinstance(n, int):
            raise Invalid(f"{label}: must be a whole number")
        if (lo is not None and n < lo) or (hi is not None and n > hi):
            raise Invalid(f"{label}: must be between {lo} and {hi}")
        return n
    if kind in ("str", "path"):
        if not isinstance(v, str) or not v.strip():
            raise Invalid(f"{label}: can't be empty")
        return v.strip()
    if kind in ("strs", "paths"):
        if v is None:
            return []
        if not isinstance(v, list) or not all(isinstance(x, str) for x in v):
            raise Invalid(f"{label}: must be a list of text")
        out = [x.strip() for x in v if x.strip()]
        if kind == "paths" and len({x.lower().rstrip("\\/") for x in out}) != len(out):
            raise Invalid(f"{label}: the same folder is listed twice")
        return out
    raise Invalid(f"{label}: unknown type")


def _rules(v):
    if v is None:
        return []
    if not isinstance(v, list):
        raise Invalid("rules: must be a list")
    out = []
    for i, r in enumerate(v, 1):
        if not isinstance(r, dict):
            raise Invalid(f"rule #{i}: bad format")
        name = str(r.get("name") or f"rule-{i}").strip()
        exts = r.get("extensions") or []
        if isinstance(exts, str):
            exts = [e for e in re.split(r"[,\s]+", exts) if e]
        exts = [("." + e.lstrip(".")).lower() for e in exts if e.strip(".")]
        rx = (r.get("name_regex") or "").strip()
        dest = str(r.get("destination") or "").strip().strip("/\\").replace("\\", "/")
        if not dest:
            raise Invalid(f"rule '{name}': choose a destination")
        if not exts and not rx:
            raise Invalid(f"rule '{name}': needs file extensions, a name pattern, or both")
        if rx:
            try:
                re.compile(rx)
            except re.error as e:
                raise Invalid(f"rule '{name}': name pattern is not a valid regular expression ({e})")
        rule = {"name": name}
        if exts:
            rule["extensions"] = exts
        if rx:
            rule["name_regex"] = rx
        rule["destination"] = dest
        out.append(rule)
    names = [r["name"].lower() for r in out]
    if len(set(names)) != len(names):
        raise Invalid("rules: two rules have the same name")
    return out


def normalize(form: dict, current: dict) -> dict:
    """Validated config mapping = current config + the form's known fields. Unknown keys are kept."""
    if not isinstance(form, dict):
        raise Invalid("bad request")
    out = copy.deepcopy(current) if isinstance(current, dict) else {}
    for key, kind, lo, hi in FIELDS:
        section = key.split(".")[0]
        if "." in key and section in ("cleanup", "search", "ocr", "autofile", "watch", "library") and not isinstance(form.get(section), dict):
            continue  # optional section not used: leave it out, defaults apply
        v = _get(form, key)
        if v is None and kind not in ("strs", "paths"):
            # optional sections (cleanup/search) may be absent: keep defaults by not writing them
            if key.split(".")[0] in ("cleanup", "search", "ocr", "autofile", "watch", "library") or key.startswith("extraction."):
                continue
            raise Invalid(f"{key.replace('.', ' → ')}: missing")
        _set(out, key, _coerce(key, kind, lo, hi, v))
    if not out.get("inbox_folders"):
        raise Invalid("Add at least one folder to watch")
    out["rules"] = _rules(form.get("rules"))
    url = _get(out, "ollama.url")
    if not re.match(r"^https?://", url):
        raise Invalid("Ollama URL must start with http:// or https://")
    return out


def dump(cfg: dict) -> str:
    """Commented YAML, sections in a stable order."""
    lines = ["# Shadow Filer configuration. Edited from the Settings page; you can also edit it by hand.",
             "# Environment variables like %USERPROFILE% are expanded. The previous version is config.yaml.bak.", ""]
    keys = [k for k in KEY_ORDER if k in cfg] + [k for k in cfg if k not in KEY_ORDER]
    for k in keys:
        if k in COMMENTS:
            lines.append("# " + COMMENTS[k])
        block = yaml.safe_dump({k: cfg[k]}, sort_keys=False, allow_unicode=True, default_flow_style=False,
                               width=1000)
        lines.append(block.rstrip())
        lines.append("")
    return "\n".join(lines)


def list_dirs(path: str) -> dict:
    """Subfolders of a folder, for the folder picker. Names only; never opens files."""
    if not path:
        if os.name == "nt":
            drives = []
            try:
                drives = os.listdrives()
            except AttributeError:  # Python < 3.12
                import string
                drives = [f"{c}:\\" for c in string.ascii_uppercase if os.path.exists(f"{c}:\\")]
            home = os.path.expanduser("~")
            quick = [os.path.join(home, n) for n in ("Downloads", "Documents", "Desktop") if
                     os.path.isdir(os.path.join(home, n))]
            return {"path": "", "parent": None, "dirs": [{"name": d, "path": d} for d in drives],
                    "quick": [{"name": os.path.basename(q), "path": q} for q in quick]}
        path = "/"
    p = os.path.abspath(os.path.expandvars(os.path.expanduser(path)))
    if not os.path.isdir(p):
        raise Invalid("Folder not found")
    out = []
    try:
        with os.scandir(p) as it:
            for e in it:
                try:
                    if not e.is_dir(follow_symlinks=False) or e.name.startswith((".", "$")):
                        continue
                    a = getattr(e.stat(follow_symlinks=False), "st_file_attributes", 0) or 0
                    if a & 0x6:  # hidden or system
                        continue
                except OSError:
                    continue
                out.append({"name": e.name, "path": e.path})
                if len(out) >= 1000:
                    break
    except OSError as e:
        raise Invalid(f"Can't open folder: {e.strerror or e}")
    parent = os.path.dirname(p.rstrip("\\/")) if p.rstrip("\\/") != p[:2] else ""
    if parent == p:
        parent = ""
    return {"path": p, "parent": parent, "dirs": sorted(out, key=lambda d: d["name"].lower())}


def check_path(path: str) -> dict:
    p = os.path.expandvars(os.path.expanduser(path or ""))
    return {"input": path, "expanded": p, "exists": bool(path) and os.path.isdir(p)}
