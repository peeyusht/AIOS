"""PDFs protected only against editing are read; ones that need a password are never opened."""
import logging
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import shadow_agent as sa  # noqa: E402

CFG = {"extraction": {"max_chars": 2000, "max_pdf_pages": 5}, "_no_ocr": True}
TEXT = "Shadow Filer extraction test 4821"


def make_pdf(path: Path, user=None, owner=None, algorithm="AES-256"):
    from pypdf import PdfWriter
    from pypdf.generic import DecodedStreamObject, DictionaryObject, NameObject
    w = PdfWriter()
    page = w.add_blank_page(width=300, height=200)
    font = DictionaryObject({NameObject("/Type"): NameObject("/Font"), NameObject("/Subtype"): NameObject("/Type1"),
                             NameObject("/BaseFont"): NameObject("/Helvetica")})
    page[NameObject("/Resources")] = DictionaryObject(
        {NameObject("/Font"): DictionaryObject({NameObject("/F1"): w._add_object(font)})})
    stream = DecodedStreamObject()
    stream.set_data(f"BT /F1 12 Tf 20 100 Td ({TEXT}) Tj ET".encode())
    page[NameObject("/Contents")] = w._add_object(stream)
    if owner is not None:
        w.encrypt(user_password=user or "", owner_password=owner, algorithm=algorithm)
    with open(path, "wb") as f:
        w.write(f)


class PdfExtractionTest(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="sf-test-"))
        logging.getLogger("shadow").addHandler(logging.NullHandler())

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def check(self, name, readable, **kw):
        p = self.tmp / name
        make_pdf(p, **kw)
        with self.assertLogs("shadow", level="INFO") as logs:
            logging.getLogger("shadow").info("start")
            text = sa.extract_text(p, CFG)
        self.assertEqual(TEXT in text, readable, name)
        self.assertEqual(sa.is_encrypted_pdf(p), not readable, name)
        self.assertFalse([r for r in logs.records if r.levelno >= logging.WARNING], name)
        return logs

    def test_plain_pdf(self):
        self.check("plain.pdf", True)

    def test_protected_against_editing_only_is_read(self):
        self.check("owner-aes256.pdf", True, owner="secret-owner")
        self.check("owner-aes128.pdf", True, owner="secret-owner", algorithm="AES-128")
        self.check("owner-rc4.pdf", True, owner="secret-owner", algorithm="RC4-128")

    def test_needs_a_password_is_never_opened(self):
        for alg in ("AES-256", "RC4-128"):
            logs = self.check(f"locked-{alg}.pdf", False, user="open-sesame", owner="secret-owner", algorithm=alg)
            self.assertTrue(any("password-protected" in r.getMessage() for r in logs.records))


if __name__ == "__main__":
    unittest.main()
