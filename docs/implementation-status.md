# 実装状況

設計書の実装順序に対する現在地:

1. **Broker** — 実装済み。policy、resource registry、redaction、aggregate result limit、audit、kill switch、永続化された budget / circuit breaker、verification を含む。
2. **Approval** — 初期実装済み。operation hash、expiry、nonce、署名、TOCTOU 用 before hash、再起動後も有効な nonce store を含む。
3. **Regression Test Harness** — 8 種類の fixture 定義と安全性テストを実装済み。benchmark の真値・fixture 名・scenario 別 allow/deny は model prompt から分離した。Docker実行fixtureの初期3ケースも追加済み。
4. **Tool API** — Python の型付き API、JSON-facing adapter、`schemas/tool-request.schema.json` を実装済み。
5. **Dummy Agent** — LLMなしの固定 playbook で Broker を検証できる。
   Incident の構造化 state store（SQLite）も実装済み。
6. **Local LLM** — Q4_K_M GGUF の初期3モデルを取得済み。Broker `TOOL_SPECS` からOpenAI function schemaを生成し、同一 `tools` / `tool_choice` / `max_tokens=384` をCUDA対応llama.cppへ渡す評価 runnerを追加済み。各GGUFのchat templateはllama.cpp Jinjaに任せ、モデルごとに起動・測定・アンロードした。旧結果は `evaluation/results-v1.json` / `evaluation/results-v2.json`、function-calling再評価は `evaluation/results-v3.json`。
7. **Docker fixture** — disposable busybox containerを使う `service_restart`、`docker_restart`、`log_rotate` の3ケースで、実Brokerのassessment → guard → intent audit → executor → result audit → verification → postcheckを実行済み。`evaluation/fixture-results-v1.json` の Incident Resolution Rate は 1.0。
8. **Hermes** — 未接続。Broker API に依存しない adapter を追加する。
9. **Gateway** — 未接続。Conversation Plane と Approval Plane を分けた gateway を追加する。
10. **Autonomous Remediation** — 未有効化。L1 でも ARMED、allowlist、budget、circuit、verification の全条件が必要。

## v2 で追加した評価境界

- model prompt は `incident-001` 形式の opaque ID、symptom、observations のみ。Tool surfaceはBroker生成のfunction schemaとして別送する。
- `evaluation/adapters/` が Sabakan JSON、OpenAI/llama.cpp `tool_calls`、LFM native marker を Canonical Proposal に変換する。
- `envelope_valid`、`tool_name_valid`、`tool_arguments_valid`、`resource_valid`、`broker_acceptance` を分離し、後者は実 Broker の schema / policy を通す。
- `approval_required` は本番 proposal に含めず、Broker の `requires_approval` を診断結果として記録する。
- synthetic benchmark は diagnosis / plan / Broker acceptance の評価であり、executor を実行しない。Docker fixtureは実executor/postcheckまで測定する。

## 次の実装候補

- `ops-agentd` の forced-command / authenticated RPC executor
- VM-backed fixture、`config_patch`を含む承認経路、残りの診断ケースのpostcheck
- v3 function-calling benchmarkを基準にしたモデル選定と、残りの実サーバー相当execution fixture追加
- Hermes adapter と Discord gateway（Approval を会話 plane から分離）
