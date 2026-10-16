# UTRAVS Reliability & Failure Injection Report

## 1. Kubernetes API High Availability

Architecture:
- 3 Kubernetes Control Plane nodes
- HAProxy + Keepalived
- Virtual IP: 172.16.90.135

Test:
- Failure of the active VIP holder
- VIP failover to the remaining load balancer
- Kubernetes API accessibility verified

Result: PASS

Observed interval between last failed and first successful
API request: approximately 1.292 seconds.

Evidence:
- evidence/vip-failover-rto.log

## 2. Kafka Broker Failure

Architecture:
- Apache Kafka KRaft
- 3 combined broker/controller nodes
- Replication Factor: 3
- min.insync.replicas: 2
- Producer configured with acks=all

Test:
- Failure of broker hosting a partition leader
- Leader reassignment
- Producer and Consumer continuity
- ISR recovery

Result: PASS

Partition 0 leader changed from broker 1 to broker 2.
Producer and Consumer continued processing messages.
All replicas returned to ISR after recovery.

Operator observation: connectivity was available again on the next manual check.

Evidence:
- evidence/kafka-topic-before-failure.txt
- evidence/kafka-topic-during-failure.txt
- evidence/kafka-topic-after-recovery.txt
- evidence/kafka-producer-during-failure.txt
- evidence/kafka-consumer-during-failure.txt

## 3. Vault Active Node Failure

Architecture:
- 3 Vault nodes
- Integrated Raft storage
- Shamir Seal (3-of-5)
- Kubernetes Authentication

Test:
- Eviction of active vault-0 through Kubernetes Eviction API
- Automatic election of vault-1 as new Active
- Continuous Producer traffic
- Consumer processing verification
- Manual unseal of recovered vault-0

Result: PASS

Observed leader-switch detection: approximately 6.98 seconds.
Measured interval: eviction request to observation of the new active node.
The recorded duration is 6,975,533,077 ns, approximately 6.98 seconds.
Producer: 39 successful HTTP 201 responses out of 40.
One HTTP 503 was observed during failover.

Consumer processing continued after leader failover.

Final recovery state:
- vault-0: standby, unsealed
- vault-1: active, unsealed
- vault-2: standby, unsealed
- StatefulSet: 3/3 Ready
- Raft Committed Index: 6105 on all nodes
- Raft Applied Index: 6105 on all nodes



Evidence:
- evidence/reliability/vault-failover-20261015T091552Z/

## 4. Security and tracing

Kafka TLS authentication checks recorded rejection of a client without a
certificate and successful metadata access for the producer and consumer
certificates. See `evidence/security/kafka-tls-auth-20261013.txt`.

`evidence/tracing/jaeger-end-to-end.json` contains producer and consumer spans
with trace ID `b05f49b3b8a7b2e61e356817edeb1c11`. The consumer parent points to
the producer span. Recorded producer-start to consumer-end time for that event
is approximately 114.32 ms, on partition 2 at offset 14.
