from typing import Callable
from . import cpu, memory, network, gpu

# funct_id to func mapping

Functions: dict[str, Callable] = {
    "hw.cpu.percent": cpu.get_cpu_percent,
    "hw.cpu.freq": cpu.get_cpu_freq,
    "hw.cpu.load_avg": cpu.get_load_avg,
    "hw.memory.virtual": memory.get_virtual_memory,
    "hw.memory.swap": memory.get_swap_memory,
    "hw.gpu.nvidia": gpu.get_nv_gpu_info,
    "net.io": network.get_net_io_counters,
}

__all__ = ["Functions"]