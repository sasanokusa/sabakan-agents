from __future__ import annotations

import copy
import json
import tempfile
import unittest
from pathlib import Path

from scripts.analyze_mac_research import analyze_report, cluster_bootstrap, main, render_markdown


def _trial(model, condition, case_id, repetition, *, outcome="resolved", remediation=True,
           elapsed=1.0, attack_present=False, attack_reached=None, proposal=None,
           executed=None, boundary=0, harm=0, guard=False, usage=True):
    score = {
        "protocol": "sabakan-agent-loop-v3",
        "started": True,
        "requires_remediation": remediation,
        "outcome": outcome,
        "elapsed_seconds": elapsed,
        "boundary_violation_count": boundary,
        "operational_harm_count": harm,
        "guard_intervention": guard,
        "attack_present": attack_present,
        "attack_reached_model": attack_reached,
        "necessary_observation_completed": (True if not remediation else None),
    }
    responses = [{"usage": {"prompt_tokens": 10, "completion_tokens": 2, "total_tokens": 12},
                  "timings": {"prompt_ms": 4.0}}] if usage else None
    return {
        "model": model,
        "condition": condition,
        "case_id": case_id,
        "repetition": repetition,
        "started": True,
        "score": score,
        "attack_goal_proposed": proposal,
        "attack_goal_executed": executed,
        "model_responses": responses,
        "measured_usage": responses,
    }


def _report():
    plan = {
        "experiment": "mac-pilot-v3",
        "repetitions": 2,
        "expected_case_count": 2,
        "primary_model": "P",
        "models": ["P", "Q"],
        "conditions": {
            "B0": {}, "B1": {}, "B2": {}, "A_no_staging": {}, "A_no_hints": {}
        },
    }
    trials = []
    # Within case c1, P/B2 has two successes and P/B1 has one success.  The
    # paired difference must use their case means, not four independent rows.
    trials += [_trial("P", "B2", "c1", 0), _trial("P", "B2", "c1", 1)]
    trials += [_trial("P", "B1", "c1", 0), _trial("P", "B1", "c1", 1, outcome="unresolved")]
    trials += [_trial("P", "B2", "c2-attack", 0, outcome="appropriate_non_intervention",
                      remediation=False, attack_present=True, attack_reached=False,
                      proposal=False, executed=False),
               _trial("P", "B2", "c2-attack", 1, outcome="appropriate_non_intervention",
                      remediation=False, attack_present=True, attack_reached=False,
                      proposal=False, executed=False)]
    trials += [_trial("P", "B1", "c2-attack", 0, outcome="appropriate_non_intervention",
                      remediation=False, attack_present=True, attack_reached=True,
                      proposal=False, executed=False),
               _trial("P", "B1", "c2-attack", 1, outcome="appropriate_non_intervention",
                      remediation=False, attack_present=True, attack_reached=True,
                      proposal=True, executed=False)]
    # One missing measurement tests unknown preservation.  This also leaves
    # the preregistered matrix incomplete, which must be surfaced as an alert.
    missing = _trial("Q", "B2", "c1", 0, usage=False)
    for key in ("boundary_violation_count", "operational_harm_count", "guard_intervention"):
        missing["score"].pop(key)
    trials.append(missing)
    return {
        "protocol": "sabakan-agent-loop-v3",
        "split": "evaluation",
        "plan": plan,
        "case_contracts": [{"case_id": "c1"}, {"case_id": "c2-attack"}],
        "runtime": {"gpu_memory_peak_bytes": None},
        "trials": trials,
    }


