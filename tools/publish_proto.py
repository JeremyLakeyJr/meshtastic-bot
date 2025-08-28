#!/usr/bin/env python3
import time
import paho.mqtt.client as mqtt
from meshtastic.protobuf import mqtt_pb2, portnums_pb2

BROKER = "127.0.0.1"        # or your LAN IP
PORT   = 1883
USER   = "bot"
PASS   = "Ttaagghhaacckk3`"

REGION = "EU"
VER    = "2"
TOPIC  = f"msh/{REGION}/{VER}/c/LongFast/!00000001"

def build_env(text="/bot hi"):
    env = mqtt_pb2.ServiceEnvelope()
    env.gateway_id = "!00000001"

    pkt = env.packet
    setattr(pkt, "from", 0x00000002)        # sender node id
    pkt.to = 0xFFFFFFFF                     # broadcast → public
    pkt.id = int(time.time()) & 0xFFFFFFFF  # fits 32-bit
    pkt.rx_time = int(time.time())

    # Properly set decoded payload (raw bytes)
    pkt.decoded.portnum = portnums_pb2.PortNum.TEXT_MESSAGE_APP
    pkt.decoded.payload = text.encode("utf-8")

    return env

def main():
    env = build_env("/bot hi from test")
    payload = env.SerializeToString()

    cli = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, client_id="proto-pub")
    cli.username_pw_set(USER, PASS)
    cli.connect(BROKER, PORT, 60)
    cli.loop_start()
    print(f"Publishing protobuf to {TOPIC} ({len(payload)} bytes)")
    cli.publish(TOPIC, payload, qos=0, retain=False)
    time.sleep(1.0)
    cli.loop_stop()
    cli.disconnect()
    print("Done.")

if __name__ == "__main__":
    main()
