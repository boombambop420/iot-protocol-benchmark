import subprocess

CONDITIONS = {
    "C1": (0, 0),
    "C2": (50, 0),
    "C3": (0, 2),
    "C4": (0, 5),
    "C5": (50, 5),
    "C6": (200, 10),
}

INTERFACES = ["wlan0", "eth0"]


def run_tc(*args):
    subprocess.run(
        ["sudo", "tc", *args],
        check=True
    )


def clear_conditions():
    for interface in INTERFACES:
        subprocess.run(
            ["sudo", "tc", "qdisc", "del",
             "dev", interface, "root"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL
        )


def apply_condition(name):
    delay, loss = CONDITIONS[name]

    clear_conditions()

    if delay == 0 and loss == 0:
        print(f"{name}: baseline network", flush=True)
        return

    args = []

    if delay:
        jitter = max(1, delay // 5)
        args += ["delay", f"{delay}ms", f"{jitter}ms"]

    if loss:
        args += ["loss", f"{loss}%"]

    try:
        for interface in INTERFACES:
            run_tc(
                "qdisc", "replace",
                "dev", interface,
                "root", "netem", *args
            )
    except Exception:
        clear_conditions()
        raise

    print(
        f"{name}: delay={delay}ms, loss={loss}%",
        flush=True
    )
