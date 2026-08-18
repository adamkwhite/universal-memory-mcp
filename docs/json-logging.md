# JSON Logging Documentation

## Overview

Claude Memory MCP supports structured JSON logging for production environments, enabling seamless integration with log aggregation platforms like Datadog, ELK (Elasticsearch, Logstash, Kibana), and CloudWatch.

**Key Features:**
- **Newline-delimited JSON (NDJSON)** - One JSON object per line for streaming compatibility
- **Structured context fields** - Machine-parseable metadata for filtering and analysis
- **Security-first** - All sanitization and redaction features work in JSON mode
- **Backward compatible** - Defaults to text format, no breaking changes
- **Performance optimized** - Minimal overhead compared to text logging

## Quick Start

### Enable JSON Logging

```bash
# Set environment variable before starting the MCP server
export CLAUDE_MCP_LOG_FORMAT=json

# Start the server
python src/universal_memory_mcp/server_fastmcp.py
```

### Verify JSON Output

```bash
# View JSON logs
tail -f ~/.claude-memory/logs/claude-mcp.log

# Parse JSON logs with jq
tail -f ~/.claude-memory/logs/claude-mcp.log | jq '.'

# Filter by log level
tail -f ~/.claude-memory/logs/claude-mcp.log | jq 'select(.level == "ERROR")'

# Filter by context type
tail -f ~/.claude-memory/logs/claude-mcp.log | jq 'select(.context.type == "performance")'
```

## JSON Schema Specification

### Standard Fields (Always Present)

All log entries include these standard fields:

| Field | Type | Description | Example |
|-------|------|-------------|---------|
| `timestamp` | string | ISO 8601 timestamp | `"2025-01-15T10:30:45"` |
| `level` | string | Log level | `"INFO"`, `"WARNING"`, `"ERROR"` |
| `logger` | string | Logger name | `"claude_memory_mcp"` |
| `function` | string | Function name | `"add_conversation"` |
| `line` | integer | Line number | `145` |
| `message` | string | Human-readable message | `"Added conversation successfully"` |

### Context Field (Optional)

The `context` field contains structured metadata specific to each log type:

```json
{
  "timestamp": "2025-01-15T10:30:45",
  "level": "INFO",
  "logger": "claude_memory_mcp",
  "function": "search_conversations",
  "line": 212,
  "message": "Performance: search_conversations completed in 0.045s",
  "context": {
    "type": "performance",
    "duration_seconds": 0.045,
    "query": "python tutorial",
    "results_count": 15
  }
}
```

## Log Types and Examples

### 1. Performance Logs

**Context Structure:**
```json
{
  "type": "performance",
  "duration_seconds": 0.123,
  "metric_name": "value",
  ...
}
```

**Example:**
```json
{
  "timestamp": "2025-01-15T10:30:45",
  "level": "INFO",
  "logger": "claude_memory_mcp",
  "function": "search_conversations",
  "line": 212,
  "message": "Performance: search_conversations completed in 0.045s | query_count=5, cache_hits=3",
  "context": {
    "type": "performance",
    "duration_seconds": 0.045,
    "query_count": 5,
    "cache_hits": 3
  }
}
```

**Use Cases:**
- Performance monitoring and SLA tracking
- Identifying slow operations
- Optimization opportunities

### 2. Security Event Logs

**Context Structure:**
```json
{
  "type": "security",
  "event_type": "event_name",
  "severity": "WARNING",
  "details": "sanitized description"
}
```

**Example:**
```json
{
  "timestamp": "2025-01-15T10:30:45",
  "level": "WARNING",
  "logger": "claude_memory_mcp.security",
  "function": "validate_path",
  "line": 78,
  "message": "Security Event: path_traversal_attempt | Blocked path: <redacted_path>",
  "context": {
    "type": "security",
    "event_type": "path_traversal_attempt",
    "severity": "WARNING",
    "details": "Blocked path: <redacted_path>"
  }
}
```

