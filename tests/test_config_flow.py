"""Config flow helper tests with stub HA objects: python tests/test_config_flow.py (needs HA installed)."""

from types import SimpleNamespace
from unittest.mock import patch

from custom_components.ukph_alerts import config_flow as cf


class NoMappingRegistry:
    """Device registry stand-in: any use of `.devices` fails the test (deprecated, breaks in 2027.9)."""

    @property
    def devices(self):
        raise AssertionError("phone_services must not use device_registry.devices")


def _device(name, by_user=None, platform="mobile_app"):
    return SimpleNamespace(name=name, name_by_user=by_user, identifiers={(platform, name)})


def test_phone_services_uses_config_entry_lookup():
    devices = {
        "e1": [_device("Darren's Phone")],
        "e2": [_device("pixel 9", by_user="Sue's Pixel"), _device("other", platform="zha")],
    }
    hass = SimpleNamespace(
        services=SimpleNamespace(async_services=lambda: {"notify": {
            "mobile_app_darren_s_phone": None, "mobile_app_sue_s_pixel": None,
            "mobile_app_old_tablet": None, "persistent_notification": None}}),
        config_entries=SimpleNamespace(async_entries=lambda domain: [
            SimpleNamespace(entry_id="e1"), SimpleNamespace(entry_id="e2")] if domain == "mobile_app" else []),
    )
    with patch.object(cf.dr, "async_get", return_value=NoMappingRegistry()), \
            patch.object(cf.dr, "async_entries_for_config_entry", side_effect=lambda reg, eid: devices[eid]):
        got = {o["value"]: o["label"] for o in cf.phone_services(hass)}
    assert got == {
        "mobile_app_darren_s_phone": "Darren's Phone",
        "mobile_app_sue_s_pixel": "Sue's Pixel",
        "mobile_app_old_tablet": "Old Tablet",  # notify service with no device: falls back to a tidied name
    }, got


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_"):
            fn()
            print("ok", name)
