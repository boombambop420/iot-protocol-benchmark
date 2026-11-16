import argparse
import csv
import os
import re
import signal
import subprocess
import time
from pathlib import Path

import serial
from network_conditions import apply_condition, clear_conditions, CONDITIONS

PORT = "/dev/ttyUSB0"
BAUD = 115200

VARIANTS = [
    "http_new", "http_keep",
    "mqtt0", "mqtt1", "mqtt2",
    "coap_con", "coap_non",
]

parser = argparse.ArgumentParser()
parser.add_argument("--n", type=int, default=2)
parser.add_argument("--conditions", nargs="+", default=list(CONDITIONS))
parser.add_argument("--variants", nargs="+", default=VARIANTS)
parser.add_argument("--outdir", default="results/full_pilot")
args = parser.parse_args()

if args.n < 1:
    parser.error("--n must be positive")

for condition in args.conditions:
    if condition not in CONDITIONS:
        parser.error(f"Unknown condition: {condition}")

outdir = Path(args.outdir)
outdir.mkdir(parents=True, exist_ok=True)


def run_variant(esp, variant, condition):
    print(f"\n=== {condition}: {variant} ===", flush=True)

    rows = []
    run_start = None
    run_end = None
    started = False
    finished = False

    pcap = outdir / f"{variant}_{condition}.pcap"

    capture = subprocess.Popen(
        ["sudo", "tcpdump", "-U", "-i", "wlan0", "-w", str(pcap)],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        start_new_session=True,
    )

    try:
        time.sleep(2)

        if capture.poll() is not None:
            raise RuntimeError("tcpdump exited unexpectedly")

        esp.reset_input_buffer()
        run_start = time.monotonic()
        esp.write(f"RUN {variant} {args.n}\n".encode("ascii"))
        esp.flush()

        deadline = time.monotonic() + args.n * 12 + 60

        while time.monotonic() < deadline:
            line = esp.readline().decode(errors="replace").strip()

            if not line:
                continue

            print(line, flush=True)

            if line.startswith(
                f"Starting {variant} with {args.n} requests"
            ):
                started = True
                continue

            if not started:
                continue

            match = re.fullmatch(r"(\d+),(-?\d+),([01])", line)

            if match:
                seq, rtt, ok = map(int, match.groups())
                if seq == len(rows):
                    rows.append([seq, rtt, ok])

            elif line == "DONE":
                run_end = time.monotonic()
                finished = True
                break

    finally:
        if capture.poll() is None:
            os.killpg(capture.pid, signal.SIGINT)
            try:
                capture.wait(timeout=10)
            except subprocess.TimeoutExpired:
                os.killpg(capture.pid, signal.SIGKILL)
                capture.wait()

    csv_path = outdir / f"{variant}_{condition}.csv"

    with csv_path.open("w", newline="") as file:
        writer = csv.writer(file)
        writer.writerow(["seq", "rtt_us", "ok"])
        writer.writerows(rows)

    if not finished or len(rows) != args.n:
        raise RuntimeError(
            f"{condition}/{variant}: incomplete run "
            f"({len(rows)}/{args.n}, DONE={finished})"
        )

    duration = run_end - run_start
    metadata_path = outdir / "run_metadata.csv"
    new_file = not metadata_path.exists()
    with metadata_path.open("a", newline="") as file:
        writer = csv.writer(file)
        if new_file:
            writer.writerow(
                ["condition", "variant", "requests",
                 "successes", "duration_s"]
            )
        writer.writerow([
            condition, variant, args.n,
            sum(row[2] for row in rows),
            round(duration, 6)
        ])

    successes = sum(row[2] for row in rows)
    print(
        f"Saved {csv_path} | Success: {successes}/{args.n}",
        flush=True,
    )


try:
    with serial.Serial(PORT, BAUD, timeout=1) as esp:
        time.sleep(5)
        esp.reset_input_buffer()

        for condition in args.conditions:
            apply_condition(condition)
            time.sleep(2)

            for variant in args.variants:
                run_variant(esp, variant, condition)
                time.sleep(5)

    print("\nAll benchmark runs completed!", flush=True)

finally:
    clear_conditions()
    print("Network restored to normal.", flush=True)
