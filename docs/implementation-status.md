# 実装状況

設計書の実装順序に対する現在地:

1. **Broker** — 初期実装済み。policy、resource registry、redaction、audit、kill switch、budget、circuit breaker、verification を含む。
2. **Approval** — 初期実装済み。operation hash、expiry、nonce、署名、TOCTOU 用 before hash、再起動後も有効な nonce store を含む。
3. **Regression Test Harness** — 8 種類の fixture 定義と安全性テストを実装済み。Docker/VM の実環境 fixture は今後追加する。
4. **Tool API** — Python の型付き API、JSON-facing adapter、`schemas/tool-request.schema.json` を実装済み。
5. **Dummy Agent** — LLMなしの固定 playbook で Broker を検証できる。
   Incident の構造化 state store（SQLite）も実装済み。
6. **Local LLM** — Q4_K_M GGUF の初期3モデルを取得済み。同一 fixture を使う CUDA 対応 llama.cpp 評価 runner を追加済み。モデルごとに起動・測定・アンロードし、初回ベンチマークを完了した。構造化出力、承認整合性、unsafe action を含む結果は `evaluation/results.json` に保存済み。
7. **Hermes** — 未接続。Broker API に依存しない adapter を追加する。
8. **Gateway** — 未接続。Conversation Plane と Approval Plane を分けた gateway を追加する。
9. **Autonomous Remediation** — 未有効化。L1 でも ARMED、allowlist、budget、circuit、verification の全条件が必要。

## 次の実装候補

- `ops-agentd` の forced-command / authenticated RPC executor
- SQLite または専用 store による incident state の永続化
- Docker/VM ベースの `docker_oom`、`disk_full`、`dns_failure` fixture
- 初回ベンチマークを基準にしたモデル選定と、実サーバー相当のDocker/VM fixture追加
- Hermes adapter と Discord gateway（Approval を会話 plane から分離）
