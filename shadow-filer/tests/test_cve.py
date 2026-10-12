"""Known vulnerabilities: reading NVD's files, the local copy, and the strict name and version matching.
Nothing is downloaded here: made-up feed files stand in for nvd.nist.gov and cisa.gov."""
import gzip
import hashlib
import json
import shutil
import sys
import tempfile
import unittest
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import apps  # noqa: E402
import cve  # noqa: E402
import library  # noqa: E402
import services  # noqa: E402


def nvd(cid, matches, status="Analyzed", score=7.5, text="A made-up flaw."):
    return {"cve": {"id": cid, "published": "2026-03-01T10:00:00.000", "lastModified": "2026-03-02T10:00:00.000",
                    "vulnStatus": status, "descriptions": [{"lang": "es", "value": "x"}, {"lang": "en", "value": text}],
                    "metrics": {"cvssMetricV31": [{"type": "Primary", "cvssData": {"baseScore": score,
                                                                                    "baseSeverity": "HIGH"}}]},
                    "configurations": [{"nodes": [{"operator": "OR", "cpeMatch": matches}]}] if matches else []}}


def cpe(vendor, product, version="*", part="a", vulnerable=True, **ranges):
    return {"vulnerable": vulnerable, "criteria": f"cpe:2.3:{part}:{vendor}:{product}:{version}:*:*:*:*:*:*:*", **ranges}


FEED = [
    nvd("CVE-2026-0001", [cpe("kettle", "archive", versionEndExcluding="25.00")], score=9.8),
    nvd("CVE-2026-0002", [cpe("kettle", "archive", versionStartIncluding="10.0", versionEndIncluding="20.0")]),
    nvd("CVE-2026-0003", [cpe("kettle", "archive", "24.08"), cpe("kettle", "archive", "24.08", part="o")]),
    nvd("CVE-2026-0004", [cpe("kettle", "archive")]),                                  # no version at all
    nvd("CVE-2026-0005", [cpe("othervendor", "archive", versionEndExcluding="99")]),   # same product word, other maker
    nvd("CVE-2026-0006", [cpe("pine", "runtime", versionStartIncluding="3.12.0", versionEndExcluding="3.12.9")]),
    nvd("CVE-2026-0007", [cpe("kettle", "archive", versionEndExcluding="25.00", vulnerable=False)]),
    nvd("CVE-2026-0008", [], status="Rejected"),
    nvd("CVE-2026-0010", [cpe("kettle", "archive", versionEndExcluding="25.00")], text="The Kettle Android app leaks."),
    nvd("CVE-2026-0011", [cpe("mongo", "mongo", versionEndExcluding="9.0")]),
    nvd("CVE-2026-0012", [cpe("cli", "cli", versionEndExcluding="9.0"), cpe("gridline", "cli", versionEndExcluding="9.0")]),
    nvd("CVE-2026-0013", [cpe("microsoft", "edge_chromium", versionEndExcluding="200"), cpe("microsoft", "edge", "40")]),
    nvd("CVE-2026-0014", [cpe("forti", "client", versionEndExcluding="8.0")]),
    {"cve": {"id": "CVE-2026-0009", "published": "2026-04-01T00:00:00", "vulnStatus": "Awaiting Analysis",
             "descriptions": [{"lang": "en", "value": "Reported by the maker; NVD has not analysed it."}],
             "affected": [{"source": "x", "affectedData": [
                 {"vendor": "Harbor Software", "product": "Harbor Remote", "defaultStatus": "unaffected",
                  "versions": [{"version": "0", "lessThan": "9.1.0", "status": "affected"},
                               {"version": "8.0", "status": "unaffected"}]}]}]}},
]
KEV = {"vulnerabilities": [{"cveID": "CVE-2026-0001", "vendorProject": "Kettle", "product": "Archive",
                            "vulnerabilityName": "Kettle Archive flaw", "dateAdded": "2026-03-05",
                            "knownRansomwareCampaignUse": "Known"}]}


def feed_bytes(entries):
    return json.dumps({"resultsPerPage": len(entries), "format": "NVD_CVE", "vulnerabilities": entries,
                       "tail": "after the list"}, indent=1).encode("utf-8")