**Security Features:**
- Automatic path redaction for sensitive file paths
- Control character sanitization to prevent log injection
- Details field is always sanitized

**Use Cases:**
- Security monitoring and threat detection
- Automated alerting on suspicious activities
- Compliance and audit logging

### 3. Validation Failure Logs

**Context Structure:**
```json
{
  "type": "validation",
  "field": "field_name",
  "value": "sanitized_value (truncated to 100 chars)",
  "reason": "failure_reason"
}
```

**Example:**
```json
{
  "timestamp": "2025-01-15T10:30:45",
  "level": "WARNING",
  "logger": "claude_memory_mcp.validation",
  "function": "validate_input",
  "line": 45,
  "message": "Validation failed: conversation_id='invalid\\nid' | Reason: Contains control characters",
  "context": {
    "type": "validation",
    "field": "conversation_id",
    "value": "invalid\\nid",
    "reason": "Contains control characters"
  }
}
```

**Sanitization Features:**
- Control characters removed or escaped
- Values truncated to 100 characters
- Newlines and carriage returns escaped for visibility

**Use Cases:**
- Input validation monitoring
- Detecting malformed API requests
- Security analysis for injection attempts

### 4. File Operation Logs

**Context Structure:**
```json
{
  "type": "file_operation",
  "operation": "read|write|delete|...",
  "path": "relative_or_redacted_path",
  "success": true,
  "custom_details": "..."
}
```

**Example:**
```json
{
  "timestamp": "2025-01-15T10:30:45",
  "level": "INFO",
  "logger": "claude_memory_mcp.files",
  "function": "save_conversation",
  "line": 189,
  "message": "File write: conversations/2025/01-january/conversation.md | SUCCESS | size_bytes=2048, duration_ms=12",
  "context": {
    "type": "file_operation",
    "operation": "write",
    "path": "conversations/2025/01-january/conversation.md",
    "success": true,
    "size_bytes": "2048",
    "duration_ms": "12"
  }
}
```

**Path Handling:**
- Absolute paths converted to relative paths when possible
- Sensitive paths outside home directory are redacted

**Use Cases:**
- File system activity monitoring
- Storage usage tracking
- Debugging file access issues

### 5. Function Call Logs

**Context Structure:**
```json
{
  "type": "function_call",
  "function": "function_name",
  "params": {
    "param1": "value1",
    "param2": 42
  }
}
```

**Example:**
```json
{
  "timestamp": "2025-01-15T10:30:45",
  "level": "DEBUG",
  "logger": "claude_memory_mcp",
  "function": "add_conversation",
  "line": 123,
  "message": "Calling add_conversation(conversation_id=conv_123, title=Python Tutorial)",
  "context": {
    "type": "function_call",
    "function": "add_conversation",
    "params": {
      "conversation_id": "conv_123",
      "title": "Python Tutorial",
      "content": "..."
    }
  }
}
```

**Use Cases:**
- Detailed debugging and tracing
- API call monitoring
- Understanding execution flow

## Migration Guide

### Switching from Text to JSON Format

#### Step 1: Update Environment Configuration

**For systemd services:**
```ini
# /etc/systemd/system/claude-memory-mcp.service
[Service]
Environment="CLAUDE_MCP_LOG_FORMAT=json"
```

**For Docker containers:**
```yaml
# docker-compose.yml
services:
  claude-memory-mcp:
    environment:
      - CLAUDE_MCP_LOG_FORMAT=json
```

**For manual deployment:**
```bash
# Add to ~/.bashrc or ~/.zshrc
export CLAUDE_MCP_LOG_FORMAT=json
```

#### Step 2: Restart the MCP Server

```bash
# Systemd
sudo systemctl restart claude-memory-mcp

# Docker
docker-compose restart

# Manual
# Kill and restart the Python process
```

#### Step 3: Verify JSON Output

