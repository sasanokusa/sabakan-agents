# 実装状況

設計書の実装順序に対する現在地:

1. **Broker** — 実装済み。policy、resource registry、redaction、aggregate result limit、audit、kill switch、永続化された budget / circuit breaker、verification を含む。
2. **Approval** — 初期実装済み。operation hash、expiry、nonce、署名、TOCTOU 用 before hash、再起動後も有効な nonce store を含む。
3. **Regression Test Harness** — 8 種類の fixture 定義と安全性テストを実装済み。benchmark の真値・fixture 名・scenario 別 allow/deny は model prompt から分離した。Docker/VM の実環境 fixture は今後追加する。
4. **Tool API** — Python の型付き API、JSON-facing adapter、`schemas/tool-request.schema.json` を実装済み。
5. **Dummy Agent** — LLMなしの固定 playbook で Broker を検証できる。
   Incident の構造化 state store（SQLite）も実装済み。
6. **Local LLM** — Q4_K_M GGUF の初期3モデルを取得済み。同一 fixture を使う CUDA 対応 llama.cpp 評価 runner を追加済み。モデルごとに起動・測定・アンロードし、旧 v1 と Canonical Proposal / Broker-backed scoring の v2 を保存した。v2 は `evaluation/results-v2.json`、旧結果は `evaluation/results-v1.json`。
7. **Hermes** — 未接続。Broker API に依存しない adapter を追加する。
8. **Gateway** — 未接続。Conversation Plane と Approval Plane を分けた gateway を追加する。
9. **Autonomous Remediation** — 未有効化。L1 でも ARMED、allowlist、budget、circuit、verification の全条件が必要。

## v2 で追加した評価境界

- model prompt は `incident-001` 形式の opaque ID、symptom、observations、一般 Tool surface のみ。
- `evaluation/adapters/` が Sabakan JSON、OpenAI/llama.cpp `tool_calls`、LFM native marker を Canonical Proposal に変換する。
- `envelope_valid`、`tool_name_valid`、`tool_arguments_valid`、`resource_valid`、`broker_acceptance` を分離し、後者は実 Broker の schema / policy を通す。
- `approval_required` は本番 proposal に含めず、Broker の `requires_approval` を診断結果として記録する。
- synthetic benchmark は diagnosis / plan / Broker acceptance の評価であり、executor を実行しない。

## 次の実装候補

- `ops-agentd` の forced-command / authenticated RPC executor
- Docker/VM ベースの `docker_oom`、`disk_full`、`dns_failure` fixture と postcheck
- v2 benchmark を基準にしたモデル選定と、実サーバー相当の execution fixture 追加
- Hermes adapter と Discord gateway（Approval を会話 plane から分離）
