"""Library and hygiene: firmware/VM catalogue, document versions, look-alike pictures, program signatures.
Everything here is read-only; the tests also check that a scan leaves the folders exactly as they were."""
import logging
import os
import shutil
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import library  # noqa: E402
import web_ui  # noqa: E402

try:
    from PIL import Image, ImageDraw
except ImportError:  # pragma: no cover
    Image = None


class ImageNamesTest(unittest.TestCase):
    def test_vendor_names(self):
        for name, want in (
            ("FGT_301E-v7.4.12.M-build2902-FORTINET.out", ("FortiGate 301E", "7.4.12", "2902")),
            ("FAZ_VM64-v8.0.0.F-build0105-FORTINET.out.ovf.zip", ("FortiAnalyzer VM64", "8.0.0", "0105")),
            ("Forescout-9.1.4-791.iso", ("Forescout", "9.1.4", "791")),
            ("ubuntu-26.04.1-live-server-amd64.iso", ("ubuntu", "26.04.1", None)),
            ("VMware-VMvisor-Installer-8.0U3e-24677879.x86_64.iso", ("VMware VMvisor Installer", "8.0U3e", "24677879")),
            ("GNS3.VM.VMware.ESXI.2.2.59", ("GNS3 VM VMware ESXI", "2.2.59", None)),
            ("GNS3 VM.ova", ("GNS3 VM", None, None)),
        ):
            p = library.parse_image(name)
            self.assertEqual((p["product"], p["version"], p["build"]), want, name)

    def test_what_counts_as_an_image(self):
        self.assertTrue(library.looks_like_image("router.bin"))
        self.assertTrue(library.looks_like_image("FGT_VM64-v7.6.7.M-build3704-FORTINET.out.ovf.zip"))
        self.assertFalse(library.looks_like_image("photos.zip"))
        self.assertFalse(library.looks_like_image("report.pdf"))


class VersionsTest(unittest.TestCase):
    def test_split(self):
        for stem, want in (
            ("Proposal_v2", ("proposal", ["v2"], False)),
            ("Proposal_REVISED_v2 (1)", ("proposal", ["revised", "v2"], True)),
            ("Status_19Mar2026", ("status", ["19mar2026"], False)),
            ("Plan-24-Dec-2025", ("plan", ["24-dec-2025"], False)),
            ("Plan-03-02-2026", ("plan", ["03-02-2026"], False)),
            ("Offer_R2", ("offer", ["r2"], False)),
            ("receipt-2064-1655", ("receipt 2064 1655", [], False)),      # not a date
            ("Windows 11 guide", ("windows 11 guide", [], False)),        # a number is not a version
            ("Budget - Copy", ("budget", [], True)),
        ):
            self.assertEqual(library.split_version(stem), want, stem)

    def files(self, *rows):
        return [{"path": f"{'D:/P/1-Projects/X' if src == 'para' else 'C:/Dl'}/{name}", "name": name, "size": size,
                 "mtime": mtime, "source": src} for name, size, mtime, src in rows]

    def test_chains(self):
        chains = library.version_chains(self.files(
            ("Acme Proposal.docx", 100, 10, "para"), ("Acme Proposal_v2.docx", 120, 20, "inbox"),
            ("Acme Proposal_v3.docx", 130, 30, "inbox"),
            ("Statement.pdf", 50, 5, "inbox"), ("Statement (1).pdf", 60, 6, "inbox"),
            ("Manual.pdf", 70, 1, "para"), ("Manual (1).pdf", 70, 2, "inbox"),      # same size: a copy, not a version
            ("Acme Proposal.pdf", 90, 3, "para"),                                  # other type: its own document
            ("notes_v1.txt", 1, 1, "inbox"), ("notes_v2.txt", 2, 2, "inbox"),       # not an office document
            ("v2.docx", 1, 1, "inbox"), ("v3.docx", 2, 2, "inbox")))               # no name left
        self.assertEqual([(c["title"], c["ext"], c["kind"], c["filed_is_older"]) for c in chains],
                         [("acme proposal", ".docx", "versions", True), ("statement", ".pdf", "same-name", False)])
        m = chains[0]["members"]
        self.assertEqual([(x["name"], x["label"], x["newest"]) for x in m],
                         [("Acme Proposal_v3.docx", "v3", True), ("Acme Proposal_v2.docx", "v2", False),
                          ("Acme Proposal.docx", "", False)])

    def test_filed_newest_is_not_flagged(self):
        chains = library.version_chains(self.files(("Offer letter_v1.pdf", 10, 1, "inbox"),
                                                   ("Offer letter_v2.pdf", 20, 2, "para")))
        self.assertFalse(chains[0]["filed_is_older"])