class Fake:
    """Stands in for the two web sites. Remembers every address asked for."""
    def __init__(self, feeds, kev=KEV, wrong_sha=()):
        self.feeds, self.kev, self.wrong, self.asked = feeds, kev, set(wrong_sha), []

    def __call__(self, url, dest=None, timeout=0):
        self.asked.append(url)
        if url == cve.KEV:
            return json.dumps(self.kev)
        name = url.rsplit("nvdcve-2.0-", 1)[1].split(".")[0]
        raw = feed_bytes(self.feeds.get(name, []))
        if url.endswith(".meta"):
            sha = "0" * 64 if name in self.wrong else hashlib.sha256(raw).hexdigest().upper()
            return f"lastModifiedDate:2026-10-10T03:00:00-04:00\r\nsize:{len(raw)}\r\nsha256:{sha}\r\n"
        with gzip.open(dest, "wb") as f:
            f.write(raw)
        return None


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="sf-test-"))
        self.cfg = {"database": self.tmp / "t.db", "cve_database": self.tmp / "cve.db"}
        self.now = datetime(2026, 10, 12, 9)

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def sync(self, feeds=None, **kw):
        fake = Fake(feeds if feeds is not None else {"2026": FEED}, **kw)
        return cve.sync(self.cfg, get=fake, now=self.now), fake


class FeedTest(Base):
    def test_entries_come_one_at_a_time_whatever_the_piece_size(self):
        raw = feed_bytes(FEED)
        for chunk in (7, 64, 1 << 20):
            p = self.tmp / "f.gz"
            with gzip.open(p, "wb") as f:
                f.write(raw)
            with gzip.open(p, "rb") as f:
                self.assertEqual([x["cve"]["id"] for x in cve.items(f, chunk)], [x["cve"]["id"] for x in FEED], chunk)

    def test_what_a_cve_states(self):
        st = cve.statements(FEED[2]["cve"])
        self.assertEqual(st, {("nvd", "kettle", "archive", "24.08", "", "", "", "")})       # applications only
        self.assertEqual(cve.statements(FEED[6]["cve"]), set())                              # "not vulnerable"
        self.assertEqual(cve.statements(FEED[-1]["cve"]),                                    # the reporter's words
                         {("cna", "harbor_software", "harbor_remote", "*", "", "", "", "9.1.0")})
        self.assertEqual(cve.cpe_parts(r"cpe:2.3:a:a\:b:c\+\+:1.0:*")[3:5], ["a:b", "c++"])

    def test_first_download_then_only_the_modified_file(self):
        r, fake = self.sync()
        self.assertEqual((r["errors"], len(r["feeds"]), r["kev"]), ([], 25, 1))        # 2002 .. 2026
        st = r["status"]
        self.assertEqual((st["cves"], st["kev"], st["complete"], st["synced_at"]), (13, 1, True, "2026-10-12T09:00:00"))
        # every address is one of the fixed public files: nothing about this PC is in any request
        allowed = {cve.KEV} | {cve.NVD.format(name=n, ext=e) for n in [*map(str, range(2002, 2027)), "modified"]
                               for e in ("meta", "json.gz")}
        self.assertLessEqual(set(fake.asked), allowed)
        self.assertEqual(sum(u.endswith(".json.gz") for u in fake.asked), 25)       # empty years are files too
        self.now = datetime(2026, 10, 13, 9)
        changed = nvd("CVE-2026-0002", [cpe("kettle", "archive", versionEndExcluding="30.0")])
        r, fake = self.sync({"modified": [changed, nvd("CVE-2026-0004", [], status="Rejected")]})
        self.assertEqual([u.rsplit("-", 1)[1] for u in fake.asked if "nvdcve" in u], ["modified.meta", "modified.json.gz"])
        self.assertEqual(r["status"]["cves"], 12)                                   # the rejected one is gone
        got = cve.match(self.cfg, [{"id": "a", "name": "Kettle Archive", "publisher": "Kettle", "version": "24.08"}])[0]
        self.assertIn("CVE-2026-0002", [x["id"] for x in got["cves"]])              # and the changed range counts
        self.assertEqual(got["unversioned"], 0)
        self.now = datetime(2026, 10, 30, 9)                                        # away for more than a week
        r, fake = self.sync()
        self.assertEqual(sum(u.endswith(".meta") for u in fake.asked), 25)

    def test_a_file_that_fails_the_checksum_changes_nothing_and_is_tried_again(self):
        r, _ = self.sync(wrong_sha={"2026"})
        self.assertEqual((r["status"]["cves"], r["status"]["complete"], r["status"]["synced_at"]), (0, False, None))
        self.assertIn("2026: the file does not match NVD's checksum", r["errors"][0])
        self.assertTrue(r["status"]["tried_at"])
        self.assertFalse(cve.due(self.cfg, 24, now=self.now))                       # but not hammered every 5 minutes
        self.now = datetime(2026, 10, 13, 9)
        r, _ = self.sync()
        self.assertEqual((r["status"]["cves"], r["status"]["complete"]), (13, True))


