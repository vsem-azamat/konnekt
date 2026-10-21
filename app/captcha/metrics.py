"""What happens to join captchas, for Prometheus: one counter, a few kinds."""

from __future__ import annotations

from prometheus_client import Counter

# sent, held, undelivered, retry, and every status a captcha settles in
# (passed, failed, expired, declined, gone). Never a chat or a person.
CAPTCHA_EVENTS = Counter("captcha_events_total", "Join captcha outcomes", ["event"])

# A series that first appears at 1 is invisible to `increase()`, so every one
# starts at 0.
for _event in ("sent", "retry", "held", "undelivered", "passed", "failed", "expired", "declined", "gone"):
    CAPTCHA_EVENTS.labels(event=_event)
