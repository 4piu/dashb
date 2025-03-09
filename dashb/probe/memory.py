import psutil


def get_virtual_memory() -> dict[str, int | float]:
    return psutil.virtual_memory()._asdict()


def get_swap_memory() -> dict[str, int | float]:
    return psutil.swap_memory()._asdict()