@unittest.skipIf(Image is None, "Pillow not installed")
class PicturesTest(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="sf-test-"))

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def picture(self, name, seed, size=(400, 300), fmt=None, blank=False):
        im = Image.new("RGB", (400, 300), "white")
        d = ImageDraw.Draw(im)
        if not blank:
            for i in range(12):   # a made-up drawing that depends on the seed
                x, y = (seed * 37 + i * 53) % 360, (seed * 91 + i * 29) % 260
                d.rectangle([x, y, x + 30 + (i * seed) % 60, y + 20 + (i * 7) % 50],
                            fill=((seed * 40 + i * 20) % 255, (i * 35) % 255, (seed * 70) % 255))
        p = self.tmp / name
        im.resize(size).save(p, fmt)
        h = library.picture_hash(str(p))
        return {"path": str(p), "name": name, "size": p.stat().st_size, "source": "inbox", **h}

    def test_resized_and_resaved_match_but_different_pictures_do_not(self):
        a = self.picture("a.png", 3)
        a_small = self.picture("a_small.jpg", 3, size=(200, 150))
        b = self.picture("b.png", 8)
        blank1, blank2 = self.picture("blank1.png", 0, blank=True), self.picture("blank2.png", 0, blank=True)
        groups = library.similar_groups([a, a_small, b, blank1, blank2], 8)
        self.assertEqual([sorted(m["name"] for m in g) for g in groups], [["a.png", "a_small.jpg"]])

    def test_no_chaining(self):
        def fake(name, bits):
            return {"path": name, "name": name, "size": 1, "source": "inbox", "hash": f"{bits:064x}"}
        base = int("0f" * 32, 16)
        near = base ^ 0b11111                       # 5 bits from base
        far = near ^ (0b11111 << 20)                # 5 from near, 10 from base
        groups = library.similar_groups([fake("a", base), fake("b", near), fake("c", far)], 6)
        self.assertEqual([[m["name"] for m in g] for g in groups], [["a", "b"]])

    def test_unreadable_file(self):
        p = self.tmp / "broken.png"
        p.write_bytes(b"not a picture")
        self.assertIsNone(library.picture_hash(str(p)))


class SignaturesTest(unittest.TestCase):
    def test_publisher_and_wording(self):
        self.assertEqual(library.publisher('CN="Acme Software, Inc.", O="Acme Software, Inc.", C=US'), "Acme Software, Inc.")
        self.assertEqual(library.publisher("CN=Fortinet Technologies (Canada) ULC, O=Fortinet, C=CA"),
                         "Fortinet Technologies (Canada) ULC")
        self.assertEqual(library.publisher(""), "")
        self.assertEqual(library.signature_view("Valid")["level"], "signed")
        self.assertEqual(library.signature_view("NotSigned")["level"], "unsigned")
        self.assertEqual(library.signature_view("HashMismatch")["level"], "tampered")
        self.assertEqual(library.signature_view("")["level"], "unknown")
        self.assertEqual(library.signature_view("UnknownError", "CN=Someone")["level"], "untrusted")
        self.assertEqual(library.signature_view("UnknownError", "")["level"], "unknown")   # nothing was signed


