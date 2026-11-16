import csv
import json
import os
import time
import statistics
from datetime import datetime
import paho.mqtt.client as mqtt

TOPIC = "benchmark/v2/mqtt"
RESULTS_DIR = "/home/pi/iot-benchmark/results"

os.makedirs(RESULTS_DIR, exist_ok=True)

test_data = {}
expected_counts = {}


def on_connect(client, userdata, flags, reason_code, properties):
    print("Connected to MQTT broker", flush=True)
    client.subscribe(TOPIC, qos=1)
    print(f"Listening on {TOPIC}", flush=True)


def on_message(client, userdata, msg):
    try:
        header, payload = msg.payload.split(b"|", 1)
        info = json.loads(header.decode())

        test_id = int(info["test"])
        sequence = int(info["seq"])
        expected = int(info["expected"])
        sent_ns = int(info["sent_ns"])
        size = int(info["size"])

        now_ns = time.time_ns()
        latency_ms = (now_ns - sent_ns) / 1_000_000

        if test_id not in test_data:
            test_data[test_id] = {
                "expected": expected,
                "size": size,
                "sequences": set(),
                "duplicates": 0,
                "bytes": 0,
                "latencies": [],
                "first": time.monotonic(),
                "last": time.monotonic(),
            }

        test = test_data[test_id]

        if sequence in test["sequences"]:
            test["duplicates"] += 1
        else:
            test["sequences"].add(sequence)
            test["bytes"] += len(msg.payload)
            test["latencies"].append(latency_ms)

        test["last"] = time.monotonic()

        count = len(test["sequences"])

        if count % 100 == 0:
            print(
                f"Test {test_id}: {count}/{expected} messages | "
                f"Latest latency: {latency_ms:.2f} ms",
                flush=True
            )

    except Exception as e:
        print(f"Invalid message: {e}", flush=True)


def save_results():
    if not test_data:
        print("No benchmark data received.")
        return

    filename = datetime.now().strftime(
        "mqtt_benchmark_%Y%m%d_%H%M%S.csv"
    )
    filepath = os.path.join(RESULTS_DIR, filename)

    fields = [
        "test_id",
        "payload_bytes",
        "expected_messages",
        "received_messages",
        "lost_messages",
        "delivery_percent",
        "duplicates",
        "elapsed_seconds",
        "throughput_kbps",
        "average_latency_ms",
        "median_latency_ms",
        "p95_latency_ms",
        "p99_latency_ms",
    ]

    with open(filepath, "w", newline="") as file:
        writer = csv.DictWriter(file, fieldnames=fields)
        writer.writeheader()

        for test_id, test in sorted(test_data.items()):
            received = len(test["sequences"])
            expected = test["expected"]
            lost = max(expected - received, 0)

            elapsed = test["last"] - test["first"]
            throughput = (
                test["bytes"] * 8 / elapsed / 1000
                if elapsed > 0 else 0
            )

            latencies = test["latencies"]

            def percentile(values, p):
                if not values:
                    return 0
                ordered = sorted(values)
                index = round((len(ordered) - 1) * p)
                return ordered[index]

            row = {
                "test_id": test_id,
                "payload_bytes": test["size"],
                "expected_messages": expected,
                "received_messages": received,
                "lost_messages": lost,
                "delivery_percent": round(
                    received / expected * 100, 2
                ) if expected else 0,
                "duplicates": test["duplicates"],
                "elapsed_seconds": round(elapsed, 3),
                "throughput_kbps": round(throughput, 2),
                "average_latency_ms": round(
                    statistics.mean(latencies), 3
                ) if latencies else 0,
                "median_latency_ms": round(
                    statistics.median(latencies), 3
                ) if latencies else 0,
                "p95_latency_ms": round(
                    percentile(latencies, 0.95), 3
                ),
                "p99_latency_ms": round(
                    percentile(latencies, 0.99), 3
                ),
            }

            writer.writerow(row)

            print(
                f"\nTest {test_id}: "
                f"{received}/{expected} received | "
                f"{row['delivery_percent']}% delivery | "
                f"{throughput:.2f} kbps"
            )

    print(f"\nResults saved to: {filepath}")


client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2)
client.on_connect = on_connect
client.on_message = on_message

try:
    client.connect("localhost", 1883)
    client.loop_forever()

except KeyboardInterrupt:
    print("\nStopping benchmark receiver...")

finally:
    save_results()
    client.disconnect()
