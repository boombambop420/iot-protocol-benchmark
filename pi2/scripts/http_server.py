import csv
import json
import time
from flask import Flask, request, jsonify

app = Flask(__name__)

RESULTS_FILE = "/home/pi/iot-benchmark/http_throughput_results.csv"

tests = {}


@app.route("/ping", methods=["POST"])
def ping():
    """
    HTTP RTT endpoint.
    Returns a response immediately so the ESP32
    can measure request-response latency.
    """
    return request.get_data(), 200, {
        "Content-Type": "application/octet-stream"
    }


@app.route("/throughput", methods=["POST"])
def throughput():
    """
    HTTP throughput endpoint.
    Receives a payload containing a JSON header
    followed by a pipe and padding.
    """
    try:
        data = request.get_data()

        header, payload = data.split(b"|", 1)
        info = json.loads(header.decode())

        test_id = int(info["test"])
        sequence = int(info["seq"])
        size = int(info["size"])

        now = time.monotonic()

        if len(data) != size:
            return jsonify(error="Incorrect payload size"), 400

        if test_id not in tests:
            tests[test_id] = {
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
            test["bytes"] += len(data)

        test["last"] = now

        count = len(test["sequences"])

        if count > 0 and count % 100 == 0:
            elapsed = test["last"] - test["first"]
            kbps = (
                test["bytes"] * 8 / elapsed / 1000
                if elapsed > 0 else 0
            )

            print(
                f"Test {test_id} | HTTP | "
                f"{size} bytes | Messages {count} | "
                f"Throughput {kbps:.2f} kbps",
                flush=True
            )

        return "OK", 200

    except Exception as e:
        print(f"Invalid HTTP message: {e}", flush=True)
        return jsonify(error=str(e)), 400


def save_results():
    print("\n===== FINAL HTTP RECEIVER RESULTS =====")

    with open(RESULTS_FILE, "w", newline="") as file:
        writer = csv.writer(file)

        writer.writerow([
            "test",
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


if __name__ == "__main__":
    try:
        print("HTTP benchmark server starting...", flush=True)
        app.run(
            host="0.0.0.0",
            port=5000,
            debug=False,
            threaded=True,
            use_reloader=False
        )

    except KeyboardInterrupt:
        print("\nHTTP server stopped.")

    finally:
        save_results()
