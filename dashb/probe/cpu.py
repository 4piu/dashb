import os
import platform
import time
from typing import Any

import psutil

from dashb.probe import lhm
from dashb.probe.types import MetricMap

WINDOWS = os.name == "nt"
PERCPU_PLATFORMS = {"Linux", "FreeBSD"}

METRICS = {
    "cpu.utilization": {"unit": "%", "kind": "gauge", "subscribable": True},
    "cpu.utilization_percore": {
        "unit": "%",
        "kind": "gauge",
        "subscribable": True,
    },
    "cpu.logical_cores": {
        "unit": "count",
        "kind": "gauge",
        "subscribable": False,
    },
    "cpu.physical_cores": {
        "unit": "count",
        "kind": "gauge",
        "subscribable": False,
    },
    "cpu.temperature_package": {
        "unit": "C",
        "kind": "gauge",
        "subscribable": True,
    },
    "cpu.voltage_average": {
        "unit": "V",
        "kind": "gauge",
        "subscribable": True,
    },
    "cpu.voltage_percore": {
        "unit": "V",
        "kind": "gauge",
        "subscribable": True,
    },
    "cpu.power_package": {"unit": "W", "kind": "gauge", "subscribable": True},
    "cpu.power_percore": {"unit": "W", "kind": "gauge", "subscribable": True},
    "cpu.clock_average": {"unit": "MHz", "kind": "gauge", "subscribable": True},
    "cpu.clock_percore": {"unit": "MHz", "kind": "gauge", "subscribable": True},
    "cpu.clock_effective_average": {
        "unit": "MHz",
        "kind": "gauge",
        "subscribable": True,
    },
    "cpu.clock_effective_percore": {
        "unit": "MHz",
        "kind": "gauge",
        "subscribable": True,
    },
}

_lhm_cpu_sensor_ids: dict[str, str | list[str]] | None = None
_supported_metrics: MetricMap | None = None
INVALID_ZERO_LHM_SENSOR_TYPES = {"Temperature", "Power", "Clock"}
MAX_REASONABLE_CPU_VID_V = 1.45
LHM_WARMUP_ATTEMPTS = 4
LHM_WARMUP_DELAY_S = 0.3


def get_supported_metrics() -> MetricMap:
    global _supported_metrics

    if _supported_metrics is not None:
        return dict(_supported_metrics)

    metrics: MetricMap = {}
    for metric, meta in METRICS.items():
        if _metric_supported(metric):
            metrics[metric] = meta

    _supported_metrics = metrics
    return dict(metrics)


def supports_metric(metric: str) -> bool:
    return metric in get_supported_metrics()


def collect_metric(metric: str) -> Any:
    if metric == "cpu.utilization":
        return psutil.cpu_percent(percpu=False)
    if metric == "cpu.utilization_percore":
        if not _supports_per_core_utilization():
            raise KeyError(metric)
        return psutil.cpu_percent(percpu=True)
    if metric == "cpu.logical_cores":
        return psutil.cpu_count(logical=True) or 0
    if metric == "cpu.physical_cores":
        return psutil.cpu_count(logical=False) or 0
    if metric == "cpu.temperature_package":
        return _read_lhm_value(metric)
    if metric == "cpu.voltage_average":
        return _average(_read_lhm_array("cpu.voltage_percore"))
    if metric == "cpu.voltage_percore":
        return _read_lhm_array(metric)
    if metric == "cpu.power_package":
        return _read_lhm_value(metric)
    if metric == "cpu.power_percore":
        return _read_lhm_array(metric)
    if metric == "cpu.clock_average":
        return _collect_clock_average()
    if metric == "cpu.clock_percore":
        return _collect_clock_percore()
    if metric == "cpu.clock_effective_average":
        return _collect_clock_effective_average()
    if metric == "cpu.clock_effective_percore":
        return _collect_clock_effective_percore()
    raise KeyError(metric)


def _supports_per_core_utilization() -> bool:
    return platform.system() in PERCPU_PLATFORMS


def _supports_lhm_metric(metric: str) -> bool:
    if not WINDOWS:
        return False
    return _get_lhm_cpu_sensor_ids().get(metric) is not None


