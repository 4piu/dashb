import psutil


def get_net_io_counters(
    pernic: bool = False,
) -> dict[str, dict[str, int]]:
    return {
        nic: counters._asdict()
        for nic, counters in psutil.net_io_counters(pernic=pernic).items()
    }

