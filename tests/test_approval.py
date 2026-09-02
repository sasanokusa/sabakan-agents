from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from sabakan_broker.approval import SQLiteNonceStore, approval_from_request
from sabakan_broker.models import ToolRequest

from tests.support import SECRET, build_broker


class ApprovalTests(unittest.TestCase):
    def test_l2_requires_concrete_signed_approval_and_binds_patch(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            broker, executor, principal = build_broker(Path(directory))
            request = ToolRequest(
                "config_patch",
                {"host": "local", "resource": "nginx-main", "patch": {"enabled": False}},
                incident_id="config-1",
            )
            pending = broker.prepare_approval(request, principal)
            self.assertNotIsInstance(pending, tuple)
            self.assertEqual(pending.required_plane, "approval")

            no_approval = broker.handle(request, principal)
            self.assertEqual(no_approval.code, "APPROVAL_REQUIRED")
            self.assertEqual(executor.mutation_calls, [])

            approval = approval_from_request(pending, plane="approval", secret=SECRET)
            executor.config["external_change"] = True
            stale = broker.handle(request, principal, approval)
            self.assertEqual(stale.code, "PRECONDITION_FAILED")
            self.assertEqual(executor.mutation_calls, [])

            fresh_request = ToolRequest(
                "config_patch",
                {"host": "local", "resource": "nginx-main", "patch": {"enabled": False}},
                incident_id="config-2",
            )
            fresh_pending = broker.prepare_approval(fresh_request, principal)
            fresh_approval = approval_from_request(fresh_pending, plane="approval", secret=SECRET)
            applied = broker.handle(fresh_request, principal, fresh_approval)
            self.assertTrue(applied.ok)
            self.assertEqual(applied.code, "MUTATION_VERIFIED")
            self.assertFalse(executor.config["enabled"])

            replay = broker.handle(fresh_request, principal, fresh_approval)
            self.assertEqual(replay.code, "APPROVAL_REPLAY")

    def test_l3_requires_out_of_band_approval_plane(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            broker, executor, principal = build_broker(Path(directory))
            request = ToolRequest("system_reboot", {"host": "local"}, incident_id="reboot-1")
            pending = broker.prepare_approval(request, principal)
            self.assertEqual(pending.required_plane, "oob")
            wrong_plane = approval_from_request(pending, plane="approval", secret=SECRET)
            result = broker.handle(request, principal, wrong_plane)
            self.assertEqual(result.code, "APPROVAL_PLANE_REQUIRED")
            self.assertEqual(executor.mutation_calls, [])

    def test_tampered_signature_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            broker, executor, principal = build_broker(Path(directory))
            request = ToolRequest(
                "config_patch",
                {"host": "local", "resource": "nginx-main", "patch": {"safe": True}},
                incident_id="tamper-1",
            )
            pending = broker.prepare_approval(request, principal)
            approval = approval_from_request(pending, plane="approval", secret=SECRET)
            tampered = approval.__class__(**{**approval.__dict__, "operation_hash": "tampered"})
            result = broker.handle(request, principal, tampered)
            self.assertEqual(result.code, "APPROVAL_MISMATCH")
            self.assertEqual(executor.mutation_calls, [])

    def test_nonce_store_survives_verifier_restart(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            nonce_path = Path(directory) / "nonces.db"
            first_store = SQLiteNonceStore(nonce_path)
            broker, executor, principal = build_broker(Path(directory))
            # Replace the in-memory verifier with the durable one for this flow.
            from sabakan_broker.approval import ApprovalVerifier

            broker.approval_verifier = ApprovalVerifier(SECRET, nonce_store=first_store)
            request = ToolRequest(
                "config_patch",
                {"host": "local", "resource": "nginx-main", "patch": {"durable": True}},
                incident_id="nonce-1",
            )
            pending = broker.prepare_approval(request, principal)
            approval = approval_from_request(pending, plane="approval", secret=SECRET)
            self.assertTrue(broker.handle(request, principal, approval).ok)
            first_store.close()

            second_store = SQLiteNonceStore(nonce_path)
            broker.approval_verifier = ApprovalVerifier(SECRET, nonce_store=second_store)
            replay = broker.handle(request, principal, approval)
            self.assertEqual(replay.code, "APPROVAL_REPLAY")
            second_store.close()