def _clock_supported_non_windows() -> bool:
    if psutil.cpu_freq(percpu=False) is not None:
        return True
    if _supports_per_core_utilization():
        freqs = psutil.cpu_freq(percpu=True)
        return bool(freqs and any(freq is not None for freq in freqs))
    return False


def _metric_supported(metric: str) -> bool:
    if metric in {"cpu.utilization", "cpu.logical_cores", "cpu.physical_cores"}:
        return True
    if metric == "cpu.utilization_percore":
        return _supports_per_core_utilization()
    if metric in {
        "cpu.temperature_package",
        "cpu.voltage_average",
        "cpu.voltage_percore",
        "cpu.power_package",
        "cpu.power_percore",
    }:
        return WINDOWS and _supports_lhm_metric(metric)
    if metric == "cpu.clock_average":
        return (WINDOWS and _supports_lhm_metric("cpu.clock_average")) or (
            not WINDOWS and _clock_supported_non_windows()
        )
    if metric == "cpu.clock_percore":
        return (WINDOWS and _supports_lhm_metric("cpu.clock_percore")) or (
            not WINDOWS
            and _supports_per_core_utilization()
            and _clock_supported_non_windows()
        )
    if metric == "cpu.clock_effective_average":
        return (WINDOWS and _supports_lhm_metric("cpu.clock_effective_average")) or (
            not WINDOWS and _clock_supported_non_windows()
        )
    if metric == "cpu.clock_effective_percore":
        return (WINDOWS and _supports_lhm_metric("cpu.clock_effective_percore")) or (
            not WINDOWS
            and _supports_per_core_utilization()
            and _clock_supported_non_windows()
        )
    return False


def _collect_clock_average() -> float | None:
    if WINDOWS:
        return _read_lhm_value("cpu.clock_average")

    freq = psutil.cpu_freq(percpu=False)
    return freq.current if freq else None


def _collect_clock_percore() -> list[float | None]:
    if WINDOWS:
        return _read_lhm_array("cpu.clock_percore")
    if not _supports_per_core_utilization():
        raise KeyError("cpu.clock_percore")
    freqs = psutil.cpu_freq(percpu=True)
    return [freq.current if freq else None for freq in freqs] if freqs else []


def _collect_clock_effective_average() -> float | None:
    if WINDOWS:
        return _read_lhm_value("cpu.clock_effective_average")
    return _collect_clock_average()


def _collect_clock_effective_percore() -> list[float | None]:
    if WINDOWS:
        return _read_lhm_array("cpu.clock_effective_percore")
    return _collect_clock_percore()


def _get_lhm_cpu_sensor_ids() -> dict[str, str | list[str]]:
    global _lhm_cpu_sensor_ids

    if _lhm_cpu_sensor_ids is not None:
        return _lhm_cpu_sensor_ids

    if not WINDOWS:
        _lhm_cpu_sensor_ids = {}
        return _lhm_cpu_sensor_ids

    # LHM sensors can briefly report a stale/zero value right after the helper
    # starts (e.g. AMD SMU-derived power/clock sensors need a settled update
    # cycle), which would make _has_usable_lhm_value reject a metric that is
    # actually available. Retry a few times so a cold first read doesn't
    # permanently mark a metric unsupported for the process lifetime.
    sensor_ids: dict[str, str | list[str]] = {}
    for attempt in range(LHM_WARMUP_ATTEMPTS):
        sensors = [
            sensor
            for sensor in lhm.list_sensors(force_refresh=attempt > 0)
            if sensor.hardware_type.lower() == "cpu"
        ]
        if not sensors:
            break

        merged = {**sensor_ids, **_match_cpu_sensor_ids(sensors)}
        stable = merged == sensor_ids
        sensor_ids = merged
        if stable or attempt + 1 == LHM_WARMUP_ATTEMPTS:
            break
        time.sleep(LHM_WARMUP_DELAY_S)

    _lhm_cpu_sensor_ids = sensor_ids
    return sensor_ids


