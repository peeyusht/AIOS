"""File-name suggestions: which words in a file name can name a folder, including short ones."""
import sys
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import suggest  # noqa: E402

DESTS = ["1-Projects/GR-One", "1-Projects/Pavak-Incorporation", "1-Projects/Muthoot-FortiNAC",
         "1-Projects/Lifestyle-FortiNAC", "3-Resources/NAC-Framework-Library", "4-Archives/HCL-Completed",
         "4-Archives/CBS-Completed", "4-Archives/Q3-2026", "4-Archives/365-Completed"]


class NameKeysTest(unittest.TestCase):
    def test_short_words_count_only_joined_to_a_neighbour(self):
        for name in ("GR-One", "gr_one report", "GR One", "GROne", "Notes for GR.One v2"):
            self.assertIn("grone", suggest._name_keys(name), name)
        keys = suggest._name_keys("GR-One_FortiNAC_Activity_Sheet_09Oct2026")
        self.assertTrue({"grone", "one", "fortinac", "activity", "sheet", "09oct2026"} <= keys)
        self.assertNotIn("gr", keys)

    def test_general_words_and_bare_numbers_never_count(self):
        keys = suggest._name_keys("Finance bank 365 2026 01 02 v3")
        self.assertFalse(keys & {"finance", "bank", "365", "01", "02", "0102", "v3", "3652026"})
        self.assertIn("2026", keys)  # 4+ characters: as before


class NameOwnersTest(unittest.TestCase):
    def test_new_short_folder_is_matched(self):
        own = suggest.name_owners(DESTS)
        self.assertEqual(own["grone"], "1-Projects/GR-One")
        self.assertEqual(own["pavak"], "1-Projects/Pavak-Incorporation")
        self.assertEqual(own["hcl"], "4-Archives/HCL-Completed")       # nothing filed says otherwise
        self.assertEqual(own["q32026"], "4-Archives/Q3-2026")
        self.assertNotIn("fortinac", own)                              # names two folders
        self.assertNotIn("365", own)
        self.assertNotIn("gr", own)

    def test_three_letter_word_needs_the_filed_files_to_agree(self):
        filed = ([("FortiNAC NAC design", "1-Projects/Muthoot-FortiNAC")] * 9
                 + [("NAC framework", "3-Resources/NAC-Framework-Library")] * 2
                 + [("HCL SOW", "4-Archives/HCL-Completed")] * 4 + [("HCL invoice", "2-Areas/Finance")]
                 + [("CBS audit", "4-Archives/CBS-Completed")] * 3 + [("CBS news", "2-Areas/Finance")])
        own = suggest.name_owners(DESTS, filed)
        self.assertNotIn("nac", own)                                   # 2 of 11
        self.assertEqual(own["hcl"], "4-Archives/HCL-Completed")       # 4 of 5 = 80%
        self.assertNotIn("cbs", own)                                   # 3 of 4 = 75%
        self.assertEqual(suggest.name_owners(DESTS, filed, short_share=0.75)["cbs"], "4-Archives/CBS-Completed")
        self.assertEqual(own["pavak"], "1-Projects/Pavak-Incorporation")  # longer words are not gated
        self.assertEqual(own["grone"], "1-Projects/GR-One")


class SuggestTest(unittest.TestCase):
    def suggester(self, examples=()):
        dests = mock.Mock()
        dests.get.return_value = DESTS
        index = mock.Mock(docvecs={})
        index.labelled.return_value = [(f"D:/Organized/{label}/{stem}.pdf", label, None) for stem, label in examples]
        index.fingerprint.return_value = None
        return suggest.Suggester({"rules": [], "destination_depth": 2}, index, dests, None)

    def names(self, sg, file):
        return [(c["folder"], c["why"]) for c in sg.suggest("C:/Downloads/" + file)["candidates"]
                if c["source"] == "name"]

    def test_file_named_after_a_short_folder(self):
        sg = self.suggester()
        self.assertEqual(self.names(sg, "GR-One_FortiNAC_Activity_Sheet_09Oct2026.xlsx"),
                         [("1-Projects/GR-One", "file name mentions 'grone'")])
        self.assertEqual(self.names(sg, "gr one kickoff.pdf"), [("1-Projects/GR-One", "file name mentions 'grone'")])
        self.assertEqual(self.names(sg, "HCL_SOW_signed.pdf"), [("4-Archives/HCL-Completed", "file name mentions 'hcl'")])
        self.assertEqual(self.names(sg, "program one-pager.pdf"), [])   # 'one' alone names nothing
        self.assertEqual(self.names(sg, "Pavak GR-One comparison.pdf"), [])  # two folders named: no suggestion

    def test_filed_files_switch_an_unreliable_short_word_off(self):
        sg = self.suggester([("NAC design", "1-Projects/Muthoot-FortiNAC")] * 5)
        self.assertEqual(self.names(sg, "NAC rollout plan.pdf"), [])
        self.assertEqual(self.names(self.suggester(), "NAC rollout plan.pdf"),
                         [("3-Resources/NAC-Framework-Library", "file name mentions 'nac'")])


if __name__ == "__main__":
    unittest.main()
