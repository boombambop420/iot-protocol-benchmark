import csv
import re
import subprocess
import time
from pathlib import Path

import serial
from network_conditions import apply_condition, clear_conditions

PORT = "/dev/ttyUSB0"
BAUD = 115200
N = 2
CONDITION = "C2"

VARIANTS = [
    "http_new", "http_keep",
    "mqtt0", "mqtt1", "mqtt2",
    "coap_con", "coap_non",
]

OUTDIR = Path.home() / "iot-benchmark/results/experiment_01"
OUTDIR.mkdir(parents=True, exist_ok=True)


try:
    apply_condition(CONDITION)
    with serial.Serial(PORT, BAUD, timeout=1) as esp:
        time.sleep(5)
        esp.reset_input_buffer()

        for variant in VARIANTS:
            print(f"\n=== {variant} ===", flush=True)

            rows = []
            started = False
            finished = False

            pcap = OUTDIR / f"{variant}_{CONDITION}.pcap"
            capture = subprocess.Popen([
                "sudo", "tcpdump",
                "-U", "-i", "wlan0",
                "-w", str(pcap),
            ], stdout=subprocess.DEVNULL,
               stderr=subprocess.DEVNULL,
               start_new_session=True)

            try:
                time.sleep(2)

                command = f"RUN {variant} {N}\n"
                esp.write(command.encode("ascii"))
                esp.flush()

                deadline = time.monotonic() + N * 12 + 60

                while time.monotonic() < deadline:
                    line = esp.readline().decode(
                        errors="replace"
                    ).strip()

                    if not line:
                        continue

                    print(line, flush=True)

                    if line.startswith(
                        f"Starting {variant} with {N} requests"
                    ):
                        started = True
                        continue

                    if not started:
                        continue

                    match = re.fullmatch(
                        r"(\d+),(-?\d+),([01])", line
                    )

                    if match:
                        seq, rtt, ok = map(int, match.groups())

                        if seq == len(rows):
                            rows.append([seq, rtt, ok])

                    elif line == "DONE":
                        finished = True
                        break

            finally:
                import os
                import signal

                os.killpg(capture.pid, signal.SIGINT)
                try:
                    capture.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    os.killpg(capture.pid, signal.SIGKILL)
                    capture.wait()

            if not finished or len(rows) != N:
                raise RuntimeError(
                    f"{variant}: incomplete run "
                    f"({len(rows)}/{N}, DONE={finished})"
                )

            filename = OUTDIR / f"{variant}_{CONDITION}.csv"

            with filename.open("w", newline="") as file:
                writer = csv.writer(file)
                writer.writerow(["seq", "rtt_us", "ok"])
                writer.writerows(rows)

            print(
                f"Saved {filename} | "
                f"Success: {sum(r[2] for r in rows)}/{N}",
                flush=True
            )

            time.sleep(5)

    print("\nBaseline pilot completed successfully!")

finally:
    clear_conditions()
    print("Network restored to normal.")
