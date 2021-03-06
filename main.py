"""Main entrypoint for this application"""
import os
import sys
import logging
import warnings
from ssl import SSLError
from threading import Thread

from time import sleep
from environs import Env
from paho.mqtt.client import Client, MQTTv5
from paho.mqtt.subscribeoptions import SubscribeOptions

env = Env()

## Source config
MQTT_SOURCE_HOST = env("MQTT_SOURCE_HOST")
MQTT_SOURCE_PORT = env.int("MQTT_SOURCE_PORT", 1883)
MQTT_SOURCE_CLIENT_ID = env("MQTT_SOURCE_CLIENT_ID", "")
MQTT_SOURCE_TRANSPORT = env(
    "MQTT_SOURCE_TRANSPORT", "tcp", validate=lambda s: s in ("tcp", "websockets")
)
MQTT_SOURCE_TLS = env.bool("MQTT_SOURCE_TLS", False)
MQTT_SOURCE_USER = env("MQTT_SOURCE_USER", None)
MQTT_SOURCE_PASSWORD = env("MQTT_SOURCE_PASSWORD", None)

## Remote config
MQTT_REMOTE_HOST = env("MQTT_REMOTE_HOST")
MQTT_REMOTE_PORT = env.int("MQTT_REMOTE_PORT", 1883)
MQTT_REMOTE_CLIENT_ID = env("MQTT_REMOTE_CLIENT_ID", "")
MQTT_REMOTE_TRANSPORT = env(
    "MQTT_REMOTE_TRANSPORT", "tcp", validate=lambda s: s in ("tcp", "websockets")
)
MQTT_REMOTE_TLS = env.bool("MQTT_REMOTE_TLS", False)
MQTT_REMOTE_USER = env("MQTT_REMOTE_USER", None)
MQTT_REMOTE_PASSWORD = env("MQTT_REMOTE_PASSWORD", None)

# Bridging config
MQTT_TOPICS = env.list("MQTT_TOPICS", [])

LOG_LEVEL = env.log_level("LOG_LEVEL", logging.WARNING)

# Setup logger
logging.basicConfig(
    format="%(asctime)s %(levelname)s %(name)s %(message)s", level=LOG_LEVEL
)
logging.captureWarnings(True)
warnings.filterwarnings("once")
LOGGER = logging.getLogger("crowsnest-bridge-mqtt")

# Source setup
source = Client(
    client_id=MQTT_SOURCE_CLIENT_ID, transport=MQTT_SOURCE_TRANSPORT, protocol=MQTTv5
)
source.username_pw_set(MQTT_SOURCE_USER, MQTT_SOURCE_PASSWORD)
if MQTT_SOURCE_TLS:
    source.tls_set()


# Remote setup
remote = Client(
    client_id=MQTT_REMOTE_CLIENT_ID, transport=MQTT_REMOTE_TRANSPORT, protocol=MQTTv5
)
remote.username_pw_set(MQTT_REMOTE_USER, MQTT_REMOTE_PASSWORD)
if MQTT_REMOTE_TLS:
    remote.tls_set()


SUBSCRIBE_OPTIONS = SubscribeOptions(
    qos=0,
    noLocal=True,
    retainAsPublished=False,
    retainHandling=SubscribeOptions.RETAIN_SEND_ON_SUBSCRIBE,
)


@remote.message_callback()
def publish_to_source(client, userdata, message):  # pylint: disable=unused-argument
    """Publish to source broker"""
    try:
        source.publish(
            message.topic,
            message.payload,
            message.qos,
            message.retain,
            message.properties,
        )
    except SSLError:
        LOGGER.exception("Failed to publish to remote! Reconnecting...")
        remote.reconnect()
    except Exception:  # pylint: disable=broad-except
        LOGGER.exception("Failed to publish to remote! Fatal error!")
        os._exit(1)  # pylint: disable=protected-access


@source.message_callback()
def publish_to_remote(client, userdata, message):  # pylint: disable=unused-argument
    """Publish to remote broker"""
    try:
        remote.publish(
            message.topic,
            message.payload,
            message.qos,
            message.retain,
            message.properties,
        )
    except SSLError:
        LOGGER.exception("Failed to publish to remote! Reconnecting...")
        remote.reconnect()
    except Exception:  # pylint: disable=broad-except
        LOGGER.exception("Failed to publish to remote! Fatal error!")
        os._exit(1)  # pylint: disable=protected-access


@source.connect_callback()
@remote.connect_callback()
def on_connect(
    client, userdata, flags, reason_code, properties=None
):  # pylint: disable=unused-argument
    """Subscribe on connect"""
    if reason_code != 0:
        LOGGER.error(
            "Connection failed to %s with reason code: %s", client, reason_code
        )
        return

    for topic in MQTT_TOPICS:
        client.subscribe(topic, options=SUBSCRIBE_OPTIONS, properties=None)


@source.disconnect_callback()
@remote.disconnect_callback()
def on_disconnect(
    client, userdata, flags, reason_code, properties=None
):  # pylint: disable=unused-argument
    """Subscribe on connect"""
    if reason_code != 0:
        LOGGER.error("Disconnected from %s with reason code: %s", client, reason_code)


# Logging
source.enable_logger(logging.getLogger("crowsnest-bridge-mqtt-SOURCE"))
remote.enable_logger(logging.getLogger("crowsnest-bridge-mqtt-REMOTE"))

# Do connection
remote.connect(MQTT_REMOTE_HOST, MQTT_REMOTE_PORT)
source.connect(MQTT_SOURCE_HOST, MQTT_SOURCE_PORT)


# Loop_forever handles reconnections automatically, lets use that
source_thread = Thread(target=source.loop_forever)
source_thread.daemon = True
source_thread.start()

remote_thread = Thread(target=remote.loop_forever)
remote_thread.daemon = True
remote_thread.start()

while source_thread.is_alive() and remote_thread.is_alive():
    sleep(1)

sys.exit(1)