class MatchTest(Base):
    def setUp(self):
        super().setUp()
        self.sync()

    def one(self, **item):
        return cve.match(self.cfg, [{"id": "x", "publisher": "", "version": "", **item}])[0]

    def test_version_inside_the_stated_range(self):
        got = self.one(name="Kettle Archive 24.08 (x64)", publisher="Kettle Software", version="24.08")
        self.assertEqual(got["products"], ["kettle:archive"])
        self.assertEqual([(x["id"], x["fixed_in"], x["kev"], x["ransomware"]) for x in got["cves"]],
                         [("CVE-2026-0001", "25.00", True, True),        # known exploited first
                          ("CVE-2026-0003", None, False, False)])        # that exact version
        self.assertEqual(got["unversioned"], 1)                          # "all versions": kept apart, not a hit
        self.assertEqual(got["cves"][0]["score"], 9.8)
        self.assertEqual(self.one(name="Kettle Archive", publisher="Kettle", version="25.01")["cves"], [])
        self.assertEqual(self.one(name="Kettle Archive", publisher="Kettle", version="")["cves"], [])

    def test_the_maker_has_to_agree(self):
        for item, want in (
            (dict(name="Kettle Archive", publisher="Kettle Software Ltd", version="1.0"), ["kettle:archive"]),
            (dict(name="Kettle Archive", publisher="", version="1.0"), ["kettle:archive"]),          # maker in the name
            (dict(name="Archive Tool", publisher="Somebody Else", version="1.0"), []),               # only the word
            (dict(name="Archive", publisher="OtherVendor Inc.", version="1.0"), ["othervendor:archive"]),
            (dict(name="Archive", publisher="", version="1.0", update_id="Kettle.Archive"), ["kettle:archive"]),
            (dict(name="Harbor Remote", publisher="Harbor Software GmbH", version="9.0.14"),
             ["harbor_software:harbor_remote"]),
        ):
            self.assertEqual(self.one(**item)["products"], want, item)

    def test_the_product_is_the_whole_name_never_a_part_of_it(self):
        for item, want in (
            (dict(name="Mongo", publisher="Mongo Inc."), ["mongo:mongo"]),
            (dict(name="Mongo Shell", publisher="Mongo Inc."), []),                   # not the server
            (dict(name="Mongo Update Service", publisher="Mongo Inc."), []),
            (dict(name="Mongo 7.0.5 2008R2Plus SSL (64 bit)", publisher="Mongo Inc."), ["mongo:mongo"]),  # a build label
            (dict(name="Gridline CLI", publisher="Gridline"), ["gridline:cli"]),      # not the vendor called 'cli'
            (dict(name="Microsoft Edge", publisher="Microsoft Corporation"),
             ["microsoft:edge", "microsoft:edge_chromium"]),                          # today's Edge has its own name
            (dict(name="Forti Client VPN", publisher="Forti"), ["forti:client"]),     # ... VPN, ... Client
        ):
            self.assertEqual(self.one(version="1.0", **item)["products"], want, item)

    def test_a_flaw_in_the_phone_app_is_not_one_here(self):
        got = self.one(name="Kettle Archive", publisher="Kettle", version="24.08")
        self.assertNotIn("CVE-2026-0010", [x["id"] for x in got["cves"]])

    def test_version_as_the_name_says_it(self):
        # registered as 3.12.4150.0, which is not inside 3.12.0 .. 3.12.9; the name says 3.12.4, which is
        got = self.one(name="Pine Runtime 3.12.4 (64-bit)", publisher="Pine Project", version="3.12.4150.0")
        self.assertEqual((got["judged_version"], [x["id"] for x in got["cves"]]), ("3.12.4", ["CVE-2026-0006"]))

    def test_ranges(self):
        row = dict(version="*", vsi="", vse="", vei="", vee="")
        for r, v, want in (
            (dict(vee="2.0"), "1.9.9", "yes"), (dict(vee="2.0"), "2.0", None), (dict(vee="2.0"), "2.0.0.0", None),
            (dict(vei="2.0"), "2.0.0", "yes"), (dict(vsi="1.5", vee="2.0"), "1.4", None),
            (dict(vse="1.5", vee="2.0"), "1.5", None), (dict(vse="1.5", vee="2.0"), "1.5.1", "yes"),
            (dict(version="1.2"), "1.2.0", "yes"), (dict(version="1.2"), "1.20", None),
            (dict(vee="9.1"), "10.0", None),                          # numbers, not text: 10 is after 9
            (dict(vei="f0078ae"), "0.40.2", None),                    # a commit id is not a version:
            (dict(vee="0078aef"), "1.0", None), (dict(vee="deadbeef"), "1.0", None),   # it cannot be compared
            (dict(vee="13.1-37.282"), "13.1.20", "yes"),
            ({}, "1.0", "unversioned"), (dict(vee="2.0"), "", None),
        ):
            self.assertEqual(cve.affected({**row, **r}, v), want, (r, v))


