import paho.mqtt.client as mqtt

def on_connect(client, userdata, flags, reason_code, properties):
    print("Connected to MQTT broker", flush=True)

    for qos in (0, 1, 2):
        client.subscribe(f"lab/req/{qos}", qos=qos)

def on_message(client, userdata, msg):
    qos = msg.qos
    response_topic = msg.topic.replace("req", "resp")

    client.publish(
        response_topic,
        msg.payload,
        qos=qos
    )

    print(f"Echoed QoS {qos}", flush=True)

client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2)
client.on_connect = on_connect
client.on_message = on_message

client.connect("localhost", 1883)
client.loop_forever()
