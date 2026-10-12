import json
import logging
import os
import time
from datetime import datetime, timezone
from threading import Event
from typing import Any
from uuid import UUID, uuid4

from confluent_kafka import Producer
from fastapi import FastAPI, HTTPException, Response
from pydantic import BaseModel, Field
from prometheus_client import Counter, Histogram, generate_latest, CONTENT_TYPE_LATEST

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("utravs-producer")

KAFKA_BOOTSTRAP = os.getenv(
    "KAFKA_BOOTSTRAP_SERVERS",
    "utravs-kafka-kafka-bootstrap.kafka.svc.cluster.local:9092",
)
KAFKA_TOPIC = os.getenv("KAFKA_TOPIC", "utravs-events")

producer = Producer({
    "bootstrap.servers": KAFKA_BOOTSTRAP,
    "acks": "all",
    "enable.idempotence": True,
    "delivery.timeout.ms": 15000,
})

app = FastAPI(title="UTRAVS Event Producer")

events_total = Counter(
    "utravs_producer_events_total",
    "Total events published to Kafka",
    ["result"],
)

publish_duration = Histogram(
    "utravs_producer_publish_seconds",
    "Kafka event publish duration",
)


class EventRequest(BaseModel):
    event_type: str = Field(min_length=1, max_length=100)
    booking_id: str = Field(min_length=1, max_length=128)
    payload: dict[str, Any] = Field(default_factory=dict)
    event_id: UUID | None = None


@app.get("/healthz")
def health():
    return {"status": "ok"}


@app.get("/readyz")
def ready():
    try:
        producer.list_topics(timeout=3)
        return {"status": "ready"}
    except Exception as exc:
        raise HTTPException(
            status_code=503, detail="Kafka unavailable"
        ) from exc


@app.get("/metrics")
def metrics():
    return Response(
        content=generate_latest(),
        media_type=CONTENT_TYPE_LATEST,
    )


@app.post("/events", status_code=201)
def publish_event(request: EventRequest):
    event_id = str(request.event_id or uuid4())

    message = {
        "event_id": event_id,
        "event_type": request.event_type,
        "booking_id": request.booking_id,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "payload": request.payload,
    }

    completed = Event()
    result = {}

    def delivery_callback(error, msg):
        result["error"] = error
        result["message"] = msg
        completed.set()

    with publish_duration.time():
        try:
            producer.produce(
                topic=KAFKA_TOPIC,
                key=request.booking_id.encode("utf-8"),
                value=json.dumps(message).encode("utf-8"),
                callback=delivery_callback,
            )
        except Exception as exc:
            events_total.labels(result="error").inc()
            logger.exception("Failed to queue event")
            raise HTTPException(
                status_code=503,
                detail="Failed to queue Kafka event",
            ) from exc

        deadline = time.monotonic() + 18

        while not completed.is_set() and time.monotonic() < deadline:
            producer.poll(0.2)

        if not completed.is_set():
            events_total.labels(result="error").inc()
            raise HTTPException(
                status_code=504,
                detail="Kafka acknowledgement timed out",
            )

        if result["error"] is not None:
            events_total.labels(result="error").inc()
            raise HTTPException(
                status_code=503,
                detail="Kafka delivery failed",
            )

    msg = result["message"]
    events_total.labels(result="success").inc()

    logger.info(
        "event_published event_id=%s partition=%s offset=%s",
        event_id,
        msg.partition(),
        msg.offset(),
    )

    return {
        "status": "delivered",
        "event_id": event_id,
        "partition": msg.partition(),
        "offset": msg.offset(),
    }
