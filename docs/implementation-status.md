# 実装状況

研究目的・脅威モデル・評価仕様・実験の優先順位は [研究設計・評価方針](research-design.md) を参照してください。
本書は現行実装の記録であり、研究設計に定めた改善を実装済みとするものではありません。

現行実装の現在地:

1. **Broker** — 実装済み。policy、resource registry、redaction、aggregate result limit、audit、kill switch、永続化された budget / circuit breaker、verification を含む。
2. **Approval** — 初期実装済み。operation hash、expiry、nonce、署名、TOCTOU 用 before hash、再起動後も有効な nonce store を含む。
3. **Regression Test Harness** — 8 種類の fixture 定義と安全性テストを実装済み。benchmark の真値・fixture 名・scenario 別 allow/deny は model prompt から分離した。Docker実行fixtureの v2 5ケースも追加済み。
4. **Tool API** — Python の型付き API、JSON-facing adapter、`schemas/tool-request.schema.json` を実装済み。
5. **Dummy Agent** — LLMなしの固定 playbook で Broker を検証できる。
   Incident の構造化 state store（SQLite）も実装済み。
6. **Local LLM** — Q4_K_M GGUF の初期3モデルを取得済み。Broker `TOOL_SPECS` からOpenAI function schemaを生成し、同一 `tools` / `tool_choice` / `max_tokens=384` をCUDA対応llama.cppへ渡す評価 runnerを追加済み。各GGUFのchat templateはllama.cpp Jinjaに任せ、モデルごとに起動・測定・アンロードした。旧結果は `evaluation/results-v1.json` / `evaluation/results-v2.json`、function-calling再評価は `evaluation/results-v3.json`、multi-turn v2は `evaluation/agent-loop-results-v2.json`。
7. **Docker fixture / agent loop** — disposable busybox containerを使う `service_restart`、`docker_restart`、`log_rotate`、disposable managed configの `config_patch`、malicious log の5ケースについて、実Brokerのassessment → guard → intent audit → executor → result audit → verification → postcheckをmulti-turn LLM loopへ接続した。`sabakan-agent-loop-v2` は schema/resource/policy/unsafe/dangerous proposal と unsafe execution を分離し、Read結果をBroker経由で次turnへ渡す。現行v2は変更実行後のhealth restoredを成功として全5ケースを集計する。ただし、内訳は復旧必要4ケースと復旧不要のmalicious log 1ケースであり、この混合集計を研究用の障害復旧率としては使わない。OOM/disk pressure は `simulated` fidelity として記録し、L2は Conversation Plane と trusted Approval Plane を分離して exact-operation、replay、expiry、principal、TOCTOU、rollback を検証する。実測traceとモデル別metricsは `evaluation/agent-loop-results-v2.json` に保存する。固定proposalだけの `evaluation/fixture-results-v2.json` はBroker fixture単体の基準として別に保持する。
8. **Hermes** — 未接続。Broker API に依存しない adapter を追加する。
9. **Gateway** — 未接続。Conversation Plane と Approval Plane を分けた gateway を追加する。
10. **Autonomous Remediation** — 未有効化。L1 でも ARMED、allowlist、budget、circuit、verification の全条件が必要。

## v2 で追加した評価境界

- model prompt は `incident-001` 形式の opaque ID、symptom、observations のみ。Tool surfaceはBroker生成のfunction schemaとして別送する。
- `evaluation/adapters/` が Sabakan JSON、OpenAI/llama.cpp `tool_calls`、LFM native marker を Canonical Proposal に変換する。
- `envelope_valid`、`tool_name_valid`、`tool_arguments_valid`、`resource_valid`、`broker_acceptance` を分離し、後者は実 Broker の schema / policy を通す。
- `approval_required` は本番 proposal に含めず、Broker の `requires_approval` を診断結果として記録する。
- synthetic benchmark は diagnosis / plan / Broker acceptance の評価であり、executor を実行しない。Docker fixtureは実executor/postcheckまで測定する。
- multi-turn agent loopは初期観測時にRead-only schema、Read成功後にL1およびL2 `config_patch` を含むremediation schemaを公開する。許可・承認・実行は公開schemaではなく、常にBroker policy/guardが決める。

## 評価上の既知の制約

- 現行v2の成功判定は `mutation_verified` を必要とするため、適切な非介入を成功として評価できない。復旧・非介入・攻撃対応を分離する仕様は [研究設計・評価方針](research-design.md) に定義したが、実装と再集計は未実施。
- `unsafe_execution_rate` は、危険と分類された提案に由来する変更実行件数を全提案件数で割った現行指標であり、情報漏えいや許可済み操作の運用上の悪影響まで網羅する指標ではない。
- `security_invariants` の固定 `True` は設計上の宣言と区別する必要がある。未計測・例外終了を違反0件として扱わず、独立した観測に基づく評価へ改める。
- 現行の平均復旧時間には失敗終了時間も含まれる。成功時の復旧時間、失敗・打切り時間、承認待ちを分離して報告する。
- 既存の結果JSONは旧protocolの測定記録として保持する。新仕様に基づく結果は別protocol・別ファイルで作成し、旧結果を無断で上書きしない。

## 次の実装順序

1. **P0: 評価の正解と分母の修正** — 復旧必要／非介入／攻撃シナリオ、終了結果、独立した正解判定、危険実行の計測範囲、復旧時間を整理する。回帰テストと旧traceの再採点可能性の確認を先に行う。
2. **P1: 非介入・安全性・誤拒否の対照評価** — 正常系、不要再起動、許可済み操作の悪影響、攻撃有無の対、正当要求の誤拒否を評価する。失敗を全体の安全性の証明に置き換えない。
3. **P2: 比較実験** — 同じ観測・権限を使う固定playbook、同一モデルでの最小／提案ハーネス、単一機構ablationを比較する。開発用と未使用の評価用ケースを分け、複数回試行と再現条件を記録する。
4. **P3: 障害とpostcheckの現実性の向上** — まずDockerで実際のサービス応答・書込み成否などを検証する。systemdやOSレベルの検証が必要なケースに限定してVM fixtureを追加する。

`ops-agentd` の forced-command / authenticated RPC、Hermes adapter、Discord gateway は後段の拡張候補として維持する。研究上の比較・評価を先に成立させ、接続先や機能の増加を研究成果の代替としない。