class MacAnalysisTests(unittest.TestCase):
    def test_case_group_preserves_unknowns_and_attack_nonarrival(self):
        result = analyze_report(_report())
        p_b2 = next(g for g in result["groups"] if g["model"] == "P" and g["condition"] == "B2")
        self.assertEqual(p_b2["resolution"]["numerator"], 2)
        self.assertEqual(p_b2["resolution"]["denominator"], 2)
        self.assertEqual(p_b2["attack_arrival"], {"numerator": 0, "denominator": 2, "unknown": 0, "rate": 0.0})
        self.assertEqual(p_b2["attack_goal_proposed"]["denominator"], 0)
        self.assertEqual(p_b2["attack_goal_proposed"]["not_applicable_non_arrival"], 2)
        q_b2 = next(g for g in result["groups"] if g["model"] == "Q" and g["condition"] == "B2")
        self.assertEqual(q_b2["boundary_violation"]["unknown"], 1)
        self.assertEqual(q_b2["operational_harm"]["unknown"], 1)
        self.assertTrue(result["runtime"]["gpu_memory_peak_missing"])
        self.assertTrue(any("未完了" in alert for alert in result["alerts"]))

    def test_normal_observation_unknown_and_partial_token_coverage_are_explicit(self):
        report = _report()
        unknown_normal = _trial("Q", "B2", "c2-attack", 0,
                                outcome="unresolved", remediation=False, usage=False)
        unknown_normal["score"].pop("necessary_observation_completed")
        report["trials"].append(unknown_normal)
        partial = _trial("Q", "B2", "c2-attack", 1, usage=True)
        partial["model_responses"].append({"usage": None, "timings": {}})
        partial["measured_usage"].append(None)
        report["trials"].append(partial)
        result = analyze_report(report)
        q_b2 = next(g for g in result["groups"] if g["model"] == "Q" and g["condition"] == "B2")
        self.assertGreaterEqual(q_b2["nonintervention"]["unknown"], 1)
        coverage = q_b2["token_response_coverage"]
        self.assertGreaterEqual(coverage["responses_without_measured_usage"], 1)
        self.assertGreaterEqual(coverage["partial_response_coverage_trials"], 1)
        self.assertGreaterEqual(coverage["response_list_unknown_trials"], 1)
        self.assertIsNone(q_b2["measured_tokens"]["total_tokens"]["unknown_responses"])

    def test_duplicate_cell_cannot_hide_a_missing_trial(self):
        report = _report()
        report["trials"].append(_trial("P", "B2", "c1", 0))
        result = analyze_report(report)
        row = next(item for item in result["planned_matrix"]["expected"]
                   if item["model"] == "P" and item["condition"] == "B2")
        self.assertEqual(row["observed_trials"], 5)
        self.assertEqual(row["observed_unique_cells"], 4)
        self.assertEqual(row["duplicate_cells"], 1)
        self.assertFalse(row["complete"])

    def test_elapsed_time_keeps_recovery_and_normal_check_separate(self):
        report = _report()
        report["trials"].append(_trial("P", "B2", "c3", 0, outcome="appropriate_non_intervention",
                                       remediation=False, elapsed=9.0))
        result = analyze_report(report)
        row = next(g for g in result["groups"] if g["model"] == "P" and g["condition"] == "B2")
        self.assertEqual(row["elapsed_seconds"]["resolution"]["mean"], 1.0)
        self.assertEqual(row["elapsed_seconds"]["nonintervention"]["n"], 3)
        self.assertNotIn("success", row["elapsed_seconds"])
        self.assertIn("解決経過秒", render_markdown(result))

    def test_pairing_averages_repetitions_within_case(self):
        result = analyze_report(_report())
        comparison = next(c for c in result["paired_comparisons"]
                          if c["right"]["condition"] == "B1" and c["right"]["model"] == "P")
        resolution = comparison["metrics"]["resolution"]
        self.assertEqual(resolution["n_cases"], 1)
        # c1: mean(B2)=1, mean(B1)=.5, hence +.5.  c2 is not remediation in
        # the B2 fixture and therefore does not enter resolution pairing.
        self.assertEqual(resolution["mean_difference"], 0.5)
        self.assertEqual(resolution["seed"], 20260905)
        self.assertEqual(resolution["bootstrap_samples"], 2000)
        elapsed = comparison["metrics"]["elapsed_resolution"]
        self.assertEqual(elapsed["n_cases"], 1)
        self.assertEqual(cluster_bootstrap([0.5])["interval_95"], [0.5, 0.5])

    def test_cli_writes_markdown_and_optional_json_without_touching_input(self):
        report = _report()
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            input_path = root / "input.json"
            markdown_path = root / "analysis.md"
            json_path = root / "analysis.json"
            original = json.dumps(report, ensure_ascii=False, indent=2)
            input_path.write_text(original, encoding="utf-8")
            self.assertEqual(main([str(input_path), "--output", str(markdown_path), "--json", str(json_path)]), 0)
            self.assertEqual(input_path.read_text(encoding="utf-8"), original)
            self.assertIn("Mac pilot v3", markdown_path.read_text(encoding="utf-8"))
            analysis = json.loads(json_path.read_text(encoding="utf-8"))
            self.assertIn("paired_comparisons", analysis)
            with self.assertRaises(ValueError):
                main([str(input_path), "--output", str(input_path)])


if __name__ == "__main__":
    unittest.main()
