
import logging
import meshtastic
import meshtastic.serial_interface
from pubsub import pub

class RadioInterface:
    def __init__(self, message_callback):
        self.message_callback = message_callback
        try:
            self.interface = meshtastic.serial_interface.SerialInterface()
            pub.subscribe(self.on_receive, "meshtastic.receive")
            logging.info("Successfully connected to Meshtastic device.")
        except meshtastic.MeshtasticError as e:
            logging.error(f"Error connecting to Meshtastic device: {e}")
            self.interface = None

    def on_receive(self, packet, interface):
        if packet and 'decoded' in packet and 'text' in packet['decoded']:
            self.message_callback(packet)

    def send_message(self, text, destination_id):
        if self.interface:
            logging.info(f"Sending message to {destination_id}: {text}")
            self.interface.sendText(text=text, destinationId=destination_id)
        else:
            logging.error("Meshtastic device not connected. Cannot send message.")

    def close(self):
        if self.interface:
            self.interface.close()
            logging.info("Meshtastic device connection closed.")
