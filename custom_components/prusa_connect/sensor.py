"""Sensors of Prusa Connect printers and their tools."""

from __future__ import annotations

from collections.abc import Callable, Iterator
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorEntityDescription,
    SensorStateClass,
)
from homeassistant.const import (
    PERCENTAGE,
    REVOLUTIONS_PER_MINUTE,
    EntityCategory,
    UnitOfLength,
    UnitOfTemperature,
    UnitOfTime,
)
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity import Entity
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.util import dt as dt_util

from .const import PRUSA_STATES
from .coordinator import PrusaConnectConfigEntry, PrusaConnectCoordinator
from .entity import (
    PrusaConnectEntity,
    PrusaConnectToolEntity,
    async_add_entities_as_found,
    enabled_heads,
    enabled_slots,
)
from .library import Device, Tool

PARALLEL_UPDATES = 0


def _job_value[T](getter: Callable[[Device], T | None]) -> Callable[[Device], T | None]:
    """A job reading, or nothing while the printer carries no print."""
    return lambda device: getter(device) if device.has_job else None


def _finish_time(device: Device) -> datetime | None:
    remaining = device.job_time_remaining
    if not device.has_job or remaining is None:
        return None
    # Rounded to the minute, so the estimate does not move every second.
    finish = dt_util.utcnow() + timedelta(seconds=remaining)
    return finish.replace(second=0, microsecond=0)


def _chamber_fan_rpm(fan: int) -> Callable[[Device], float | None]:
    return lambda d: d.chamber_fan_rpm(fan)


def _has_chamber_fan(fan: int) -> Callable[[Device], bool]:
    return lambda d: d.chamber_fan_rpm(fan) is not None


@dataclass(frozen=True, kw_only=True)
class PrinterSensorDescription(SensorEntityDescription):
    value_fn: Callable[[Device], Any]
    exists_fn: Callable[[Device], bool] = lambda _: True


@dataclass(frozen=True, kw_only=True)
class ToolSensorDescription(SensorEntityDescription):
    value_fn: Callable[[Tool], Any]
    exists_fn: Callable[[Device, Tool], bool] = lambda _d, _t: True


PRINTER_SENSORS: tuple[PrinterSensorDescription, ...] = (
    PrinterSensorDescription(
        key="progress",
        translation_key="progress",
        native_unit_of_measurement=PERCENTAGE,
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=0,
        value_fn=_job_value(lambda d: d.job_progress),
    ),
    PrinterSensorDescription(
        key="time_remaining",
        translation_key="time_remaining",
        device_class=SensorDeviceClass.DURATION,
        native_unit_of_measurement=UnitOfTime.SECONDS,
        suggested_unit_of_measurement=UnitOfTime.MINUTES,
        suggested_display_precision=0,
        value_fn=_job_value(lambda d: d.job_time_remaining),
    ),
    PrinterSensorDescription(
        key="time_printing",
        translation_key="time_printing",
        device_class=SensorDeviceClass.DURATION,
        native_unit_of_measurement=UnitOfTime.SECONDS,
        suggested_unit_of_measurement=UnitOfTime.MINUTES,
        suggested_display_precision=0,
        entity_registry_enabled_default=False,
        value_fn=_job_value(lambda d: d.job_time_printing),
    ),
    PrinterSensorDescription(
        key="finish_time",
        translation_key="finish_time",
        device_class=SensorDeviceClass.TIMESTAMP,
        value_fn=_finish_time,
    ),
    PrinterSensorDescription(
        key="job_name",
        translation_key="job_name",
        value_fn=_job_value(lambda d: d.job_name),
    ),
    PrinterSensorDescription(
        key="bed_temperature",
        translation_key="bed_temperature",
        device_class=SensorDeviceClass.TEMPERATURE,
        native_unit_of_measurement=UnitOfTemperature.CELSIUS,
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=1,
        value_fn=lambda d: d.bed_temp,
        exists_fn=lambda d: d.bed_temp is not None,
    ),
    PrinterSensorDescription(
        key="chamber_temperature",
        translation_key="chamber_temperature",
        device_class=SensorDeviceClass.TEMPERATURE,
        native_unit_of_measurement=UnitOfTemperature.CELSIUS,
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=1,
        value_fn=lambda d: d.chamber_temp,
        exists_fn=lambda d: d.chamber_temp is not None,
    ),
    *(
        PrinterSensorDescription(
            key=f"chamber_fan_{fan}_speed",
            translation_key=f"chamber_fan_{fan}_speed",
            native_unit_of_measurement=REVOLUTIONS_PER_MINUTE,
            state_class=SensorStateClass.MEASUREMENT,
            entity_category=EntityCategory.DIAGNOSTIC,
            value_fn=_chamber_fan_rpm(fan),
            exists_fn=_has_chamber_fan(fan),
        )
        for fan in (1, 2)
    ),
    *(
        PrinterSensorDescription(
            key=f"axis_{axis}",
            translation_key=f"axis_{axis}",
            device_class=SensorDeviceClass.DISTANCE,
            native_unit_of_measurement=UnitOfLength.MILLIMETERS,
            state_class=SensorStateClass.MEASUREMENT,
            suggested_display_precision=1,
            entity_category=EntityCategory.DIAGNOSTIC,
            entity_registry_enabled_default=False,
            value_fn=lambda d, axis=axis: d.axis(axis),  # type: ignore[misc]
            exists_fn=lambda d, axis=axis: d.axis(axis) is not None,  # type: ignore[misc]
        )
        for axis in ("x", "y", "z")
    ),
)


