"""
Filing suggestions (Phase 2): where should this file go?

Main signal: the documents you've already filed. Every file in the PARA tree has a fingerprint in the
search index (its name + the start of its text, embedded locally; never its folder). For a new file we
find the most similar filed documents and let them vote for their folders (k nearest neighbours,
softmax-weighted). The share of the vote is the confidence, and unlike the model's self-reported 0.95,
it was measured: on your own filed documents, leave-one-out.

Also shown: a matching rule (always first), and the local model's pick if it differs.
"""
import math
import os
import time
from pathlib import Path

DEFAULTS = {"k": 10, "temperature": 0.05, "show": 3, "duplicate_similarity": 0.995,
            "short_word_share": 0.8}  # a 3-letter folder word counts only if this share of filed names agree
# Words in folder names too general to identify one folder.
GENERIC = set("""completed projects areas resources archives other clients company documents personal technical
guides learning library framework research vendor marketing platform finance software firmware todelete bank
technologies services incorporation""".split())


# Everyday 3-letter words: never enough to name a folder, whatever has been filed.
COMMON3 = set("the and for new old one two all any our you not doc pdf img tmp jpg png zip csv".split())


def _name_keys(s: str) -> set[str]:
    """What a folder name or file name can be matched on:
    - its words of 3+ letters that aren't too general ('pavak', 'hcl');
    - shorter words joined to their neighbours ('GR-One', 'GR One', 'gr_one' -> 'grone'), because a
      1-2 letter word says nothing by itself. Numbers alone never count."""
    import re
    raw = [t for t in re.split(r"[^a-z0-9]+", s.lower()) if t]
    out = {t for t in raw if len(t) >= 3 and t not in GENERIC and not (len(t) < 4 and t.isdigit())}
    for n in (2, 3):
        for i in range(len(raw) - n + 1):
            part = raw[i:i + n]
            if any(len(t) < 4 for t in part) and not all(t in GENERIC for t in part):
                joined = "".join(part)
                if len(joined) >= 4 and not joined.isdigit():
                    out.add(joined)
    return out


def name_owners(dests: list[str], filed=None, short_share: float = DEFAULTS["short_word_share"]) -> dict:
    """Distinctive word -> the one destination folder named with it (e.g. 'pavak' -> 1-Projects/Pavak-Incorporation).
    A word in more than one folder name identifies nothing and is left out.

    3-letter words ('hcl', 'nac') are ambiguous far more often than longer ones, so one counts only while the
    files already filed back it up: `filed` is (file name without extension, folder) for every filed file,
    and at least `short_share` of the names containing the word must be in that folder. A word no filed
    name contains yet is accepted only when it is the folder's whole name ('HCL', 'HCL-Completed': a
    brand-new folder), never when it is one part of a longer name (the 'one' in 'GR-One')."""
    import re
    owner: dict = {}
    for d in dests:
        for t in _name_keys(d.split("/")[-1]):
            owner.setdefault(t, set()).add(d)
    own = {t: next(iter(v)) for t, v in owner.items() if len(v) == 1 and not (len(t) < 4 and t in COMMON3)}
    short = {t for t in own if len(t) < 4}
    if short:
        total, inside = dict.fromkeys(short, 0), dict.fromkeys(short, 0)
        for stem, label in filed or ():
            for t in _name_keys(stem) & short:
                total[t] += 1
                inside[t] += label == own[t]
        for t in short:
            if total[t]:
                ok = inside[t] / total[t] >= short_share
            else:
                words = [w for w in re.split(r"[^a-z0-9]+", own[t].split("/")[-1].lower()) if w and w not in GENERIC]
                ok = words == [t]
            if not ok:
                del own[t]
    return own


def settings(cfg: dict) -> dict:
    return {**DEFAULTS, **(cfg.get("suggest") or {})}


def _truncate(rel: str, depth: int) -> str:
    return "/".join(rel.split("/")[:depth]) if rel else ""