```bash
# Check that logs are in JSON format
tail -n 1 ~/.claude-memory/logs/claude-mcp.log | jq '.'

# Should output pretty-printed JSON
```

#### Step 4: Update Log Aggregation Configuration

Configure your log aggregation platform to parse JSON logs (see Integration Examples below).

### Rollback to Text Format

Simply remove or change the environment variable:

```bash
# Remove the environment variable
unset CLAUDE_MCP_LOG_FORMAT

# Or explicitly set to text
export CLAUDE_MCP_LOG_FORMAT=text
```

Restart the MCP server, and logs will revert to human-readable text format.

## Integration Examples

### Datadog

**Datadog Agent Configuration** (`/etc/datadog-agent/conf.d/python.d/conf.yaml`):

```yaml
logs:
  - type: file
    path: /home/user/.claude-memory/logs/claude-mcp.log
    service: claude-memory-mcp
    source: python
    sourcecategory: sourcecode
    # JSON auto-parsing enabled by default for JSON lines
```

**Querying in Datadog:**
```
source:python service:claude-memory-mcp @context.type:performance @context.duration_seconds:>1
```

**Creating Monitors:**
```
Alert when:
@context.type:security AND @level:ERROR
```

### ELK Stack (Elasticsearch, Logstash, Kibana)

**Logstash Configuration** (`logstash.conf`):

```ruby
input {
  file {
    path => "/home/user/.claude-memory/logs/claude-mcp.log"
    start_position => "beginning"
    codec => json
  }
}

filter {
  # JSON is already parsed by the json codec

  # Add custom fields
  mutate {
    add_field => { "service" => "claude-memory-mcp" }
  }

  # Convert timestamp to @timestamp
  date {
    match => [ "timestamp", "ISO8601" ]
    target => "@timestamp"
  }
}

output {
  elasticsearch {
    hosts => ["localhost:9200"]
    index => "claude-memory-mcp-%{+YYYY.MM.dd}"
  }
}
```

**Kibana Query Examples:**
```
# Find slow operations
context.type:performance AND context.duration_seconds:>0.5

# Security events
context.type:security AND level:WARNING

# Failed validations
context.type:validation
```

### AWS CloudWatch

**CloudWatch Agent Configuration** (`amazon-cloudwatch-agent.json`):

```json
{
  "logs": {
    "logs_collected": {
      "files": {
        "collect_list": [
          {
            "file_path": "/home/user/.claude-memory/logs/claude-mcp.log",
            "log_group_name": "/aws/claude-memory-mcp",
            "log_stream_name": "{instance_id}/application",
            "timezone": "UTC"
          }
        ]
      }
    },
    "log_stream_name": "{instance_id}/application"
  }
}
```

**CloudWatch Insights Queries:**
```sql
-- Find performance issues
fields @timestamp, message, context.duration_seconds
| filter context.type = "performance"
| sort context.duration_seconds desc
| limit 20

-- Security events by type
fields @timestamp, context.event_type, context.severity
| filter context.type = "security"
| stats count() by context.event_type

-- Error rate by function
fields @timestamp, function, level
| filter level = "ERROR"
| stats count() by function
| sort count desc
```

### Splunk

**Splunk Forwarder Configuration** (`inputs.conf`):

```ini
[monitor:///home/user/.claude-memory/logs/claude-mcp.log]
disabled = false
sourcetype = _json
source = claude-memory-mcp
index = main
```

**Splunk Search Examples:**
```spl
# Performance analysis
sourcetype=_json context.type=performance
| stats avg(context.duration_seconds) p95(context.duration_seconds) by function

# Security dashboard
sourcetype=_json context.type=security
| timechart count by context.event_type

# Error investigation
sourcetype=_json level=ERROR
| table _time, function, message, context.*
```

## Troubleshooting

### Issue: Logs are still in text format after setting environment variable

**Cause:** Environment variable not loaded by the process.

