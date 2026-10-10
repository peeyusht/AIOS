"""Document watch: dates that matter and sensitive files in Downloads, read from the search index's text."""
import shutil
import sqlite3
import sys
import tempfile
import unittest
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import watch  # noqa: E402

TODAY = date(2026, 10, 11)


def with_check_digit(prefix: str, ok) -> str:
    return next(prefix + str(d) for d in range(10) if ok(prefix + str(d)))


AADHAAR = with_check_digit("49382716504", watch._verhoeff)          # made up, passes the checksum
CARD = with_check_digit("453914880343646", watch._luhn)             # made up, passes the checksum
A4 = f"{AADHAAR[:4]} {AADHAAR[4:8]} {AADHAAR[8:]}"
C4 = f"{CARD[:4]} {CARD[4:8]} {CARD[8:12]} {CARD[12:]}"


class DatesTest(unittest.TestCase):
    def dates(self, text):
        return [(d["date"], d["kind"]) for d in watch.find_dates(text, TODAY)]

    def test_formats(self):
        for text, want in (
            ("Policy No 123. Expiry Date: 31/12/2026", ("2026-12-31", "expires")),
            ("Valid until 17 October 2026", ("2026-10-17", "valid until")),
            ("valid upto : 02-Oct-2030", ("2030-10-02", "valid until")),
            ("Due Date : 08/10/2026 P.O.#", ("2026-10-08", "due")),
            ("Passport Expiry: 30th December 2028", ("2028-12-30", "expires")),
            ("Renewal date 2027-03-01", ("2027-03-01", "renewal")),
            ("certificate expiring Jul 10, 2027.", ("2027-07-10", "expires")),
            ("PO Validity: 12-03-2027", ("2027-03-12", "valid until")),
            ("Policy end date 5.1.27", ("2027-01-05", "ends")),
        ):
            self.assertEqual(self.dates(text), [want], text)

    def test_a_start_date_is_not_a_deadline(self):
        self.assertEqual(self.dates("Validity: from 26 Sept 2026 Place of supply"), [])
        self.assertEqual(self.dates("Valid from 01/04/2026 to 31/03/2027 for all sites"), [("2027-03-31", "valid until")])
        self.assertEqual(self.dates("Validity w.e.f. 1 Jan 2026 till 31 Dec 2026"), [("2026-12-31", "valid until")])

    def test_dates_without_a_phrase_or_out_of_range_are_ignored(self):
        self.assertEqual(self.dates("Invoice date 12/10/2026. Meeting on 5 November 2026."), [])
        self.assertEqual(self.dates("Expiry date: see overleaf.\n\nPrinted on 01/01/2027"), [])
        self.assertEqual(self.dates("valid until 31/12/2099"), [])            # too far ahead to be a real deadline
        self.assertEqual(self.dates("expired on 01/01/2019"), [])             # long past
        self.assertEqual(self.dates("valid until 31/02/2027"), [])            # not a real date
        self.assertEqual(self.dates("Expiry Date: 31/12/2026 ... expiry date 31-12-2026"), [("2026-12-31", "expires")])


class SensitiveTest(unittest.TestCase):
    def test_pan_only_a_persons(self):
        self.assertEqual(watch.find_sensitive("PAN: ABCPK1234L"), {"pan": 1})
        self.assertEqual(watch.find_sensitive("Company PAN AABCK1234L, GSTIN 27AABCK1234L1Z5"), {})
        self.assertEqual(watch.find_sensitive("ref XABCPK1234L9 and abcpk1234l"), {})

    def test_aadhaar_needs_the_checksum_and_a_reason(self):
        self.assertEqual(watch.find_sensitive(f"Aadhaar No. {AADHAAR}"), {"aadhaar": 1})
        self.assertEqual(watch.find_sensitive(f"ID {A4} issued"), {"aadhaar": 1})          # written 4-4-4
        self.assertEqual(watch.find_sensitive(f"request id {AADHAAR} took 12 ms"), {})      # a number in a log
        bad = AADHAAR[:-1] + str((int(AADHAAR[-1]) + 1) % 10)
        self.assertEqual(watch.find_sensitive(f"Aadhaar No. {bad}"), {})

    def test_card_needs_the_checksum_and_a_reason(self):
        self.assertEqual(watch.find_sensitive(f"Card number {CARD} exp 09/29"), {"card": 1})
        self.assertEqual(watch.find_sensitive(f"paid with {C4}"), {"card": 1})
        self.assertEqual(watch.find_sensitive(f"txn {CARD} settled"), {})
        self.assertEqual(watch.find_sensitive("card 4111 1111 1111 1111"), {})              # the well-known test number

    def test_bank_passport_key(self):
        self.assertEqual(watch.find_sensitive("Bank: HDFC, A/c No: 50100123456789, IFSC HDFC0001234"), {"bank": 1})
        self.assertEqual(watch.find_sensitive("order account number 123456789012 shipped"), {})
        self.assertEqual(watch.find_sensitive("Passport No: Z1234567"), {"passport": 1})
        self.assertEqual(watch.find_sensitive("-----BEGIN RSA PRIVATE KEY-----\nMIIE"), {"key": 1})
        self.assertEqual(watch.find_sensitive("-----BEGIN PUBLIC KEY-----"), {})

    def test_values_are_never_returned(self):
        text = f"PAN ABCPK1234L Aadhaar {A4} card {C4} Passport No: Z1234567 A/c No: 50100123456789 bank"
        rep = repr(watch.find_sensitive(text))
        for secret in ("ABCPK1234L", AADHAAR, CARD, "Z1234567", "50100123456789"):
            self.assertNotIn(secret, rep)


