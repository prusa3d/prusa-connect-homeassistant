"""The chamber light of an enclosed printer."""

from __future__ import annotations

from collections.abc import Iterator
from typing import Any

from homeassistant.components.light import ATTR_BRIGHTNESS, LightEntity
from homeassistant.components.light.const import ColorMode
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity import Entity
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .coordinator import PrusaConnectConfigEntry, PrusaConnectCoordinator
from .entity import PrusaConnectEntity, async_add_entities_as_found
from .helpers import command
from .library import VERB_SET_CHAMBER_LIGHT, Device

PARALLEL_UPDATES = 1

_FULL = 100
_BRIGHTNESS_TOP = 255


def _entities(coordinator: PrusaConnectCoordinator, device: Device) -> Iterator[Entity]:
    if device.may("operate") and device.supports(VERB_SET_CHAMBER_LIGHT):
        yield ChamberLight(coordinator, device)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: PrusaConnectConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up the chamber lights."""
    async_add_entities_as_found(entry, async_add_entities, _entities)


class ChamberLight(PrusaConnectEntity, LightEntity):
    """The chamber light, set in percent.

    A CORE One reports it. An XL takes it and reports nothing, so its state is
    unknown until it is set from here.
    """

    _attr_translation_key = "chamber_light"
    _attr_color_mode = ColorMode.BRIGHTNESS

    def __init__(self, coordinator: PrusaConnectCoordinator, device: Device) -> None:
        super().__init__(coordinator, device, "chamber_light")
        self._attr_supported_color_modes = {ColorMode.BRIGHTNESS}

    @property
    def _percent(self) -> int | None:
        device = self.device
        return device.chamber_light if device else None

    @property
    def is_on(self) -> bool | None:
        percent = self._percent
        return None if percent is None else percent > 0

    @property
    def brightness(self) -> int | None:
        percent = self._percent
        return None if percent is None else round(percent * _BRIGHTNESS_TOP / _FULL)

    @command
    async def _set(self, percent: float) -> None:
        device = self.device
        if device is not None:
            await self.coordinator.client.set_chamber_light(device, percent)

    async def async_turn_on(self, **kwargs: Any) -> None:
        brightness = kwargs.get(ATTR_BRIGHTNESS)
        await self._set(_FULL if brightness is None else max(1, round(brightness * _FULL / _BRIGHTNESS_TOP)))

    async def async_turn_off(self, **kwargs: Any) -> None:
        await self._set(0)
