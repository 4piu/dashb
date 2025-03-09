import psutil


def get_cpu_percent(*args, **kwargs) -> float | list[float]:
    return psutil.cpu_percent(*args, **kwargs)


def get_cpu_freq(percpu: bool = False) -> dict[str, float] | list[dict[str, float]]:
    result = psutil.cpu_freq(percpu=percpu)
    return [cpu._asdict() for cpu in result] if percpu else result._asdict()


def get_load_avg() -> tuple[float, float, float]:
    return psutil.getloadavg()
