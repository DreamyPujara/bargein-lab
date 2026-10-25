import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

import tool


class MetricsTests(unittest.TestCase):
    def test_summarize_measures_delay_after_user_interruption(self):
        events = [
            {"time_ms": 0, "type": "agent_start"},
            {"time_ms": 100, "type": "user_start"},
            {"time_ms": 240, "type": "agent_stop"},
            {"time_ms": 400, "type": "user_start"},  # ignored: agent is not speaking
        ]

        summary = tool.summarize(events)

        self.assertEqual(summary["interruptions"], 1)
        self.assertEqual(summary["completed_cancellations"], 1)
        self.assertEqual(summary["missed_cancellations"], 0)
        self.assertEqual(summary["delays_ms"], [140])
        self.assertEqual(summary["avg_delay_ms"], 140.0)
        self.assertEqual(summary["p95_delay_ms"], 140)
        self.assertEqual(summary["max_delay_ms"], 140)

    def test_missed_cancellation_when_agent_never_stops(self):
        events = [
            {"time_ms": 0, "type": "agent_start"},
            {"time_ms": 50, "type": "user_start"},
        ]

        summary = tool.summarize(events)

        self.assertEqual(summary["interruptions"], 1)
        self.assertEqual(summary["completed_cancellations"], 0)
        self.assertEqual(summary["missed_cancellations"], 1)
        self.assertIsNone(summary["p95_delay_ms"])

    def test_unsorted_events_are_handled_deterministically(self):
        events = [
            {"time_ms": 300, "type": "agent_stop"},
            {"time_ms": 100, "type": "user_start"},
            {"time_ms": 0, "type": "agent_start"},
        ]

        self.assertEqual(tool.summarize(events)["delays_ms"], [200])

    def test_compare_fails_on_p95_regression(self):
        baseline = tool.summarize([
            {"time_ms": 0, "type": "agent_start"},
            {"time_ms": 100, "type": "user_start"},
            {"time_ms": 200, "type": "agent_stop"},
        ])
        candidate = tool.summarize([
            {"time_ms": 0, "type": "agent_start"},
            {"time_ms": 100, "type": "user_start"},
            {"time_ms": 260, "type": "agent_stop"},
        ])

        passed, failures = tool.compare_summaries(
            baseline,
            candidate,
            max_p95_ms=300,
            max_regression_ms=25,
            allow_more_missed=False,
        )

        self.assertFalse(passed)
        self.assertTrue(any("regressed" in f for f in failures))


class CliTests(unittest.TestCase):
    def write_json(self, directory, name, events):
        path = Path(directory) / name
        path.write_text(json.dumps({"events": events}), encoding="utf-8")
        return path

    def test_measure_cli_outputs_json(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = self.write_json(tmp, "events.json", [
                {"time_ms": 0, "type": "agent_start"},
                {"time_ms": 100, "type": "user_start"},
                {"time_ms": 210, "type": "agent_stop"},
            ])

            result = subprocess.run(
                [sys.executable, "tool.py", "measure", str(path)],
                check=False,
                capture_output=True,
                text=True,
            )

        self.assertEqual(result.returncode, 0, result.stderr)
        payload = json.loads(result.stdout)
        self.assertEqual(payload["delays_ms"], [110])

    def test_compare_cli_returns_one_when_gate_fails(self):
        with tempfile.TemporaryDirectory() as tmp:
            baseline = self.write_json(tmp, "baseline.json", [
                {"time_ms": 0, "type": "agent_start"},
                {"time_ms": 100, "type": "user_start"},
                {"time_ms": 200, "type": "agent_stop"},
            ])
            candidate = self.write_json(tmp, "candidate.json", [
                {"time_ms": 0, "type": "agent_start"},
                {"time_ms": 100, "type": "user_start"},
                {"time_ms": 500, "type": "agent_stop"},
            ])

            result = subprocess.run(
                [
                    sys.executable,
                    "tool.py",
                    "compare",
                    str(baseline),
                    str(candidate),
                    "--max-p95-ms",
                    "250",
                ],
                check=False,
                capture_output=True,
                text=True,
            )

        self.assertEqual(result.returncode, 1)
        payload = json.loads(result.stdout)
        self.assertFalse(payload["passed"])
        self.assertTrue(payload["failures"])


if __name__ == "__main__":
    unittest.main()
