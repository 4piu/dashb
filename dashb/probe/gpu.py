import subprocess


def get_nv_gpu_info(
    query_gpu: list = [
        "name",
        "utilization.gpu",
        "memory.used",
        "memory.total",
        "temperature.gpu",
        "power.draw",
        "power.limit",
        "clocks.gr",
        "clocks.max.gr",
        "clocks.sm",
        "clocks.max.sm",
        "clocks.mem",
        "clocks.max.mem",
    ]
) -> list[str | float]:
    """
    Get GPU information from nvidia-smi
    """
    query = ",".join(query_gpu)
    cmd = f"nvidia-smi --query-gpu={query} --format=csv,noheader,nounits"
    result = subprocess.run(cmd, shell=True, capture_output=True)
    if result.returncode != 0:
        return []

    # validate output format
    decoded_results = result.stdout.decode().split(",")
    if len(decoded_results) != len(query_gpu):
        return []

    # try to convert to float or int else return as string
    return [
        (
            float(item.strip())
            if item.strip().replace(".", "", 1).isdigit()
            else item.strip()
        )
        for item in decoded_results
    ]
