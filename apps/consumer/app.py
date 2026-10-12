import json
import logging
import os
import signal
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from threading import Event, Thread

from confluent_kafka import Consumer, KafkaException, TopicPartition
from prometheus_client import (
    Counter,
    Gauge,
    CONTENT_TYPE_LATEST,
    generate_latest,
)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
)
logger = logging.getLogger("utravs-consumer")

BOOTSTRAP = os.getenv(
    "KAFKA_BOOTSTRAP_SERVERS",
    "utravs-kafka-kafka-bootstrap.kafka.svc.cluster.local:9092",
)
TOPIC = os.getenv("KAFKA_TOPIC", "utravs-events")
GROUP_ID = os.getenv("KAFKA_GROUP_ID", "utravs-consumer-group")

running = Event()
running.set()
ready = Event()

processed_total = Counter(
    "utravs_consumer_processed_total",
    "Successfully processed Kafka messages",
)

errors_total = Counter(
    "utravs_consumer_errors_total",
    "Consumer processing errors",
)

consumer_lag = Gauge(
    "utravs_consumer_lag",
    "Estimated unprocessed messages by partition",
    ["topic", "partition"],
)


class HealthHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path == "/metrics":
            body = generate_latest()
            content_type = CONTENT_TYPE_LATEST
            status = 200

        elif self.path in ("/healthz", "/readyz"):
            healthy = running.is_set()
            if self.path == "/readyz":
                healthy = healthy and ready.is_set()

            status = 200 if healthy else 503
            body = json.dumps(
                {"status": "ok" if healthy else "unavailable"}
            ).encode()
            content_type = "application/json"

        else:
            status = 404
            body = b"Not found"
            content_type = "text/plain"

        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, format, *args):
        pass


def stop(signum, frame):
    logger.info("Shutdown signal received")
    running.clear()


def process_message(message):
    event = json.loads(message.value())

    event_id = event["event_id"]
    event_type = event["event_type"]
    booking_id = event["booking_id"]

    # Demonstration business logic: validate and process an event.
    # A production implementation would use a durable,
    # idempotent business operation keyed by event_id.
    logger.info(
        "event_processed event_id=%s event_type=%s "
        "booking_id=%s partition=%s offset=%s",
        event_id,
        event_type,
        booking_id,
        message.partition(),
        message.offset(),
    )


def update_lag(consumer):
    for partition in consumer.assignment():
        low, high = consumer.get_watermark_offsets(
            partition, timeout=2, cached=False
        )

        committed = consumer.committed(
            [partition], timeout=2
        )[0].offset

        if committed >= 0:
            lag = max(0, high - committed)
            consumer_lag.labels(
                topic=partition.topic,
                partition=str(partition.partition),
            ).set(lag)


def main():
    signal.signal(signal.SIGTERM, stop)
    signal.signal(signal.SIGINT, stop)

    http_server = ThreadingHTTPServer(
        ("0.0.0.0", 8080), HealthHandler
    )
    Thread(
        target=http_server.serve_forever,
        daemon=True,
    ).start()

    consumer = Consumer({
        "bootstrap.servers": BOOTSTRAP,
        "group.id": GROUP_ID,
        "auto.offset.reset": "earliest",
        "enable.auto.commit": False,
        "enable.auto.offset.store": False,
    })

    def on_assign(client, partitions):
        logger.info("Partitions assigned: %s", partitions)
        ready.set()

    def on_revoke(client, partitions):
        ready.clear()
        logger.info("Partitions revoked: %s", partitions)

    consumer.subscribe(
        [TOPIC],
        on_assign=on_assign,
        on_revoke=on_revoke,
    )

    last_lag_check = 0

    try:
        while running.is_set():
            msg = consumer.poll(1.0)

            if msg is not None:
                if msg.error():
                    logger.error("Kafka error: %s", msg.error())
                    errors_total.inc()
                    continue

                try:
                    process_message(msg)

                    # Commit only after successful processing.
                    consumer.commit(
                        message=msg,
                        asynchronous=False,
                    )
                    processed_total.inc()

                except Exception:
                    errors_total.inc()
                    logger.exception(
                        "Processing failed; offset not committed"
                    )
                    # Restart rather than skip a failed message.
                    raise

            if time.monotonic() - last_lag_check >= 5:
                try:
                    update_lag(consumer)
                except KafkaException as exc:
                    logger.warning("Lag metrics unavailable: %s", exc)
                last_lag_check = time.monotonic()

    finally:
        ready.clear()
        consumer.close()
        http_server.shutdown()
        http_server.server_close()
        logger.info("Consumer stopped")


if __name__ == "__main__":
    main()
