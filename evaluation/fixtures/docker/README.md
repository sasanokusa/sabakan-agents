# Docker execution fixtures

`scripts/run_docker_fixtures.py` creates disposable `busybox:latest` containers,
injects a stopped/unhealthy state, and submits a fixed typed proposal through
the real Broker. The result is counted as an Incident Resolution only when:

```text
proposal → Broker policy/schema/guard → executor → Broker verification → postcheck
```

completes and the fixture health condition is restored. Containers are removed
by exact generated names after each case. The first set covers `service_restart`,
`docker_restart`, and `log_rotate`; VM-backed fixtures and the remaining
configuration/diagnosis cases are subsequent work.
