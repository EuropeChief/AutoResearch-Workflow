import json
from pathlib import Path
import tempfile
import unittest

import implementation_review as qa


class InputReportTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.out = self.root / "output"

    def test_unsupported_archive_is_input_error_not_missing_task_material(self):
        source = self.root / "example.tar.gz"
        source.write_bytes(b"synthetic unsupported archive")
        self.assertEqual(qa.main([str(source), "--out-dir", str(self.out)]), 2)
        result = json.loads((self.out / "report.json").read_text())
        self.assertEqual(result["source"]["kind"], "file")
        self.assertEqual(result["inspection_stage"], "input")
        self.assertEqual(result["summary"]["decision"], "INCOMPLETE")
        output = (self.out / "report.txt").read_text()
        self.assertNotIn("输入目录不存在", output)
        self.assertNotIn("完成 review.json", (self.out / "return_to_expert.txt").read_text())
        self.assertFalse(list(self.out.glob("evidence-*")))

    def test_invalid_zip_preserves_structured_error_report(self):
        source = self.root / "broken.zip"
        source.write_bytes(b"not a zip")
        self.assertEqual(qa.main([str(source), "--out-dir", str(self.out)]), 2)
        result = json.loads((self.out / "report.json").read_text())
        self.assertIn("ZIP", result["inspection_error"])
        self.assertFalse(result["review"]["completed"])

    def test_invalid_review_is_distinguished_from_unreadable_input(self):
        source = self.root / "task"
        source.mkdir()
        review = self.root / "review.json"
        review.write_text("{")
        self.assertEqual(qa.main([str(source), "--out-dir", str(self.out), "--review", str(review)]), 2)
        result = json.loads((self.out / "report.json").read_text())
        self.assertEqual(result["source"]["kind"], "directory")
        self.assertEqual(result["inspection_stage"], "review")
        self.assertNotIn("没有需退回", (self.out / "return_to_expert.txt").read_text())


if __name__ == "__main__":
    unittest.main()
