import csv
import json
import time
import paho.mqtt.client as mqtt

TOPIC = "benchmark/throughput"
RESULTS_FILE = "/home/pi/iot-benchmark/mqtt_throughput_results.csv"

tests = {}


def on_connect(client, userdata, flags, reason_code, properties):
    print("Connected to MQTT broker", flush=True)
    client.subscribe(TOPIC, qos=1)
    print("Throughput receiver ready", flush=True)


def on_message(client, userdata, msg):
    try:
        header, payload = msg.payload.split(b"|", 1)
        info = json.loads(header.decode())

        test_id = int(info["test"])
        sequence = int(info["seq"])
        qos = int(info["qos"])
        size = int(info["size"])

        now = time.monotonic()

        if test_id not in tests:
            tests[test_id] = {
                "qos": qos,
                "size": size,
                "sequences": set(),
                "duplicates": 0,
                "bytes": 0,
                "first": now,
                "last": now,
            }

        test = tests[test_id]

        if sequence in test["sequences"]:
            test["duplicates"] += 1
        else:
            test["sequences"].add(sequence)
            test["bytes"] += len(msg.payload)

        test["last"] = now

        count = len(test["sequences"])

        if count > 0 and count % 100 == 0:
            elapsed = test["last"] - test["first"]
            kbps = (
                test["bytes"] * 8 / elapsed / 1000
                if elapsed > 0 else 0
            )

            print(
                f"Test {test_id} | QoS {qos} | "
                f"{size} bytes | Messages {count} | "
                f"Throughput {kbps:.2f} kbps",
                flush=True,
            )

    except Exception as e:
        print(f"Invalid message: {e}", flush=True)


def save_results():
    print("\n===== FINAL RECEIVER RESULTS =====")

    with open(RESULTS_FILE, "w", newline="") as file:
        writer = csv.writer(file)

        writer.writerow([
            "test",
            "qos",
            "payload_bytes",
            "unique_messages",
            "duplicates",
            "received_bytes",
            "elapsed_seconds",
            "received_kbps",
        ])

        for test_id in sorted(tests):
            test = tests[test_id]

            elapsed = test["last"] - test["first"]
            count = len(test["sequences"])

            kbps = (
                test["bytes"] * 8 / elapsed / 1000
                if elapsed > 0 else 0
            )

            writer.writerow([
                test_id,
                test["qos"],
                test["size"],
                count,
                test["duplicates"],
                test["bytes"],
                round(elapsed, 3),
                round(kbps, 2),
            ])

            print(
                f"Test {test_id}: "
                f"{count} unique messages, "
                f"{test['duplicates']} duplicates, "
                f"{kbps:.2f} kbps"
            )

    print(f"\nResults saved to {RESULTS_FILE}")


client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2)
client.on_connect = on_connect
client.on_message = on_message

try:
    client.connect("localhost", 1883)
    client.loop_forever()

except KeyboardInterrupt:
    print("\nReceiver stopped.")

finally:
    save_results()
    client.disconnect()
