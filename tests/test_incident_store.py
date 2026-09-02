from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from sabakan_broker.incident import AgentState, IncidentStateStore


class IncidentStoreTests(unittest.TestCase):
    def test_state_machine_and_structured_memory_persist(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "incidents.db"
            store = IncidentStateStore(path)
            store.create("i-1", "restore nginx")
            store.transition("i-1", AgentState.OBSERVE)
            store.append_observation("i-1", {"source_type": "untrusted_log", "event": "timeout"})
            store.transition("i-1", AgentState.DIAGNOSE)
            store.append_hypothesis("i-1", {"cause": "backend_down"})
            snapshot = store.get("i-1")
            self.assertEqual(snapshot.current_state, AgentState.DIAGNOSE)
            self.assertEqual(snapshot.observations[0]["source_type"], "untrusted_log")
            self.assertEqual(snapshot.hypotheses[0]["cause"], "backend_down")
            store.close()

            reopened = IncidentStateStore(path)
            self.assertEqual(reopened.get("i-1").current_state, AgentState.DIAGNOSE)
            with self.assertRaises(ValueError):
                reopened.transition("i-1", AgentState.EXECUTE)
            reopened.close()
