import base64
import json
import logging
import os
import signal
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from threading import Event, Thread

from confluent_kafka import Consumer, KafkaException, Producer
from opentelemetry.trace import SpanKind
from otel_tracing import setup_tracing, extract_kafka_context
from vault_client import VaultClient
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
tracer = setup_tracing("utravs-consumer")

BOOTSTRAP = os.getenv(
    "KAFKA_BOOTSTRAP_SERVERS",
    "utravs-kafka-kafka-bootstrap.kafka.svc.cluster.local:9092",
)
TOPIC = os.getenv("KAFKA_TOPIC", "utravs-events")
GROUP_ID = os.getenv("KAFKA_GROUP_ID", "utravs-consumer-group")

DLQ_TOPIC = os.getenv("KAFKA_DLQ_TOPIC", "utravs-events-dlq")

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

dlq_total = Counter(
    "utravs_consumer_dlq_total",
    "Messages successfully sent to the dead letter queue",
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



def verify_event_signature(message, vault_client):
    signatures = [
        value
        for name, value in (message.headers() or [])
        if name == "utravs-signature"
    ]

    if len(signatures) != 1:
        raise ValueError("Missing or duplicate event signature")

    raw_signature = signatures[0]

    if not isinstance(raw_signature, bytes):
        raise ValueError("Invalid signature header")

    try:
        signature = raw_signature.decode("ascii")
    except UnicodeDecodeError as exc:
        raise ValueError("Invalid signature encoding") from exc

    if not signature.startswith("vault:v") or len(signature) > 256:
        raise ValueError("Invalid signature format")

    if not vault_client.verify_message(
        message.value() or b"", signature
    ):
        raise ValueError("Event signature verification failed")


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



def send_to_dlq(producer, message, error):
    record = {
        "source_topic": message.topic(),
        "source_partition": message.partition(),
        "source_offset": message.offset(),
        "error_type": type(error).__name__,
        "error": str(error)[:500],
        "original_value_base64": base64.b64encode(
            message.value() or b""
        ).decode("ascii"),
    }

    delivery_results = []

    def on_delivery(err, msg):
        delivery_results.append(err)

    producer.produce(
        DLQ_TOPIC,
        key=message.key(),
        value=json.dumps(record).encode("utf-8"),
        on_delivery=on_delivery,
    )

    remaining = producer.flush(20)

    if (
        remaining != 0
        or not delivery_results
        or delivery_results[0] is not None
    ):
        raise RuntimeError(
            f"DLQ delivery failed: {delivery_results}"
        )

    logger.warning(
        "event_sent_to_dlq topic=%s partition=%s offset=%s",
        message.topic(),
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



def kafka_tls_options():
    protocol = os.getenv(
        "KAFKA_SECURITY_PROTOCOL", "PLAINTEXT"
    ).upper()

    if protocol not in ("PLAINTEXT", "SSL"):
        raise ValueError(f"Unsupported Kafka protocol: {protocol}")

    options = {"security.protocol": protocol}

    if protocol == "SSL":
        ca_path = os.getenv(
            "KAFKA_SSL_CA_LOCATION",
            "/etc/kafka/ca.crt"
        )

        if not os.path.isfile(ca_path):
            raise FileNotFoundError(
                f"Kafka CA certificate missing: {ca_path}"
            )

        options["ssl.ca.location"] = ca_path

        cert_path = os.getenv("KAFKA_SSL_CERT_LOCATION", "").strip()
        key_path = os.getenv("KAFKA_SSL_KEY_LOCATION", "").strip()

        if bool(cert_path) != bool(key_path):
            raise ValueError(
                "Kafka client certificate and key must be configured together"
            )

        if cert_path:
            for file_path in (cert_path, key_path):
                if not os.path.isfile(file_path):
                    raise FileNotFoundError(
                        f"Kafka mTLS credential missing: {file_path}"
                    )

            options["ssl.certificate.location"] = cert_path
            options["ssl.key.location"] = key_path

    return options


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

    vault_client = VaultClient("utravs-consumer")

    dlq_producer = Producer({
        "bootstrap.servers": BOOTSTRAP,
        **kafka_tls_options(),
        "acks": "all",
        "enable.idempotence": True,
        "delivery.timeout.ms": 15000,
    })

    consumer = Consumer({
        "bootstrap.servers": BOOTSTRAP,
        **kafka_tls_options(),
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

                with tracer.start_as_current_span(
                    "kafka.consume",
                    context=extract_kafka_context(msg.headers()),
                    kind=SpanKind.CONSUMER,
                ) as span:
                    span.set_attribute("messaging.system", "kafka")
                    span.set_attribute("messaging.destination.name", msg.topic())
                    span.set_attribute("messaging.kafka.partition", msg.partition())
                    span.set_attribute("messaging.kafka.offset", msg.offset())

                    try:
                        try:
                            verify_event_signature(msg, vault_client)
                            process_message(msg)
                            valid = True

                        except (ValueError, TypeError, KeyError, UnicodeError) as exc:
                            logger.warning(
                                "Invalid event: %s; routing to DLQ", exc
                            )
                            send_to_dlq(dlq_producer, msg, exc)
                            valid = False

                        # Commit only after processing or confirmed DLQ delivery.
                        consumer.commit(
                            message=msg,
                            asynchronous=False,
                        )

                        if valid:
                            processed_total.inc()
                        else:
                            dlq_total.inc()

                    except Exception:
                        errors_total.inc()
                        logger.exception(
                            "Processing, DLQ delivery or commit failed"
                        )
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
