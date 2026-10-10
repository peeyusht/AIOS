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
from operator import mul
from pathlib import Path

DEFAULTS = {"k": 10, "temperature": 0.05, "show": 3, "duplicate_similarity": 0.995}


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
        self._cache, self._cache_at, self._cache_n = out, time.time(), n
        return out

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

        fp = self.index.fingerprint(path) if self.index else None
        knn, duplicate = [], None
        if fp is not None:
            ex = self._examples()
            sims = [(sum(map(mul, fp, v)), label, ep) for ep, label, v in ex]
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
                        "ext": os.path.splitext(e.name)[1].lower()})
    out.sort(key=lambda f: -f["mtime"])
    return out