class ReportTest(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="sf-test-"))
        self.db = self.tmp / "search.db"
        c = sqlite3.connect(self.db)
        c.executescript("""
            CREATE TABLE files (path TEXT PRIMARY KEY, root TEXT, source TEXT, name TEXT, folder TEXT, ext TEXT,
                size INTEGER, mtime_ns INTEGER, status TEXT, chars INTEGER, chunks INTEGER, indexed_at TEXT, error TEXT);
            CREATE TABLE chunks (id INTEGER PRIMARY KEY AUTOINCREMENT, path TEXT, idx INTEGER, text TEXT, vec BLOB);
        """)
        self.c = c
        self.add("D:/P/2-Areas/Insurance/policy.pdf", "para", "Policy schedule. Expiry Date: 20/10/2026. Insured: A. Person")
        self.add("C:/Dl/policy.pdf", "inbox", "Policy schedule. Expiry Date: 20/10/2026. Insured: A. Person")
        self.add("C:/Dl/policy (1).pdf", "inbox", "Policy schedule. Expiry Date: 20/10/2026. Insured: A. Person")
        self.add("C:/Dl/quote.pdf", "inbox", "Quotation. Valid until 1 September 2026.", "More text, PAN ABCPK1234L")
        self.add("C:/Dl/old.pdf", "inbox", "Licence valid until 1 January 2025.")
        self.add("C:/Dl/id.pdf", "inbox", f"Aadhaar {A4} and card {C4}")
        self.add("D:/P/2-Areas/ID/pan.pdf", "para", "PAN ABCPK1234L")            # filed: not a Downloads problem
        c.commit()
        self.cfg = {"database": self.tmp / "shadow.db"}

    def tearDown(self):
        self.c.close()
        shutil.rmtree(self.tmp, ignore_errors=True)

    def add(self, path, source, *chunks):
        name = path.rsplit("/", 1)[1]
        self.c.execute("INSERT INTO files VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
                       (path, "", source, name, "Folder", ".pdf", 1000, 1_700_000_000 * 10**9, "ok", 10, len(chunks), "", None))
        for i, t in enumerate(chunks):
            self.c.execute("INSERT INTO chunks (path, idx, text, vec) VALUES (?,?,?,NULL)", (path, i, f"File: {name}\n{t}"))

    def test_scan(self):
        rep = watch.scan(self.db, TODAY)
        self.assertEqual([(d["name"], d["date"], d["status"], d["days"], len(d["copies"])) for d in rep["dates"]],
                         [("policy.pdf", "2026-10-20", "soon", 9, 2), ("quote.pdf", "2026-09-01", "passed", -40, 0)])
        self.assertEqual(rep["dates"][0]["source"], "para")       # the filed copy leads, downloads are its copies
        self.assertEqual(rep["older_passed"], 1)
        self.assertEqual([(s["name"], s["level"], [(f["kind"], f["count"]) for f in s["found"]]) for s in rep["sensitive"]],
                         [("id.pdf", "high", [("aadhaar", 1), ("card", 1)]), ("quote.pdf", "medium", [("pan", 1)])])
        text = repr(rep)
        for secret in ("ABCPK1234L", AADHAAR, A4, CARD, C4):
            self.assertNotIn(secret, text)

    def test_report_and_dismiss(self):
        rep = watch.report(self.cfg, self.db, force=True)
        self.assertEqual(rep["counts"], {"soon": 1, "passed": 1, "later": 0, "sensitive": 2})
        watch.dismiss(self.cfg["database"], "D:/P/2-Areas/Insurance/policy.pdf", "date", "2026-10-20|expires")
        watch.dismiss(self.cfg["database"], "C:/Dl/id.pdf", "sensitive", "")
        rep = watch.report(self.cfg, self.db)
        self.assertEqual((rep["counts"]["soon"], rep["counts"]["sensitive"], rep["dismissed"]), (0, 1, 2))
        watch.dismiss(self.cfg["database"], "C:/Dl/id.pdf", "sensitive", "", undo=True)
        self.assertEqual(watch.report(self.cfg, self.db)["counts"]["sensitive"], 2)
        self.cfg["watch"] = {"enabled": False}
        self.assertEqual(watch.report(self.cfg, self.db)["dates"], [])


if __name__ == "__main__":
    unittest.main()
