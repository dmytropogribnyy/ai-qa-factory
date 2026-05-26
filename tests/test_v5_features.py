from __future__ import annotations

from core.config import get_settings
from core.orchestrator import QAFactoryOrchestrator
from tools.file_manager import FileManager
import pytest


def test_upwork_mode_generates_pricing_and_quality_gate(tmp_path, monkeypatch):
    monkeypatch.setenv('OUTPUT_DIR', str(tmp_path / 'outputs'))
    settings = get_settings()
    state = QAFactoryOrchestrator(settings).run('upwork', 'Need Playwright TypeScript flaky CI audit for SaaS app.')
    assert 'pricing_and_milestone.md' in state.generated_outputs
    assert 'proposal.md' in state.generated_outputs
    assert 'QUALITY_GATE_REPORT.md' in state.generated_outputs
    assert state.suggested_price
    assert (tmp_path / 'outputs' / state.project_id / 'pricing_and_milestone.md').exists()


def test_dynamic_specialist_suggestions(tmp_path, monkeypatch):
    monkeypatch.setenv('OUTPUT_DIR', str(tmp_path / 'outputs'))
    settings = get_settings()
    state = QAFactoryOrchestrator(settings).run('full', 'Need QA for Stripe checkout, mobile web and performance smoke.')
    assert 'suggested_specialists.md' in state.generated_outputs
    assert any('Payment' in s for s in state.suggested_specialists)
    assert any('Performance' in s for s in state.suggested_specialists)


def test_file_manager_blocks_path_traversal(tmp_path):
    fm = FileManager(tmp_path / 'outputs')
    with pytest.raises(ValueError):
        fm.write_many('project', {'../evil.txt': 'bad'})
