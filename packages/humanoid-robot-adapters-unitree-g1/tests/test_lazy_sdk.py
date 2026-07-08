"""SDK gating tests — importable everywhere, uses SDK only on `.start()`."""

from __future__ import annotations

import pytest

from humanoid_robot.adapters.unitree_g1 import (
    UnitreeG1Adapter,
    UnitreeG1Settings,
    UnitreeSdkNotAvailableError,
)


class TestLazySdk:
    def test_importable_without_sdk(self) -> None:
        # If we got here, importing the package did not trigger a
        # `unitree_sdk2py` import (there is no such module in this env).
        adapter = UnitreeG1Adapter(network_interface="eth10")
        assert adapter.settings.network_interface == "eth10"

    def test_manifest_available_without_sdk(self) -> None:
        adapter = UnitreeG1Adapter(network_interface="eth10")
        # Reading capabilities/manifest must not touch the SDK.
        assert adapter.capabilities.locomotion is not None
        assert adapter.manifest.network_interface == "eth10"

    async def test_start_raises_helpful_error_without_sdk(self) -> None:
        adapter = UnitreeG1Adapter(network_interface="eth10")
        with pytest.raises(UnitreeSdkNotAvailableError, match="unitree_sdk2py"):
            await adapter.start()

    def test_settings_reject_bad_mic_source(self) -> None:
        with pytest.raises(ValueError, match="mic_source"):
            UnitreeG1Settings(mic_source="bogus")

    def test_from_settings_constructor(self) -> None:
        settings = UnitreeG1Settings(network_interface="eth10", speaker_volume=80)
        adapter = UnitreeG1Adapter.from_settings(settings)
        assert adapter.settings.speaker_volume == 80
