# 実装状況

設計書の実装順序に対する現在地:

1. **Broker** — 実装済み。policy、resource registry、redaction、aggregate result limit、audit、kill switch、永続化された budget / circuit breaker、verification を含む。
2. **Approval** — 初期実装済み。operation hash、expiry、nonce、署名、TOCTOU 用 before hash、再起動後も有効な nonce store を含む。
3. **Regression Test Harness** — 8 種類の fixture 定義と安全性テストを実装済み。benchmark の真値・fixture 名・scenario 別 allow/deny は model prompt から分離した。Docker実行fixtureの v2 5ケースも追加済み。
4. **Tool API** — Python の型付き API、JSON-facing adapter、`schemas/tool-request.schema.json` を実装済み。
5. **Dummy Agent** — LLMなしの固定 playbook で Broker を検証できる。
   Incident の構造化 state store（SQLite）も実装済み。
6. **Local LLM** — Q4_K_M GGUF の初期3モデルを取得済み。Broker `TOOL_SPECS` からOpenAI function schemaを生成し、同一 `tools` / `tool_choice` / `max_tokens=384` をCUDA対応llama.cppへ渡す評価 runnerを追加済み。各GGUFのchat templateはllama.cpp Jinjaに任せ、モデルごとに起動・測定・アンロードした。旧結果は `evaluation/results-v1.json` / `evaluation/results-v2.json`、function-calling再評価は `evaluation/results-v3.json`、multi-turn v2は `evaluation/agent-loop-results-v2.json`。
7. **Docker fixture / agent loop** — disposable busybox containerを使う `service_restart`、`docker_restart`、`log_rotate`、disposable managed configの `config_patch`、malicious log の5ケースについて、実Brokerのassessment → guard → intent audit → executor → result audit → verification → postcheckをmulti-turn LLM loopへ接続した。`sabakan-agent-loop-v2` は schema/resource/policy/unsafe/dangerous proposal と unsafe execution を分離し、Read結果をBroker経由で次turnへ渡し、health restoredだけをIncident Resolution成功とする。OOM/disk pressure は `simulated` fidelity として記録し、L2は Conversation Plane と trusted Approval Plane を分離して exact-operation、replay、expiry、principal、TOCTOU、rollback を検証する。実測traceとモデル別metricsは `evaluation/agent-loop-results-v2.json` に保存する。固定proposalだけの `evaluation/fixture-results-v2.json` はBroker fixture単体の基準として別に保持する。
8. **Hermes** — 未接続。Broker API に依存しない adapter を追加する。
9. **Gateway** — 未接続。Conversation Plane と Approval Plane を分けた gateway を追加する。
10. **Autonomous Remediation** — 未有効化。L1 でも ARMED、allowlist、budget、circuit、verification の全条件が必要。

## v2 で追加した評価境界

- model prompt は `incident-001` 形式の opaque ID、symptom、observations のみ。Tool surfaceはBroker生成のfunction schemaとして別送する。
- `evaluation/adapters/` が Sabakan JSON、OpenAI/llama.cpp `tool_calls`、LFM native marker を Canonical Proposal に変換する。
- `envelope_valid`、`tool_name_valid`、`tool_arguments_valid`、`resource_valid`、`broker_acceptance` を分離し、後者は実 Broker の schema / policy を通す。
- `approval_required` は本番 proposal に含めず、Broker の `requires_approval` を診断結果として記録する。
- synthetic benchmark は diagnosis / plan / Broker acceptance の評価であり、executor を実行しない。Docker fixtureは実executor/postcheckまで測定する。
- multi-turn agent loopは初期観測時にRead-only schema、Read成功後にL1 schemaを公開する。許可・承認・実行は公開schemaではなく、常にBroker policy/guardが決める。

## 次の実装候補

- `ops-agentd` の forced-command / authenticated RPC executor
- VM-backed fixture、実filesystem full/OOMのreal fidelity、残りの診断ケースのpostcheck
- v3 function-calling benchmarkを基準にしたモデル選定と、残りの実サーバー相当execution fixture追加
- 3B/4Bモデルのagent-loop failure（Read-only loop、不要proposal）を減らすprompt/chat-template調整と、より現実的なDocker/VM health fixture
- Hermes adapter と Discord gateway（Approval を会話 plane から分離）
