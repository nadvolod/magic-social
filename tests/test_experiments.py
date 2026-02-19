"""Tests for the A/B experiment manager."""

import json
import pytest

from src.experiments import ExperimentManager, MIN_SAMPLES_PER_VARIANT
from src.models import Experiment, ExperimentStatus, ExperimentVariable


class TestExperimentManager:
    def test_starts_first_experiment(self, tmp_path):
        manager = ExperimentManager(state_path=str(tmp_path / "exp.json"))
        exp = manager.start_next_experiment()
        assert exp is not None
        assert exp.status == ExperimentStatus.RUNNING

    def test_get_active_experiment_returns_running(self, tmp_path):
        manager = ExperimentManager(state_path=str(tmp_path / "exp.json"))
        manager.start_next_experiment()
        active = manager.get_active_experiment()
        assert active is not None
        assert active.status == ExperimentStatus.RUNNING

    def test_assign_variant_round_robin(self, tmp_path):
        manager = ExperimentManager(state_path=str(tmp_path / "exp.json"))
        exp = manager.start_next_experiment()
        # Simulate round-robin: assign + record a result each time
        assigned = []
        for i in range(len(exp.variants)):
            variant = manager.assign_variant(exp)
            assigned.append(variant)
            manager.record_result(exp, f"post-{i}", variant, 50.0)
        # Each variant should be assigned exactly once across one full round
        assert set(assigned) == set(exp.variants)

    def test_record_result_stores_data(self, tmp_path):
        manager = ExperimentManager(state_path=str(tmp_path / "exp.json"))
        exp = manager.start_next_experiment()
        manager.record_result(exp, "post-001", exp.variants[0], 45.0)
        assert "post-001" in exp.results
        assert exp.results["post-001"]["engagement_score"] == 45.0

    def test_experiment_concludes_after_min_samples(self, tmp_path):
        manager = ExperimentManager(state_path=str(tmp_path / "exp.json"))
        exp = manager.start_next_experiment()
        # Add MIN_SAMPLES_PER_VARIANT results per variant
        for i, variant in enumerate(exp.variants):
            for j in range(MIN_SAMPLES_PER_VARIANT):
                score = 100.0 if i == 0 else 50.0  # First variant wins
                manager.record_result(exp, f"post-{i}-{j}", variant, score)
        assert exp.status == ExperimentStatus.CONCLUDED
        assert exp.winner == exp.variants[0]

    def test_get_best_variant_returns_winner(self, tmp_path):
        manager = ExperimentManager(state_path=str(tmp_path / "exp.json"))
        exp = manager.start_next_experiment()
        for i, variant in enumerate(exp.variants):
            for j in range(MIN_SAMPLES_PER_VARIANT):
                score = 100.0 if variant == "result" else 30.0
                manager.record_result(exp, f"post-{i}-{j}", variant, score)
        variable = ExperimentVariable(exp.variable) if isinstance(exp.variable, str) else exp.variable
        winner = manager.get_best_variant(variable)
        assert winner == "result"

    def test_returns_none_for_inconclusive_experiment(self, tmp_path):
        manager = ExperimentManager(state_path=str(tmp_path / "exp.json"))
        manager.start_next_experiment()
        winner = manager.get_best_variant(ExperimentVariable.HOOK_STYLE)
        assert winner is None

    def test_state_persists_across_instances(self, tmp_path):
        path = str(tmp_path / "exp.json")
        manager1 = ExperimentManager(state_path=path)
        exp = manager1.start_next_experiment()
        exp_id = exp.id

        manager2 = ExperimentManager(state_path=path)
        assert len(manager2.experiments) == 1
        assert manager2.experiments[0].id == exp_id

    def test_summary_shows_all_experiments(self, tmp_path):
        manager = ExperimentManager(state_path=str(tmp_path / "exp.json"))
        manager.start_next_experiment()
        summary = manager.summary()
        assert "hook_style" in summary.lower() or "Hook" in summary

    def test_summary_empty_when_no_experiments(self, tmp_path):
        manager = ExperimentManager(state_path=str(tmp_path / "exp.json"))
        assert "No experiments" in manager.summary()
