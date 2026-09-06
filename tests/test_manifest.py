import json
from pathlib import Path

import pytest

MANIFEST_PATH = Path(__file__).resolve().parent.parent / "_manifest.json"


@pytest.fixture(scope="module")
def manifest() -> dict[str, object]:
    return json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))


def test_manifest_keeps_stable_plugin_id(manifest) -> None:
    assert manifest["id"] == "zjcs.guild-notifier"


def test_manifest_uses_chinese_display_name(manifest) -> None:
    assert manifest["name"] == "杖剑助手"


def test_manifest_declares_project_author(manifest) -> None:
    assert manifest["author"] == {
        "name": "野生的金属乌帕",
        "url": "https://github.com/ShiinaWhite/maibot_plugin_zjcs",
    }


def test_manifest_version_is_bumped_for_v1_2_config(manifest) -> None:
    assert manifest["version"] == "0.1.2"
