"""v3.1 P1 - deterministic VS Code file-URI encoding (cross-platform, Windows-safe)."""
from __future__ import annotations

from core.scout.dashboard import _vscode_file_uri


def test_windows_path_with_spaces_is_encoded():
    uri = _vscode_file_uri(r"D:\1QA AI\ai-qa-factory\outputs\p\40_ark_work")
    assert uri == "vscode://file/D:/1QA%20AI/ai-qa-factory/outputs/p/40_ark_work"
    assert "\\" not in uri and " " not in uri


def test_posix_absolute_path():
    assert _vscode_file_uri("/home/u/proj/40_ark_work") == "vscode://file/home/u/proj/40_ark_work"


def test_relative_path_gets_leading_slash():
    assert _vscode_file_uri("outputs/p").startswith("vscode://file/outputs/p")


def test_drive_letter_colon_preserved_spaces_encoded():
    uri = _vscode_file_uri(r"C:\Users\Q A\proj")
    assert uri == "vscode://file/C:/Users/Q%20A/proj"
