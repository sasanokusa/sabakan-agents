from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from sabakan_broker.api import BrokerAPI
from sabakan_broker.dummy_agent import DummyDiagnosis
from sabakan_broker.models import Principal

from tests.support import build_broker


class BrokerAPITests(unittest.TestCase):
    def test_api_uses_authenticated_principal_context_not_payload_roles(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            broker, executor, principal = build_broker(Path(directory))
            api = BrokerAPI(broker)
            payload = {
                "tool": "service_restart",
                "arguments": {"host": "local", "service": "nginx"},
                "principal": "attacker",
                "roles": ["owner"],
            }
            result = api.handle(payload, principal=Principal("alice", roles=frozenset({"observer"})))
            self.assertEqual(result["code"], "ROLE_DENIED")
            self.assertEqual(executor.mutation_calls, [])

    def test_dummy_agent_can_only_use_typed_broker_operations(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            broker, executor, principal = build_broker(Path(directory))
            results = DummyDiagnosis(BrokerAPI(broker)).inspect_and_restart_nginx("local", principal)
            self.assertEqual(results[0]["code"], "READ_OK")
            self.assertEqual(results[1]["code"], "MUTATION_VERIFIED")
            self.assertEqual(len(executor.mutation_calls), 1)
