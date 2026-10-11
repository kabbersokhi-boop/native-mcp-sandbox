#!/usr/bin/env python3
"""Exercise reports against the actual native executable and changed evidence."""

from __future__ import annotations

import argparse
import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "agent"))

from native_mcp_agent.demo import DemoFailure, fixture_text, run_demo
from native_mcp_agent.transcript import parse_bounded_transcript

SERVER = Path()


class FlagshipDemoTests(unittest.TestCase):
    def setUp(self):
        self.workspace = tempfile.TemporaryDirectory()
        self.addCleanup(self.workspace.cleanup)
        self.root = Path(self.workspace.name)

    def run_scenario(self, scenario, **kwargs):
        output = self.root / scenario
        report = run_demo(SERVER, scenario, output, **kwargs)
        self.assertEqual(json.loads((output / "report.json").read_bytes()), report)
        events = parse_bounded_transcript((output / "transcript.json").read_bytes())
        pairs = {
            (event["metadata"]["action"], int(event["metadata"]["response"]))
            for event in events
            if event["event"] == "evidence_validated"
        }
        for item in report["evidence"]:
            self.assertIn((item["actionId"], item["responseId"]), pairs)
        identifiers = {item["id"] for item in report["evidence"]}
        for item in report["facts"] + report["inferences"] + report["rejections"]:
            self.assertTrue(set(item["evidence"]) <= identifiers)
        return report

    def test_recovered_uses_all_four_real_tools(self):
        report = self.run_scenario("recovered")
        self.assertEqual(report["result"], "recovery-observed")
        self.assertEqual(
            [item["tool"] for item in report["evidence"]],
            ["logs.search", "logs.tail", "elf.inspect", "proc.memory"],
        )
        self.assertTrue(report["evidence"][3]["structured"]["pidfdPinned"])

    def test_incomplete_search_does_not_claim_recovery(self):
        report = self.run_scenario("inconclusive")
        self.assertEqual(report["result"], "inconclusive")
        self.assertTrue(report["evidence"][0]["structured"]["matchLimitReached"])
        self.assertEqual(report["evidence"][2]["structured"]["machineNumber"], 183)
        self.assertFalse(any("reports recovery" in item["claim"] for item in report["inferences"]))

    def test_hostile_distinguishes_native_and_python_rejections(self):
        report = self.run_scenario("hostile")
        self.assertEqual(report["result"], "boundary-held")
        self.assertEqual(
            [item["layer"] for item in report["rejections"]],
            ["C++ file policy", "Python proposal validation"],
        )
        self.assertEqual(
            report["evidence"][4]["structured"]["error"]["code"], "invalid_relative_path"
        )
        self.assertNotIn("NMS_OUTSIDE_ROOT_SENTINEL", json.dumps(report))
        self.assertFalse(any(item["tool"] == "shell.exec" for item in report["evidence"]))
        self.assertIn("<img", json.dumps(report))

    def test_changed_log_changes_conclusion(self):
        changed = fixture_text("recovered").replace('"recovered"', '"retry"')
        report = self.run_scenario("recovered", log_text=changed)
        self.assertEqual(report["result"], "inconclusive")

    def test_untrusted_event_shapes_do_not_become_inferences(self):
        report = self.run_scenario("recovered", log_text='{"incident":"INC-042","event":[]}\n')
        self.assertEqual(report["result"], "inconclusive")

    def test_canonical_report_is_stable_across_processes(self):
        first = self.run_scenario("hostile")
        second = self.run_scenario("hostile")
        self.assertEqual(first, second)
        runtime = json.loads((self.root / "hostile" / "run.json").read_bytes())
        self.assertEqual(runtime["processObservations"][0]["pid"], "<redacted>")
        self.assertEqual(runtime["processObservations"][0]["threads"], 3)
        self.assertNotIn("pid", first["evidence"][3]["structured"])

    def test_oversized_fixture_is_rejected(self):
        with self.assertRaises(DemoFailure):
            self.run_scenario("recovered", log_text="x" * 65537)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--server", type=Path, required=True)
    arguments, remaining = parser.parse_known_args()
    SERVER = arguments.server.resolve()
    unittest.main(argv=[__file__, *remaining])