def _match_cpu_sensor_ids(sensors: list[lhm.Sensor]) -> dict[str, str | list[str]]:
    sensor_ids: dict[str, str | list[str]] = {}

    package_temperature = _first_sensor(
        sensors,
        sensor_type="Temperature",
        name_contains=("package", "tdie", "tctl"),
    )
    if package_temperature and _has_usable_lhm_value(package_temperature):
        sensor_ids["cpu.temperature_package"] = package_temperature.id

    per_core_voltage = _matching_sensors(
        sensors,
        sensor_type="Voltage",
        name_contains=("vid",),
        name_starts_with=("core #",),
    )
    per_core_voltage = [
        sensor
        for sensor in per_core_voltage
        if _has_usable_lhm_value(sensor) and _is_reasonable_cpu_vid(sensor.value)
    ]
    if per_core_voltage:
        sensor_ids["cpu.voltage_percore"] = [sensor.id for sensor in per_core_voltage]
        sensor_ids["cpu.voltage_average"] = [sensor.id for sensor in per_core_voltage]

    package_power = _first_sensor(
        sensors,
        sensor_type="Power",
        name_contains=("package",),
    )
    if package_power and _has_usable_lhm_value(package_power):
        sensor_ids["cpu.power_package"] = package_power.id

    per_core_power = _matching_sensors(
        sensors,
        sensor_type="Power",
        name_contains=("core",),
        name_starts_with=("core #",),
    )
    per_core_power = [
        sensor for sensor in per_core_power if _has_usable_lhm_value(sensor)
    ]
    if per_core_power:
        sensor_ids["cpu.power_percore"] = [sensor.id for sensor in per_core_power]

    package_clock = _first_sensor(
        sensors,
        sensor_type="Clock",
        name_contains=("package", "average"),
    )
    if package_clock and _has_usable_lhm_value(package_clock):
        sensor_ids["cpu.clock_average"] = package_clock.id
    else:
        per_core_clocks = _matching_sensors(
            sensors,
            sensor_type="Clock",
            name_contains=(),
            name_starts_with=("core #",),
        )
        per_core_clocks = [
            sensor
            for sensor in per_core_clocks
            if _has_usable_lhm_value(sensor) and "effective" not in sensor.name.lower()
        ]
        if per_core_clocks:
            sensor_ids["cpu.clock_percore"] = [sensor.id for sensor in per_core_clocks]

    effective_average = _first_sensor(
        sensors,
        sensor_type="Clock",
        name_contains=("effective",),
    )
    if effective_average and _has_usable_lhm_value(effective_average):
        sensor_ids["cpu.clock_effective_average"] = effective_average.id

    effective_per_core = _matching_sensors(
        sensors,
        sensor_type="Clock",
        name_contains=("effective",),
        name_starts_with=("core #",),
    )
    effective_per_core = [
        sensor for sensor in effective_per_core if _has_usable_lhm_value(sensor)
    ]
    if effective_per_core:
        sensor_ids["cpu.clock_effective_percore"] = [
            sensor.id for sensor in effective_per_core
        ]

    return sensor_ids


