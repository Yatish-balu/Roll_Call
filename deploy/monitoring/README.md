# Monitoring and alerting (Person 2, Phase 4)

The application already emits structured security events through
`app/security/events.py`. Set `SECURITY_EVENT_LOG_FILE` to an append-only JSONL
file and ship it to your log platform. Every line is one JSON object with
`timestamp`, `event_type`, `severity`, `outcome`, `actor_id`, `ip_address`,
`request_id` and redacted `details`.

## Minimum alerts

| Alert | Condition | Severity | Why |
| --- | --- | --- | --- |
| Authentication failures | `event_type=auth_login` and `outcome=failure` > 20 in 5 min for one IP | High | brute force / credential stuffing |
| Access denied spike | `event_type=access_denied` > 10 in 10 min for one actor or IP | High | enumeration or privilege probing |
| Prompt injection blocked | any `event_type=prompt_injection_blocked` | Medium | active AI abuse |
| Embedded instruction | any `event_type=embedded_instruction_detected` | Medium | malicious upload attempt |
| Upload rejected | `event_type=upload_rejected` with `reason=malware_detected` | Critical | malware upload |
| Scanner unavailable | `event_type=upload_scanner_unavailable` | Medium | degraded upload protection |
| Rate limit triggered | `event_type=rate_limit_triggered` > 50 in 5 min | Medium | abuse or broken client |
| 5xx spike | `/health` failing or 5xx ratio > 5% for 5 min | High | availability incident |
| Certificate expiry | TLS certificate < 14 days | High | HTTPS outage risk |
| Backup failure | backup job did not create an archive in 24 h | High | recovery risk |

## Suggested stack

* **Logs**: Loki + Promtail (see `promtail-config.yml`) or your cloud provider's
  log service. Use the JSON fields as labels, never the raw request body.
* **Metrics/uptime**: any black-box monitor against `https://app.example.com/health`
  every 30-60 seconds.
* **Alert routing**: page on Critical/High, ticket on Medium, weekly review for Low.
* **Retention**: keep security events at least 90 days (or per your policy).

## Privacy

Security events already redact passwords, tokens, API keys and large binary
payloads. Do not add raw chat text, uploaded file contents or full student
records to alert payloads. Use `safe_excerpt` (bounded) when an excerpt is
genuinely needed.
