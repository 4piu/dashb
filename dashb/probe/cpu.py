import psutil

from dashb.probe import lhm
from dashb.probe.types import MetricMap

METRICS = {
    "cpu.utilization": {"unit": "%", "kind": "gauge", "subscribable": True},
    "cpu.per_core.utilization": {"unit": "%", "kind": "gauge", "subscribable": True},
    "cpu.logical_cores": {"unit": "count", "kind": "gauge", "subscribable": False},
    "cpu.physical_cores": {"unit": "count", "kind": "gauge", "subscribable": False},
}

LHM_CPU_METRICS = {
    "cpu.package_temperature_c": {"unit": "C", "kind": "gauge", "subscribable": True},
    "cpu.core_temperatures_c": {"unit": "C", "kind": "gauge", "subscribable": True},
    "cpu.core_average_voltage_v": {
        "unit": "V",
        "kind": "gauge",
        "subscribable": True,
    },
    "cpu.per_core_vid_v": {"unit": "V", "kind": "gauge", "subscribable": True},
    "cpu.package_power_w": {"unit": "W", "kind": "gauge", "subscribable": True},
    "cpu.max_core_clock_mhz": {
        "unit": "MHz",
        "kind": "gauge",
        "subscribable": True,
    },
    "cpu.per_core_clock_mhz": {
        "unit": "MHz",
        "kind": "gauge",
        "subscribable": True,
    },
}

_lhm_cpu_sensor_ids: dict[str, str | list[str]] | None = None


def get_cpu_percent(percpu: bool = False) -> float | list[float]:
    return psutil.cpu_percent(percpu=percpu)


def get_cpu_freq(percpu: bool = False) -> dict[str, float] | list[dict[str, float]]:
    result = psutil.cpu_freq(percpu=percpu)
    return [cpu._asdict() for cpu in result] if percpu else result._asdict()


def get_load_avg() -> tuple[float, float, float]:
    return psutil.getloadavg()


def get_supported_metrics() -> MetricMap:
    metrics = METRICS.copy()
    for metric in _get_lhm_cpu_sensor_ids():
        metrics[metric] = LHM_CPU_METRICS[metric]
    return metrics


def supports_metric(metric: str) -> bool:
    return metric in METRICS or metric in _get_lhm_cpu_sensor_ids()


def collect_metric(metric: str) -> float | int | list[float]:
    if metric == "cpu.utilization":
        return get_cpu_percent(percpu=False)
    if metric == "cpu.per_core.utilization":
        return get_cpu_percent(percpu=True)
    if metric == "cpu.logical_cores":
        return psutil.cpu_count(logical=True) or 0
    if metric == "cpu.physical_cores":
        return psutil.cpu_count(logical=False) or 0
    if metric == "cpu.package_temperature_c":
        return _read_lhm_scalar(metric)
    if metric == "cpu.core_temperatures_c":
        return _read_lhm_array(metric)
    if metric == "cpu.core_average_voltage_v":
        return _average(_read_lhm_array("cpu.per_core_vid_v"))
    if metric == "cpu.per_core_vid_v":
        return _read_lhm_array(metric)
    if metric == "cpu.package_power_w":
        return _read_lhm_scalar(metric)
    if metric == "cpu.max_core_clock_mhz":
        return _max(_read_lhm_array("cpu.per_core_clock_mhz"))
    if metric == "cpu.per_core_clock_mhz":
        return _read_lhm_array(metric)
    raise KeyError(metric)


def _get_lhm_cpu_sensor_ids() -> dict[str, str | list[str]]:
    global _lhm_cpu_sensor_ids

    if _lhm_cpu_sensor_ids is not None:
        return _lhm_cpu_sensor_ids

    sensor_ids: dict[str, str | list[str]] = {}
    sensors = [
        sensor
        for sensor in lhm.list_sensors()
        if sensor.hardware_type.lower() == "cpu"
    ]

    package_temperature = _first_sensor(
        sensors,
        sensor_type="Temperature",
        name_contains=("package", "tdie", "tctl"),
    )
    if package_temperature:
        sensor_ids["cpu.package_temperature_c"] = package_temperature.id

    core_temperatures = [
        sensor.id
        for sensor in sensors
        if sensor.type == "Temperature" and "core" in sensor.name.lower()
    ]
    if core_temperatures:
        sensor_ids["cpu.core_temperatures_c"] = core_temperatures

    per_core_vid = _matching_sensors(
        sensors,
        sensor_type="Voltage",
        name_contains=("vid",),
        name_starts_with=("core #",),
    )
    if per_core_vid:
        sensor_ids["cpu.per_core_vid_v"] = [sensor.id for sensor in per_core_vid]
        sensor_ids["cpu.core_average_voltage_v"] = [
            sensor.id for sensor in per_core_vid
        ]

    package_power = _first_sensor(
        sensors,
        sensor_type="Power",
        name_contains=("package",),
    )
    if package_power:
        sensor_ids["cpu.package_power_w"] = package_power.id

    per_core_clocks = _matching_sensors(
        sensors,
        sensor_type="Clock",
        name_contains=(),
        name_starts_with=("core #",),
    )
    if per_core_clocks:
        sensor_ids["cpu.per_core_clock_mhz"] = [
            sensor.id for sensor in per_core_clocks
        ]
        sensor_ids["cpu.max_core_clock_mhz"] = [sensor.id for sensor in per_core_clocks]

    _lhm_cpu_sensor_ids = sensor_ids
    return sensor_ids


def _read_lhm_scalar(metric: str) -> float | None:
    sensor_id = _get_lhm_cpu_sensor_ids().get(metric)
    return lhm.read_sensor(sensor_id) if isinstance(sensor_id, str) else None


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


def _max(values: list[float | None]) -> float | None:
    valid_values = [value for value in values if value is not None]
    if not valid_values:
        return None
    return max(valid_values)


def _first_sensor(
    sensors: list[lhm.Sensor],
    *,
    sensor_type: str,
    name_contains: tuple[str, ...],
) -> lhm.Sensor | None:
    for sensor in sensors:
        name = sensor.name.lower()
        if sensor.type == sensor_type and any(part in name for part in name_contains):
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