class Suggester:
    def __init__(self, cfg: dict, index, dests, db):
        self.cfg, self.index, self.dests, self.db = cfg, index, dests, db
        self._cache = None
        self._cache_at = 0.0
        self._cache_n = -1
        self._knn: dict = {}   # path -> (fingerprint, settings, votes, duplicate); valid for self._cache
        self._owners = None    # (examples, destinations, share, {word: folder})

    def owners(self) -> dict:
        """name_owners for the current folders, checked against the names of the files already filed."""
        dests, ex, share = self.dests.get(), self._examples(), settings(self.cfg)["short_word_share"]
        c = self._owners
        if c is None or c[0] is not ex or c[1] is not dests or c[2] != share:
            filed = [(os.path.splitext(os.path.basename(path))[0], label) for path, label, _ in ex]
            c = self._owners = (ex, dests, share, name_owners(dests, filed, share))
        return c[3]

    def _examples(self):
        """(path, folder at destination depth, fingerprint) for filed documents in valid destinations."""
        n = len(getattr(self.index, "docvecs", {}) or {})
        if self._cache is not None and n == self._cache_n and time.time() - self._cache_at < 300:
            return self._cache
        depth = self.cfg["destination_depth"]
        valid = set(self.dests.get())
        out = []
        for path, rel, vec in self.index.labelled():
            label = _truncate(rel, depth)
            if label in valid:
                out.append((path, label, vec))
        old = self._cache
        self._cache_at, self._cache_n = time.time(), n
        if old is not None and len(old) == len(out) and all(
                a[0] == b[0] and a[1] == b[1] and a[2] is b[2] for a, b in zip(old, out)):
            return old  # nothing was filed, moved or re-read: the comparisons already made still stand
        self._cache, self._knn = out, {}
        return out

    def _votes(self, path: str, fp, s: dict):
        """Folders of the most similar filed documents, and an identical one if there is one. Comparing a
        file with every filed document is the slow part, so the answer is kept until either side changes."""
        ex = self._examples()
        key = (s["k"], s["temperature"], s["duplicate_similarity"])
        hit = self._knn.get(path)
        if hit and hit[0] is fp and hit[1] == key:
            return [dict(c) for c in hit[2]], hit[3]
        knn, duplicate = [], None
        sims = [(math.sumprod(fp, v), label, ep) for ep, label, v in ex]
        sims.sort(key=lambda t: -t[0])
        if sims and sims[0][0] >= s["duplicate_similarity"]:
            duplicate = {"folder": sims[0][1], "path": sims[0][2], "similarity": round(sims[0][0], 4)}
        top = [t for t in sims if t[0] < s["duplicate_similarity"]][: s["k"]]
        if top:
            mx = top[0][0]
            votes, who = {}, {}
            for sim, label, ep in top:
                w = math.exp((sim - mx) / s["temperature"])
                votes[label] = votes.get(label, 0.0) + w
                who.setdefault(label, []).append(os.path.basename(ep))
            tot = sum(votes.values())
            for label, w in sorted(votes.items(), key=lambda kv: -kv[1]):
                knn.append({"folder": label, "source": "similar", "score": round(w / tot, 3),
                            "why": "like " + ", ".join(who[label][:2]), "exists": True})
        if len(self._knn) > 5000:
            self._knn.clear()
        self._knn[path] = (fp, key, knn, duplicate)
        return [dict(c) for c in knn], duplicate

    def stats(self) -> dict:
        ex = self._examples()
        per = {}
        for _, label, _ in ex:
            per[label] = per.get(label, 0) + 1
        return {"examples": len(ex), "folders": len(per)}

    def suggest(self, path: str) -> dict:
        import shadow_agent as sa
        s = settings(self.cfg)
        cands: list[dict] = []
        p = Path(path)

        rule = sa.match_rule(p, self.cfg)
        if rule:
            cands.append({"folder": rule["destination"], "source": "rule", "score": None,
                          "why": f"rule '{rule.get('name')}'",
                          "exists": rule["destination"] in set(self.dests.get())})

        # The file name mentions exactly one folder's distinctive word: right 86% of the time on filed documents,
        # and it works for new folders with only a few files, where similar-document voting can't.
        owners = self.owners() if self.index else name_owners(self.dests.get())
        named = {}
        for t in sorted(_name_keys(p.stem), key=len):  # for one folder, show the longest matching word
            if t in owners:
                named[owners[t]] = t
        if len(named) == 1:
            folder, word = next(iter(named.items()))
            if folder not in {c["folder"] for c in cands}:
                cands.append({"folder": folder, "source": "name", "score": None,
                              "why": f"file name mentions '{word}'", "exists": True})

        fp = self.index.fingerprint(path) if self.index else None
        knn, duplicate = [], None
        if fp is not None:
            knn, duplicate = self._votes(path, fp, s)

        model = None
        row = self.db.latest_prediction(path) if self.db else None
        if row and row["method"] == "model" and row["predicted"] not in (None, sa.UNSURE):
            model = {"folder": row["predicted"], "source": "model", "score": None,
                     "why": (row["reason"] or "")[:160], "exists": row["predicted"] in set(self.dests.get())}

        seen = {c["folder"] for c in cands}
        for c in knn:
            if len(cands) >= s["show"]:
                break
            if c["score"] < 0.03 and cands:
                break  # the rest are noise
            if c["folder"] not in seen:
                cands.append(c)
                seen.add(c["folder"])
        if model:
            if model["folder"] in seen:
                for c in cands:
                    if c["folder"] == model["folder"]:
                        c["model_agrees"] = True
            else:
                cands.append(model)
        for i, c in enumerate(cands, 1):
            c["rank"] = i
        return {"candidates": cands, "ready": fp is not None, "duplicate": duplicate,
                "confidence": knn[0]["score"] if knn else None}


def list_inbox(cfg: dict, dismissed: dict, ignore) -> list[dict]:
    """Files waiting in the watched folders (top level), newest first."""
    from cleanup import added_time
    out = []
    for inbox in cfg["inbox_folders"]:
        try:
            entries = list(os.scandir(inbox))
        except OSError:
            continue
        for e in entries:
            try:
                if not e.is_file(follow_symlinks=False) or ignore(Path(e.path)):
                    continue
                st = e.stat(follow_symlinks=False)
            except OSError:
                continue
            if dismissed.get(e.path) == st.st_size:
                continue
            out.append({"path": e.path, "name": e.name, "size": st.st_size, "mtime": st.st_mtime,
                        "added": added_time(st),  # when it arrived here; mtime can be years older
                        "ext": os.path.splitext(e.name)[1].lower()})
    out.sort(key=lambda f: -f["mtime"])
    return out
