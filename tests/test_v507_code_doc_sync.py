from pathlib import Path


def test_v508_docs_exist_legacy_sync():
    assert Path("docs/OPPORTUNITY_PRESCREENING_APPROVAL_FLOW.md").exists()
    assert Path("docs/REAL_TESTING_PREPARATION.md").exists()
    assert Path("docs/V508_MODEL_ROUTING_NOTES.md").exists()


def test_readme_mentions_v508_sync():
    text = Path("README.md").read_text(encoding="utf-8")
    assert "v5.0.8 model routing profiles" in text.lower()
    assert "pre-screen first" in text.lower()


def test_main_version_label_v508_legacy_sync():
    text = Path("main.py").read_text(encoding="utf-8")
    assert "v5.0.8" in text


def test_real_testing_doc_records_current_limitations():
    text = Path("docs/REAL_TESTING_PREPARATION.md").read_text(encoding="utf-8")
    assert "URL-only autonomous inspection" in text
    assert "screenshot-only visual analysis" in text
    assert "Future adapters" in text