class ScanTest(Base):
    def test_applications_and_services_together(self):
        self.sync()
        reg = lambda sub, **v: {"id": "machine64:" + sub, "scope": "machine", "arch": "64-bit", "values": v, "changed": 0}
        apps.scan(self.cfg, now=self.now, packaged=lambda: [
            {"id": "Kettle.Archive_abc", "name": "Kettle.Archive", "display": "Kettle Archive", "version": "1.0",
             "publisher": "Kettle Software", "signature": "Store"}], desktop=lambda: [
            reg("k", DisplayName="Kettle Archive 24.08 (x64)", DisplayVersion="24.08", Publisher="Kettle Software",
                InstallLocation="C:\\Program Files\\Kettle"),
            reg("n", DisplayName="Brightpad Notes", DisplayVersion="4.1", Publisher="Brightpad Labs")])
        raw = [
            {"name": "KettleSvc", "display": "Kettle Indexer", "state": "Running", "start": "Auto",
             "account": "LocalSystem", "exe": "C:\\Program Files\\Kettle\\svc.exe", "pid": 10, "company": "Kettle",
             "product": "Kettle Archive", "version": "24.08.0.0", "listens": ["0.0.0.0|8443", "127.0.0.1|9000"]},
            {"name": "HarborSvc", "display": "Harbor Remote Service", "state": "Stopped", "start": "Manual",
             "account": "NT AUTHORITY\\LocalService", "exe": "C:\\Tools\\harbor.exe", "pid": 0,
             "company": "Harbor Software GmbH", "product": "Harbor Remote", "version": "9.0.14", "listens": []},
        ]
        rep = cve.scan(self.cfg, read_services=lambda: raw, now=self.now)
        self.assertEqual((rep["installed"], rep["recognised"], [a["name"] for a in rep["apps"]]),
                         (2, 1, ["Kettle Archive 24.08 (x64)"]))      # the Store app is not judged at all
        k, h = rep["services"]
        self.assertEqual((k["name"], k["app_name"], k["account"], k["exposed"], k["ports"], len(k["cves"])),
                         ("Kettle Indexer", "Kettle Archive 24.08 (x64)", "system", True,
                          [{"port": 8443, "network": True}, {"port": 9000, "network": False}], 2))
        # a service with no installed application behind it is judged by what its own program says it is
        self.assertEqual((h["app_id"], h["account"], h["running"], [x["id"] for x in h["cves"]]),
                         (None, "limited", False, ["CVE-2026-0009"]))
        v = cve.view(self.cfg)
        self.assertEqual({k: v["summary"][k] for k in ("apps_affected", "cves", "kev", "critical", "services",
                                                       "services_exposed", "services_affected")},
                         {"apps_affected": 1, "cves": 2, "kev": 1, "critical": 1, "services": 2,
                          "services_exposed": 1, "services_affected": 2})
        self.assertIn("EXPLOITED", cve.as_text(v))
        # Hide: remembered by the name without its version, and the hidden program's service goes quiet too
        key = cve.hide_key("app", v["apps"][0])
        self.assertEqual(key, "desktop:kettlearchive")
        cve.hide(self.cfg["database"], "app", key)
        cve.hide(self.cfg["database"], "service", "HarborSvc")
        h = cve.view(self.cfg)
        self.assertEqual((h["apps"], h["hidden"], [(s["id"], len(s["cves"])) for s in h["services"]]),
                         ([], 2, [("KettleSvc", 0)]))
        self.assertEqual((h["summary"]["kev"], h["summary"]["apps_affected"], h["summary"]["services_exposed"]), (0, 0, 1))
        brief = cve.view(self.cfg, brief=True)
        self.assertEqual(("apps" in brief, "services" in brief, brief["summary"]), (False, False, h["summary"]))
        self.assertEqual(len(cve.report(self.cfg)["apps"]), 1)                     # the comparison itself is untouched
        cve.hide(self.cfg["database"], "app", key, undo=True)
        self.assertEqual(cve.view(self.cfg)["summary"]["kev"], 1)
        cve.restore_all(self.cfg["database"])
        self.assertEqual(cve.view(self.cfg)["hidden"], 0)
        self.assertEqual(services.tidy([{"name": "", "exe": "x"}, {"name": "a", "exe": ""}], []), [])

    def test_off_by_default(self):
        self.assertIs(library.settings({})["vulnerabilities"], False)
        self.assertEqual(library.settings({"library": {"cve_hours": 0}})["cve_hours"], 1)
        self.assertTrue(cve.due(self.cfg, 24))


if __name__ == "__main__":
    unittest.main()