def debug_lhm_cpu_sensor_matches() -> dict[str, list[dict[str, Any]]]:
    """Return raw LHM CPU sensor candidates grouped by Dashb CPU metric."""
    sensors = [
        sensor for sensor in lhm.list_sensors() if sensor.hardware_type.lower() == "cpu"
    ]
    return {
        "cpu.temperature_package": _sensor_debug_rows(
            [
                sensor
                for sensor in sensors
                if sensor.type == "Temperature"
                and _name_contains_any(sensor, ("package", "tdie", "tctl"))
            ]
        ),
        "cpu.voltage_percore": _sensor_debug_rows(
            _matching_sensors(
                sensors,
                sensor_type="Voltage",
                name_contains=("vid",),
                name_starts_with=("core #",),
            )
        ),
        "cpu.power_package": _sensor_debug_rows(
            [
                sensor
                for sensor in sensors
                if sensor.type == "Power" and _name_contains_any(sensor, ("package",))
            ]
        ),
        "cpu.power_percore": _sensor_debug_rows(
            _matching_sensors(
                sensors,
                sensor_type="Power",
                name_contains=("core",),
                name_starts_with=("core #",),
            )
        ),
        "cpu.clock_average": _sensor_debug_rows(
            [
                sensor
                for sensor in sensors
                if sensor.type == "Clock"
                and _name_contains_any(sensor, ("package", "average"))
                and "effective" not in sensor.name.lower()
            ]
        ),
        "cpu.clock_percore": _sensor_debug_rows(
            [
                sensor
                for sensor in _matching_sensors(
                    sensors,
                    sensor_type="Clock",
                    name_contains=(),
                    name_starts_with=("core #",),
                )
                if "effective" not in sensor.name.lower()
            ]
        ),
        "cpu.clock_effective_average": _sensor_debug_rows(
            [
                sensor
                for sensor in sensors
                if sensor.type == "Clock"
                and _name_contains_any(sensor, ("effective",))
                and "average" in sensor.name.lower()
            ]
        ),
        "cpu.clock_effective_percore": _sensor_debug_rows(
            _matching_sensors(
                sensors,
                sensor_type="Clock",
                name_contains=("effective",),
                name_starts_with=("core #",),
            )
        ),
    }


def _read_lhm_value(metric: str) -> float | None:
    sensor_ids = _get_lhm_cpu_sensor_ids().get(metric)
    if isinstance(sensor_ids, str):
        return lhm.read_sensor(sensor_ids)
    if isinstance(sensor_ids, list):
        return _average(_read_lhm_array(metric))
    return None


def _read_lhm_array(metric: str) -> list[float | None]:
    sensor_ids = _get_lhm_cpu_sensor_ids().get(metric)
    if not isinstance(sensor_ids, list):
        return []
    values = lhm.read_sensors(sensor_ids)
    return [values.get(sensor_id) for sensor_id in sensor_ids]


def _average(values: list[float | None]) -> float | None:
    valid_values = [value for value in values if value is not None]
    if not valid_values:
        return None
    return sum(valid_values) / len(valid_values)


def _has_usable_lhm_value(sensor: lhm.Sensor) -> bool:
    if sensor.value is None:
        return False
    if sensor.type in INVALID_ZERO_LHM_SENSOR_TYPES and sensor.value == 0:
        return False
    return True


def _is_reasonable_cpu_vid(value: float | None) -> bool:
    return value is not None and 0 < value <= MAX_REASONABLE_CPU_VID_V


def _name_contains_any(sensor: lhm.Sensor, parts: tuple[str, ...]) -> bool:
    name = sensor.name.lower()
    return any(part in name for part in parts)


def _sensor_debug_rows(sensors: list[lhm.Sensor]) -> list[dict[str, Any]]:
    return [
        {
            "id": sensor.id,
            "name": sensor.name,
            "type": sensor.type,
            "value": sensor.value,
            "hardware_name": sensor.hardware_name,
            "usable": _has_usable_lhm_value(sensor),
        }
        for sensor in sensors
    ]


def _first_sensor(
    sensors: list[lhm.Sensor],
    *,
    sensor_type: str,
    name_contains: tuple[str, ...],
) -> lhm.Sensor | None:
    for sensor in sensors:
        name = sensor.name.lower()
        if sensor.type != sensor_type:
            continue
        if name_contains and not any(part in name for part in name_contains):
            continue
        return sensor
    return None


def _matching_sensors(
    sensors: list[lhm.Sensor],
    *,
    sensor_type: str,
    name_contains: tuple[str, ...],
    name_starts_with: tuple[str, ...] = (),
) -> list[lhm.Sensor]:
    matches: list[lhm.Sensor] = []
    for sensor in sensors:
        name = sensor.name.lower()
        if sensor.type != sensor_type:
            continue
        if name_contains and not all(part in name for part in name_contains):
            continue
        if name_starts_with and not any(
            name.startswith(prefix) for prefix in name_starts_with
        ):
            continue
        matches.append(sensor)
    return matches


__all__ = [
    "METRICS",
    "collect_metric",
    "debug_lhm_cpu_sensor_matches",
    "get_supported_metrics",
    "supports_metric",
]
