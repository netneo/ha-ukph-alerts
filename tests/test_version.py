import json
from pathlib import Path

from custom_components.ukph_alerts.const import VERSION


def test_const_version_matches_manifest():
    """VERSION drives the panel cache-busting URL and user agent; it must track the manifest."""
    manifest = json.loads(
        (Path(__file__).parents[1] / "custom_components/ukph_alerts/manifest.json").read_text()
    )
    assert VERSION == manifest["version"]
