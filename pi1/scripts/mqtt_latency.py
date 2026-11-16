import time
import statistics
import threading
import paho.mqtt.client as mqtt

BROKER = "172.20.10.8"
TRIALS = 20

received = threading.Event()
latencies = []

def on_connect(client, userdata, flags, reason_code, properties):
    client.subscribe("benchmark/response")

def on_message(client, userdata, msg):
    received.set()

client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2)
client.on_connect = on_connect
client.on_message = on_message

client.connect(BROKER, 1883)
client.loop_start()

while not client.is_connected():
    time.sleep(0.01)

time.sleep(0.5)

for i in range(TRIALS):
    received.clear()

    start = time.perf_counter()
    client.publish("benchmark/request", str(i), qos=0)

    if received.wait(timeout=5):
        elapsed = (time.perf_counter() - start) * 1000
        latencies.append(elapsed)
        print("Trial {}: {:.2f} ms".format(i + 1, elapsed))
    else:
        print("Trial {}: TIMEOUT".format(i + 1))

    time.sleep(0.1)

client.loop_stop()
client.disconnect()

if latencies:
    print("\n--- MQTT ROUND-TRIP RESULTS ---")
    print("Successful: {}/{}".format(len(latencies), TRIALS))
    print("Average: {:.2f} ms".format(statistics.mean(latencies)))
    print("Minimum: {:.2f} ms".format(min(latencies)))
    print("Maximum: {:.2f} ms".format(max(latencies)))