**Solutions:**
1. Verify the environment variable is set in the same shell where the server runs:
   ```bash
   echo $CLAUDE_MCP_LOG_FORMAT
   ```

2. For systemd services, ensure the `Environment` directive is in the `[Service]` section:
   ```bash
   systemctl show claude-memory-mcp | grep CLAUDE_MCP_LOG_FORMAT
   ```

3. Restart the MCP server after setting the variable:
   ```bash
   sudo systemctl restart claude-memory-mcp
   ```

### Issue: JSON parsing errors in log aggregation platform

**Cause:** Multi-line JSON or invalid JSON structure.

**Solutions:**
1. Verify each log line is valid JSON:
   ```bash
   tail -n 10 ~/.claude-memory/logs/claude-mcp.log | while read line; do echo "$line" | jq '.' || echo "Invalid JSON: $line"; done
   ```

2. Check for non-serializable objects causing fallback to string representation:
   ```bash
   grep '"context": "' ~/.claude-memory/logs/claude-mcp.log
   ```

   If found, this indicates non-serializable objects. The formatter handles this gracefully by converting to strings.

3. Ensure your log aggregation platform is configured for newline-delimited JSON (NDJSON).

### Issue: Missing context field in some log entries

**Cause:** Not all log entries include context (only specialized logging functions add it).

**Solutions:**
- This is expected behavior. Only calls to `log_performance()`, `log_security_event()`, `log_validation_failure()`, `log_file_operation()`, and `log_function_call()` include structured context.
- Basic logging calls (`logger.info()`, `logger.error()`, etc.) without the `extra` parameter won't have context.
- Use filters in your log aggregation platform to handle both cases:
  ```
  # Datadog
  @context.type:* OR NOT @context:*

  # Elasticsearch
  exists:context.type OR NOT _exists_:context
  ```

### Issue: Performance degradation after enabling JSON logging

**Cause:** JSON serialization overhead.

**Solutions:**
1. Verify the overhead is within acceptable range (<5%):
   ```bash
   # Run performance benchmarks
   python tests/test_performance_benchmarks.py
   ```

2. Reduce logging verbosity if necessary:
   ```bash
   export CLAUDE_MCP_LOG_LEVEL=INFO  # Instead of DEBUG
   ```

