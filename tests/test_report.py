import importlib.util
import json
from pathlib import Path
import tempfile
import unittest

spec = importlib.util.spec_from_file_location("report", Path(__file__).resolve().parents[1] / "scripts/report.py")
report = importlib.util.module_from_spec(spec)
spec.loader.exec_module(report)


class ReportTests(unittest.TestCase):
    def test_escapes_model_metadata_and_manual_annotations(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            (root / "decisions.jsonl").write_text(json.dumps({
                "step": 0, "decision": {"buttons": ['<script>'], "scene": '<img src=x onerror=alert(1)>',
                "rationale": '<script>alert(1)</script>', "stop": True}, "images": [],
                "decision_latency_ms": 42}) + "\n")
            (root / "run_summary.json").write_text(json.dumps({"goal": "<script>goal</script>"}))
            output = report.build_report(root, root / "report.html", {"0": {"notes": "<script>manual</script>", "collisions": 0}})
            rendered = output.read_text()
            self.assertNotIn("<script>", rendered)
            self.assertIn("&lt;script&gt;", rendered)
            self.assertIn("Manual evaluation", rendered)
            self.assertIn("collisions", rendered)
            self.assertIn("42 ms", rendered)

    def test_final_observation_included_once_without_decision(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            initial, final = root / "before.png", root / "after #1.png"
            initial.write_bytes(b"fixture")
            final.write_bytes(b"fixture")
            (root / "decisions.jsonl").write_text(json.dumps({"step": 0,
                "decision": {"buttons": [], "scene": "driving", "rationale": "Clear", "stop": False},
                "images": [str(initial)]}) + "\n")
            (root / "events.jsonl").write_text("\n".join(json.dumps({"image_path": str(p)}) for p in (initial, final, final)))
            rendered = report.build_report(root, root / "report.html").read_text()
            self.assertEqual(rendered.count('<img '), 2)
            self.assertIn("after%20%231.png", rendered)
            self.assertIn("Additional recorded observation", rendered)
            self.assertIn("Not manually evaluated", rendered)

    def test_manual_only_session_has_images_without_fabricated_decisions(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            image = root / "frame.png"
            image.write_bytes(b"fixture")
            (root / "events.jsonl").write_text(json.dumps({"image_path": str(image)}) + "\n")
            rendered = report.build_report(root, root / "report.html").read_text()
            self.assertIn("0 decisions", rendered)
            self.assertIn('<img ', rendered)
            self.assertIn("No model latency measurements", rendered)
            self.assertNotIn("Manual evaluation</summary>", rendered)


if __name__ == "__main__":
    unittest.main()