def _material(tool: Tool) -> str | None:
    # An empty abbreviation is a tool with nothing loaded.
    return tool.material or None


HEAD_SENSORS: tuple[ToolSensorDescription, ...] = (
    ToolSensorDescription(
        key="nozzle_temperature",
        translation_key="nozzle_temperature",
        device_class=SensorDeviceClass.TEMPERATURE,
        native_unit_of_measurement=UnitOfTemperature.CELSIUS,
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=1,
        value_fn=lambda t: t.nozzle_temp,
    ),
    ToolSensorDescription(
        key="material",
        translation_key="material",
        value_fn=_material,
        # A head with a feeder prints the material of the loaded slot, which
        # the slot's own sensor reports.
        exists_fn=lambda _d, t: t.feeder is None and t.material is not None,
    ),
    ToolSensorDescription(
        key="nozzle_diameter",
        translation_key="nozzle_diameter",
        device_class=SensorDeviceClass.DISTANCE,
        native_unit_of_measurement=UnitOfLength.MILLIMETERS,
        suggested_display_precision=2,
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda t: t.nozzle_diameter,
        exists_fn=lambda _d, t: t.nozzle_diameter is not None,
    ),
    ToolSensorDescription(
        key="print_fan_speed",
        translation_key="print_fan_speed",
        native_unit_of_measurement=REVOLUTIONS_PER_MINUTE,
        state_class=SensorStateClass.MEASUREMENT,
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda t: t.print_fan_rpm,
        exists_fn=lambda _d, t: t.print_fan_rpm is not None,
    ),
    ToolSensorDescription(
        key="heatbreak_fan_speed",
        translation_key="heatbreak_fan_speed",
        native_unit_of_measurement=REVOLUTIONS_PER_MINUTE,
        state_class=SensorStateClass.MEASUREMENT,
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda t: t.heatbreak_fan_rpm,
        exists_fn=lambda _d, t: t.heatbreak_fan_rpm is not None,
    ),
    ToolSensorDescription(
        key="feeder_progress",
        translation_key="feeder_progress",
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda t: t.feeder.mmu_progress_code if t.feeder else None,
        exists_fn=lambda _d, t: t.feeder is not None,
    ),
    ToolSensorDescription(
        key="feeder_command",
        translation_key="feeder_command",
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda t: t.feeder.mmu_command_in_progress if t.feeder else None,
        exists_fn=lambda _d, t: t.feeder is not None,
    ),
)

SLOT_SENSORS: tuple[ToolSensorDescription, ...] = (
    ToolSensorDescription(
        key="material",
        translation_key="slot_material",
        value_fn=_material,
    ),
)


def _entities(coordinator: PrusaConnectCoordinator, device: Device) -> Iterator[Entity]:
    yield PrinterStateSensor(coordinator, device)
    for description in PRINTER_SENSORS:
        if description.exists_fn(device):
            yield PrinterSensor(coordinator, device, description)
    for head in enabled_heads(device):
        for tool_description in HEAD_SENSORS:
            if tool_description.exists_fn(device, head):
                yield ToolSensor(coordinator, device, head, tool_description)
        for slot in enabled_slots(device, head):
            for tool_description in SLOT_SENSORS:
                if tool_description.exists_fn(device, slot):
                    yield ToolSensor(coordinator, device, slot, tool_description)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: PrusaConnectConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up the sensors."""
    async_add_entities_as_found(entry, async_add_entities, _entities)


class PrinterSensor(PrusaConnectEntity, SensorEntity):
    entity_description: PrinterSensorDescription

    def __init__(
        self,
        coordinator: PrusaConnectCoordinator,
        device: Device,
        description: PrinterSensorDescription,
    ) -> None:
        super().__init__(coordinator, device, description.key)
        self.entity_description = description

    @property
    def native_value(self) -> Any:
        device = self.device
        return self.entity_description.value_fn(device) if device else None


class ToolSensor(PrusaConnectToolEntity, SensorEntity):
    entity_description: ToolSensorDescription

    def __init__(
        self,
        coordinator: PrusaConnectCoordinator,
        device: Device,
        tool: Tool,
        description: ToolSensorDescription,
    ) -> None:
        super().__init__(coordinator, device, tool, description.key)
        self.entity_description = description

    @property
    def native_value(self) -> Any:
        tool = self.tool
        return self.entity_description.value_fn(tool) if tool else None


class PrinterStateSensor(PrusaConnectEntity, SensorEntity):
    """The machine state, translated for the states Prusa printers report.

    Another vendor's driver may report states outside that set. They are kept
    as the machine spells them, lower-cased, rather than dropped.
    """

    _attr_device_class = SensorDeviceClass.ENUM
    _attr_translation_key = "state"

    def __init__(self, coordinator: PrusaConnectCoordinator, device: Device) -> None:
        super().__init__(coordinator, device, "state")

    @property
    def native_value(self) -> str | None:
        device = self.device
        state = device.printer_state if device else None
        return state.lower() if state else None

    @property
    def options(self) -> list[str]:
        options = set(PRUSA_STATES)
        options.update(s.lower() for s in self.coordinator.vocabulary.states)
        if (current := self.native_value) is not None:
            options.add(current)
        return sorted(options)

    @property
    def extra_state_attributes(self) -> dict[str, Any] | None:
        device = self.device
        volume = device.build_volume if device else None
        if volume is None:
            return None
        return {
            "build_volume_x": volume.x_mm,
            "build_volume_y": volume.y_mm,
            "build_volume_z": volume.z_mm,
        }