3. Use log sampling for high-frequency operations (future enhancement - see issue #15).

### Issue: Sensitive data visible in JSON logs

**Cause:** Custom log calls not using sanitization functions.

**Solutions:**
1. Always use the specialized logging functions (`log_security_event()`, `log_validation_failure()`, etc.) which include built-in sanitization.

2. For custom logging with sensitive data, manually sanitize before logging:
   ```python
   import re
   from src.logging_config import CONTROL_CHAR_PATTERN

   safe_value = re.sub(CONTROL_CHAR_PATTERN, '', str(value))
   logger.info("Custom message", extra={"context": {"value": safe_value}})
   ```

3. Verify path redaction is working:
   ```bash
   grep '<redacted_path>' ~/.claude-memory/logs/claude-mcp.log
   ```

### Issue: Invalid environment variable value warning

**Symptom:** Warning message in logs: `"Invalid CLAUDE_MCP_LOG_FORMAT value: 'xyz'. Valid values are: json, text. Defaulting to 'text'."`

**Cause:** Typo or invalid value in `CLAUDE_MCP_LOG_FORMAT`.

**Solutions:**
1. Check the environment variable value:
   ```bash
   echo $CLAUDE_MCP_LOG_FORMAT
   ```

2. Set to a valid value (case-insensitive):
   ```bash
   export CLAUDE_MCP_LOG_FORMAT=json  # or text
   ```

3. Verify the fix:
   ```bash
   tail -f ~/.claude-memory/logs/claude-mcp.log
   # Should not show the warning anymore
   ```

## Best Practices

### 1. Use JSON Format in Production

**Why:** Structured logs enable automated monitoring, alerting, and analysis.

```bash
# Production environment
export CLAUDE_MCP_LOG_FORMAT=json
```

### 2. Keep Text Format for Development

**Why:** Human-readable logs are easier to scan during local development.

```bash
# Development environment
export CLAUDE_MCP_LOG_FORMAT=text  # or unset (default)
```

### 3. Use Context Fields for Rich Metadata

**Good Example:**
```python
log_performance(
    "search_conversations",
    duration=0.045,
    query_length=len(query),
    results_count=len(results),
    cache_used=True
)
```

**Bad Example:**
```python
logger.info(f"Search took {duration}s with {len(results)} results")
# No structured context for filtering/analysis
```

### 4. Monitor Log Volume

**Why:** JSON logs are slightly larger than text logs.

**How:**
```bash
# Monitor log file size
du -h ~/.claude-memory/logs/claude-mcp.log

# Monitor disk usage
df -h ~/.claude-memory/
```

### 5. Set Up Log Rotation

**Why:** Prevent disk space exhaustion.

**How:** The MCP server includes built-in log rotation (10MB per file, 5 backups). Verify it's working:

```bash
ls -lh ~/.claude-memory/logs/
# Should show:
# claude-mcp.log
# claude-mcp.log.1
# claude-mcp.log.2
# ...
```

### 6. Create Alerts for Critical Events

**Examples:**

**Datadog Monitor:**
```
Alert when:
@context.type:security AND @context.severity:CRITICAL
```

**CloudWatch Alarm:**
```sql
fields @timestamp, context.type, context.severity
| filter context.type = "security" and context.severity = "CRITICAL"
| stats count() as critical_events by bin(5m)
| filter critical_events > 0
```

**Splunk Alert:**
```spl
sourcetype=_json context.type=security context.severity=CRITICAL
| stats count
| where count > 0
```

## Advanced Usage

### Custom Context Fields

You can add custom context to any log entry using the `extra` parameter:

```python
from src.logging_config import get_logger

logger = get_logger()

custom_context = {
    "type": "custom",
    "user_id": user_id,
    "request_id": request_id,
    "feature_flags": {"new_search": True}
}

logger.info("Custom event", extra={"context": custom_context})
```

**Output:**
```json
{
  "timestamp": "2025-01-15T10:30:45",
  "level": "INFO",
  "logger": "claude_memory_mcp",
  "function": "custom_function",
  "line": 123,
  "message": "Custom event",
  "context": {
    "type": "custom",
    "user_id": "user_abc123",
    "request_id": "req_xyz789",
    "feature_flags": {
      "new_search": true
    }
  }
}
```

### Querying Nested Context Fields

**Datadog:**
```
@context.feature_flags.new_search:true
```

**Elasticsearch (Kibana):**
```
context.feature_flags.new_search:true
```

**CloudWatch Insights:**
```sql
fields @timestamp, message, context.feature_flags.new_search
| filter context.feature_flags.new_search = true
```

## Related Documentation

- **Environment Variables:** See `README.md` for complete list of configuration options
- **Performance Benchmarks:** See `tests/test_performance_benchmarks.py` for JSON vs text performance comparison
- **Security Features:** See `src/universal_memory_mcp/logging_config.py` for sanitization and redaction implementation
- **Related Issues:**
  - [Issue #52](https://github.com/adamkwhite/claude-memory-mcp/issues/52) - JSON Logging Implementation
  - [Issue #16](https://github.com/adamkwhite/claude-memory-mcp/issues/16) - Correlation IDs (future enhancement)
  - [Issue #15](https://github.com/adamkwhite/claude-memory-mcp/issues/15) - Log Sampling (future enhancement)

## Support

For issues or questions:
- Create a GitHub issue: [claude-memory-mcp/issues](https://github.com/adamkwhite/claude-memory-mcp/issues)
- Check existing issues: [Issue #52 (JSON Logging)](https://github.com/adamkwhite/claude-memory-mcp/issues/52)
