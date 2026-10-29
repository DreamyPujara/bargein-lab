import json
import tempfile
import unittest
from pathlib import Path

from tool import load_events


class BooleanTimestampValidationTests(unittest.TestCase):
    def test_json_boolean_time_ms_is_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "events.json"
            path.write_text(
                json.dumps({"events": [{"time_ms": True, "type": "agent_start"}]}),
                encoding="utf-8",
            )

            with self.assertRaisesRegex(ValueError, "time_ms must be a non-negative integer"):
                load_events(path)

    def test_integer_zero_time_ms_is_still_accepted(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "events.json"
            path.write_text(
                json.dumps({"events": [{"time_ms": 0, "type": "agent_start"}]}),
                encoding="utf-8",
            )

            self.assertEqual(load_events(path), [{"time_ms": 0, "type": "agent_start"}])


if __name__ == "__main__":
    unittest.main()