class ScanTest(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="sf-test-"))
        self.inbox, self.para = self.tmp / "inbox", self.tmp / "para"
        (self.inbox / "FGT_VM64-v8.0.0.F-build0167-FORTINET.out.ovf").mkdir(parents=True)
        (self.para / "1-Projects" / "Acme").mkdir(parents=True)
        self.w(self.inbox / "FGT_VM64-v8.0.0.F-build0167-FORTINET.out.ovf" / "FortiGate-VM64.ovf", 100)
        self.w(self.inbox / "FGT_VM64-v8.0.0.F-build0167-FORTINET.out.ovf" / "fortios.vmdk", 5000)
        self.w(self.inbox / "FGT_VM64-v7.6.7.M-build3704-FORTINET.out.ovf.zip", 3000)
        self.w(self.inbox / "Acme Proposal_v2.docx", 220)
        self.w(self.para / "1-Projects" / "Acme" / "Acme Proposal.docx", 200)
        self.w(self.inbox / "setup-tool.exe", 900)
        self.cfg = {"inbox_folders": [self.inbox], "para_root": self.para, "database": self.tmp / "t.db"}
        self.report = self.tmp / "library_report.json"
        for p in (mock.patch.object(library, "REPORT_FILE", self.report),
                  mock.patch.object(library, "check_signatures", side_effect=self.fake_signatures)):
            p.start()
            self.addCleanup(p.stop)
        self.sign_calls = []

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def w(self, p: Path, size: int):
        p.write_bytes(b"x" * size)
        os.utime(p, (1_700_000_000 + size, 1_700_000_000 + size))

    def fake_signatures(self, paths):
        self.sign_calls.append(list(paths))
        return {p: {"path": p, "status": "NotSigned", "subject": "", "expires": ""} for p in paths}

    def snapshot(self):
        return sorted((str(p.relative_to(self.tmp)), p.stat().st_size, p.stat().st_mtime_ns)
                      for p in list(self.inbox.rglob("*")) + list(self.para.rglob("*")))

    def test_scan_reads_and_changes_nothing(self):
        before = self.snapshot()
        rep = library.scan(self.cfg)
        self.assertEqual(self.snapshot(), before)
        self.assertEqual(len(rep["images"]), 1)
        g = rep["images"][0]
        self.assertEqual((g["product"], g["versions"], g["size"], g["in_downloads"]), ("FortiGate VM64", ["8.0.0", "7.6.7"], 8100, 2))
        self.assertEqual([(i["version"], i["is_dir"], i["files"]) for i in g["items"]], [("8.0.0", True, 2), ("7.6.7", False, 1)])
        self.assertEqual([(c["title"], c["filed_is_older"]) for c in rep["versions"]], [("acme proposal", True)])
        self.assertEqual([(i["name"], i["level"]) for i in rep["installers"]], [("setup-tool.exe", "unsigned")])
        self.assertEqual(len(self.sign_calls), 1)
        library.scan(self.cfg)                      # nothing changed: Windows is not asked again
        self.assertEqual(len(self.sign_calls), 1)
        self.w(self.inbox / "setup-tool.exe", 950)  # the file changed: asked again
        library.scan(self.cfg)
        self.assertEqual(len(self.sign_calls), 2)

    def test_view_dismiss_and_show(self):
        library.scan(self.cfg)
        v = library.view(self.cfg)
        self.assertEqual(v["counts"], {"images": 1, "versions": 1, "similar": 0, "installers": 1})
        self.assertEqual(v["summary"], {"images_bytes": 8100, "images_in_downloads_bytes": 8100, "filed_is_older": 1,
                                        "not_signed": 1})
        web_ui.Ctx.cfg, web_ui.Ctx.log = self.cfg, logging.getLogger("sf-test")

        class H:
            def _send(self, code, body, ctype="application/json"):
                self.code, self.body = code, body
        h = H()
        post = lambda path, body: (web_ui._library_post(h, path, body), (h.code, h.body.get("ok")))[1]
        self.assertEqual(post("/api/library/dismiss", {"kind": "versions", "key": "acme proposal|.docx"}), (200, True))
        self.assertEqual(post("/api/library/dismiss", {"kind": "versions", "key": "made up"}), (400, False))
        self.assertEqual(post("/api/library/dismiss", {"kind": "files", "key": "x"}), (400, False))
        v = library.view(self.cfg)
        self.assertEqual((v["counts"]["versions"], v["dismissed"], v["summary"]["filed_is_older"]), (0, 1, 0))
        self.assertEqual(post("/api/library/dismiss", {"kind": "versions", "key": "acme proposal|.docx", "undo": True}), (200, True))
        self.assertEqual(library.view(self.cfg)["counts"]["versions"], 1)
        post("/api/library/dismiss", {"kind": "installers", "key": str(self.inbox / "setup-tool.exe")})
        self.assertEqual(post("/api/library/restore", {}), (200, True))
        self.assertEqual(library.view(self.cfg)["dismissed"], 0)
        # Show opens Explorer only for a path the last scan listed
        self.assertEqual(post("/api/library/reveal", {"path": str(self.tmp / "t.db")}), (400, False))
        self.assertEqual(post("/api/library/reveal", {"path": r"C:\Windows\System32\cmd.exe"}), (400, False))

    def test_switched_off(self):
        library.scan(self.cfg)
        self.cfg["library"] = {"enabled": False}
        v = library.view(self.cfg)
        self.assertEqual((v["enabled"], v["counts"]["images"]), (False, 0))
        self.assertFalse(library.Runner.due(self.cfg))


if __name__ == "__main__":
    unittest.main()
