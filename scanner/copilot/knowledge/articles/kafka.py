"""Apache Kafka knowledge articles."""

from .. import KnowledgeArticle, KnowledgeCategory

KAFKA_ARTICLES = [
    KnowledgeArticle(
        id="kafka-consumer-lag",
        title="Fixing Kafka Consumer Lag",
        category=KnowledgeCategory.TROUBLESHOOTING,
        tags=["kafka", "consumer", "lag", "throughput", "partitions", "scaling"],
        tools=[],
        summary="How to diagnose and fix Kafka consumer lag: scaling consumers, tuning batch sizes, and partition rebalancing.",
        content="""## Fixing Kafka Consumer Lag

### What Is Consumer Lag?
Consumer lag = difference between the latest offset produced and the latest offset consumed.
Growing lag means consumers can't keep up with producers.

### Diagnosing
- **Kafka CLI**: `kafka-consumer-groups --describe --group <group>`
- **Monitoring**: Check lag metrics in your monitoring tool (Prometheus, Datadog, Confluent Cloud)
- **Per-partition**: Lag may be uneven if partitions have different volumes

### Common Causes and Fixes

**1. Not Enough Consumers**
- Consumers < partitions means some consumers handle multiple partitions
- Fix: Scale consumers up to partition count (max 1 consumer per partition per group)
- Long-term: Increase partition count if needed

**2. Slow Processing**
- Consumer processing takes too long per message
- Fix: Optimize processing logic, use async processing, batch operations
- Increase `max.poll.records` for batch processing efficiency
- Increase `max.poll.interval.ms` to prevent unnecessary rebalancing

**3. Large Messages**
- Messages too large, slow to deserialize
- Fix: Use compression (snappy/lz4), reduce message size, use schema references

**4. Frequent Rebalancing**
- Consumer group keeps rebalancing (check logs for "rebalance" messages)
- Fix: Increase `session.timeout.ms` and `heartbeat.interval.ms`
- Use static group membership: `group.instance.id` to prevent rebalance on restart

### Key Consumer Configs
```properties
max.poll.records=500          # Records per poll (increase for throughput)
max.poll.interval.ms=300000   # Max time between polls (increase for slow processing)
fetch.min.bytes=1048576       # Batch fetching (1MB minimum)
session.timeout.ms=45000      # Time before consumer considered dead
```
""",
    ),
    KnowledgeArticle(
        id="kafka-offset-errors",
        title="Kafka Offset Management Issues",
        category=KnowledgeCategory.TROUBLESHOOTING,
        tags=["kafka", "offset", "commit", "reset", "reprocessing", "exactly-once"],
        tools=[],
        summary="How to handle Kafka offset issues: offset out of range, auto-commit problems, manual offset management, and reprocessing.",
        content="""## Kafka Offset Management Issues

### "Offset Out of Range"
- Consumer tries to read from an offset that no longer exists (data expired)
- Fix: Set `auto.offset.reset=latest` (skip to newest) or `=earliest` (read from start)
- Prevention: Ensure `retention.ms` is long enough for your consumer to keep up

### Auto-Commit Issues
- Default: `enable.auto.commit=true`, commits every 5 seconds
- Problem: If consumer crashes between commit and processing, messages are skipped
- Fix for at-least-once: Disable auto-commit, commit after processing:
```python
consumer = KafkaConsumer(..., enable_auto_commit=False)
for msg in consumer:
    process(msg)
    consumer.commit()
```

### Manual Offset Reset
- Reset consumer group to specific offset:
```bash
kafka-consumer-groups --reset-offsets --to-earliest --group my-group --topic my-topic --execute
```
- Options: `--to-earliest`, `--to-latest`, `--to-datetime`, `--to-offset`

### Reprocessing Data
1. Stop all consumers in the group
2. Reset offsets to desired position
3. Restart consumers
4. Ensure processing is idempotent (can handle duplicates)

### Exactly-Once Semantics
- Enable with: `enable.idempotence=true` + `transactional.id` on producer
- Consumer must read committed: `isolation.level=read_committed`
- Requires Kafka 0.11+ and careful application design
""",
    ),
    KnowledgeArticle(
        id="kafka-schema-registry",
        title="Kafka Schema Registry Best Practices",
        category=KnowledgeCategory.BEST_PRACTICES,
        tags=["kafka", "schema-registry", "avro", "protobuf", "compatibility", "evolution"],
        tools=[],
        summary="Best practices for Kafka Schema Registry: schema evolution, compatibility modes, and avoiding breaking changes.",
        content="""## Kafka Schema Registry Best Practices

### Why Schema Registry?
- Enforce data contracts between producers and consumers
- Schema evolution without breaking consumers
- Avro/Protobuf/JSON Schema support

### Compatibility Modes
| Mode | Can Add Fields? | Can Remove Fields? | Can Change Types? |
|------|-----------------|-------------------|-------------------|
| BACKWARD | Yes (with default) | Yes | No |
| FORWARD | Yes | Yes (with default) | No |
| FULL | Yes (with default) | Yes (with default) | No |
| NONE | Anything goes | Anything goes | Yes |

### Recommended: BACKWARD Compatibility
- Default in Confluent Schema Registry
- New consumers can read old data
- Adding a field: Must have a default value
- Removing a field: Allowed (old consumers ignore missing fields)

### Schema Evolution Rules
1. **Always add defaults** to new fields
2. **Never remove required fields** without default
3. **Never change field types** (int → string)
4. **Never rename fields** (add new, deprecate old)
5. **Use optional/nullable** fields where possible

### Integration with Data Pipelines
- Fivetran/Airbyte read Avro schemas automatically
- dbt can reference schema registry for type information
- Kafka Connect uses schemas for sink transformations
""",
    ),
]
