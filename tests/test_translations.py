"""Tests for the translation files of the Kathrein Wallbox integration."""

import json
import re
from pathlib import Path

import pytest

INTEGRATION_DIR = Path(__file__).parents[1] / "custom_components" / "kathrein_wallbox"
STRINGS = json.loads((INTEGRATION_DIR / "strings.json").read_text(encoding="utf-8"))
TRANSLATION_FILES = sorted((INTEGRATION_DIR / "translations").glob("*.json"))
PLACEHOLDER = re.compile(r"\{[a-z_]+\}")


def _flatten(node: dict, prefix: str = "") -> dict[str, str]:
    """Flatten nested translation data into dotted paths."""
    flat: dict[str, str] = {}
    for key, value in node.items():
        path = f"{prefix}.{key}" if prefix else key
        if isinstance(value, dict):
            flat.update(_flatten(value, path))
        else:
            flat[path] = value
    return flat


def _load(path: Path) -> dict[str, str]:
    return _flatten(json.loads(path.read_text(encoding="utf-8")))


def test_all_supported_languages_are_present() -> None:
    """Provide every language required by the project."""
    assert [path.stem for path in TRANSLATION_FILES] == [
        "cs",
        "da",
        "de",
        "en",
        "es",
        "fr",
        "it",
        "nb",
        "nl",
        "pl",
        "pt",
        "sv",
    ]


def test_english_translation_matches_strings() -> None:
    """Keep strings.json and en.json identical."""
    assert _load(INTEGRATION_DIR / "translations" / "en.json") == _flatten(STRINGS)


@pytest.mark.parametrize("path", TRANSLATION_FILES, ids=lambda path: path.stem)
def test_translation_has_same_keys_and_placeholders_as_strings(path: Path) -> None:
    """Mirror every key and placeholder of strings.json in each language."""
    reference = _flatten(STRINGS)
    translation = _load(path)

    assert translation.keys() == reference.keys()
    for key, text in translation.items():
        assert sorted(PLACEHOLDER.findall(text)) == sorted(
            PLACEHOLDER.findall(reference[key])
        ), key


@pytest.mark.parametrize("step", ["user", "reconfigure"])
def test_config_flow_fields_have_descriptions(step: str) -> None:
    """Explain every connection field shown in the config flow."""
    form = STRINGS["config"]["step"][step]

    for field in ("host", "port", "unit_id"):
        assert field in form["data"]
        assert form["data_description"][field]


@pytest.mark.parametrize(("section", "step"), [("config", "user"), ("options", "init")])
def test_polling_interval_has_description(section: str, step: str) -> None:
    """Explain the polling interval in the setup and options forms."""
    form = STRINGS[section]["step"][step]

    assert "scan_interval" in form["data"]
    assert form["data_description"]["scan_interval"]


@pytest.mark.parametrize(
    "path",
    [INTEGRATION_DIR / "strings.json", *TRANSLATION_FILES],
    ids=lambda path: path.name,
)
def test_translation_file_uses_canonical_layout(path: Path) -> None:
    """Format every language file like Home Assistant Core does."""
    text = path.read_text(encoding="utf-8")

    assert text == json.dumps(json.loads(text), indent=2, ensure_ascii=False) + "\n"
