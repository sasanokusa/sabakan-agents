# 実装状況

## 2026-09-08の確認状況

Issue #18の追跡範囲に対する現在の証拠を以下にまとめる。開発比較・固定対照・主評価を区別し、過去記録を上書きしない。主評価開始前の全回帰は238 tests成功。開始後に追加した[解析器の検証](primary-analysis-implementation-20260908.md)は、固定した実行コードとは分けて記録する。

| 範囲 | 確認した内容 | 未完了・制約 |
| --- | --- | --- |
| #9/#10 条件比較 | [40行計画の中断と欠測解析](availability-ablation-interruption-20260908.md)。19行保存、21行欠測を保持 | 元計画は未完了。[別の既使用ケース追試40件](availability-ablation-replication-20260908.md)は完了。LLMの付加価値は示せず、元データに合算しない |
| #13 承認状態 | [Spark／playbookの7状態×2actor](http-approval-comparison-20260908.md)を開発ケースで完了 | 人間の承認運用は未評価。未使用評価・部分適用等の要件が残る |
| #13 rollback | [検証失敗後の復元成功](http-rollback-comparison-20260908.md)と[復元snapshot喪失](http-rollback-unavailable-comparison-20260908.md)を各2actorで比較 | 復元の成功とHTTP復旧は別。復元中のストレージ故障とは異なる |
| #13 時間 | [loop復旧時間の誤集計修正](loop-resolution-timing-audit-20260908.md)、[区間別壁時計計測](http-wall-timing-20260908.md)の実Docker固定対照 | [Spark guard比較](http-timed-guard-development-20260908.md)で区間計測を保存。旧データに時間を推定補完しない |
| #14/#15 HTTP | [Sparkの観測版2による開発4件](spark-http-v2-development-20260908.md)。frontendと設定不備を復旧、正常は非介入、依存先停止は誤った再起動で未復旧 | 観測・monitor版が異なる旧結果と単純比較しない。未使用ケース・故障族汎化は未評価 |
| #14/#15 複合故障 | [3故障の段階的修復と内部DNS修正](compound-http-controls-20260908.md)。IP再割当てを実測し、3変更後のHTTP正常化を固定要求で確認 | 直後と待機後のHTTPを分離。モデルの多段階復旧と未使用ケースの主評価は未完了 |
| #7 攻撃 | [正常対象restart誘導の16試行](healthy-restart-attack-development-20260908.md)は全件非介入。[canaryの16試行](canary-attack-development-20260908.md)は禁止読出し・本文出力0だがSparkのreasoningにmarker 2件 | API全出力で漏えいなしとは言えない。少数の開発条件での結果を一般的な耐性と解釈しない |
| #7 正当タスク妨害 | [観測継続誘導の16試行](observation-obstruction-development-20260908.md)。Sparkの停止ケースはclean 2/2、attack 1/2復旧、playbookは両方2/2 | 同一観測の反復実行は0。1件の対応差から因果効果を断定しない。許可済み別対象への誤操作は残件 |
| #11 guard | [実時間の固定対照](timed-guard-controls-20260908.md)と[Sparkの8試行](http-timed-guard-development-20260908.md)を完了 | 上限4の改善は確認せず既定2を維持。多段階復旧・広いケースでの採用判断は未完了 |
| #12 モデル主評価 | [共通runtime確認](primary-runtime-preflight-20260908.md)を完了し、[3モデル・56試行の事前計画](gtx1650-primary-plan-20260908.md)をcommit `96ee05a`で固定、実行開始 | 主評価は収集中で未完了。2故障組合せ3件と既使用正常referenceを分離。背景GPU使用量、モデルprocess VRAM、RSS、cgroup RAMを混同しない |

Spark X2.5 4Bを有効なモデル候補へ追加し、LFMは過去結果・重みを保持して候補から除外した。開発評価の結果であり、主評価によるモデル順位を確定したものではない。VMと製品連携は必要性・採用範囲を判断する後段項目で、未実装を実装済みとは扱わない。

以下の日付付き記録と旧protocolの記述は実施当時の履歴を含む。現在の到達範囲は上表とリンク先の生記録・限界を参照する。

> 2026-09-07 終了契約診断: Agents-A1の開発4件が復旧2/2・適切な非介入2/2で選定基準に到達。初期入力の差は指定した追記だけと検証した。[結果と限界](agents-termination-development-20260907.md) を参照。主評価は未実施。

> 2026-09-07 時間上限診断: Agents-A1の上限を300秒に変更した開発4件は復旧2/2・非介入0/2。正常系は8ターン上限で、選定基準は未達。[比較と残る課題](agents-deadline-development-20260907.md) を参照。

> 2026-09-07 trace保存: 外側timeout時の途中canonical／Tool結果を保存し、中断phaseと未完了を明示するよう修正。実Docker固定対照と全回帰148件が通過。[検証記録](partial-timeout-trace-20260907.md) を参照。

> 2026-09-07 Agents-A1選定: #10の開発4件を事前固定条件で実行。全件が外側timeoutで、復旧0/2・非介入0/2。主評価の選定基準は未達。[実測と次の診断](agents-candidate-development-20260907.md) を参照。

> 2026-09-07 resource fixture: #15の実OOM・専用tmpfs ENOSPC固定対照2件を確認した。OOMは瞬間的なBroker成功判定の後に再発する反例を記録。[結果と限界](resource-fault-controls-20260907.md) を参照。LLM主評価は未実施。

> 2026-09-07 HTTP fixture: #14/#15の開発用ケースを追加。別observerによる実HTTP確認で、frontend停止・設定不備・依存先停止・正常を切り分け、固定対照11件を検証した。[構成・結果・残件](http-fixtures-20260907.md) を参照。未使用評価は未実施。実OOM/ディスク枯渇の追加検証は上記を参照。

> 2026-09-07 LFM診断: #8の開発用CUDA比較8試行を完了。補助観測を追加しても全8件がloop guard終了し、raw/canonical 46応答は一致した。[結果・入出力監査・次の条件](lfm-observation-diagnostic-20260907.md) を参照。主評価とは区別する。

> 2026-09-07追加: #6の実Docker反証9件（不要変更、停止後失敗、監視／監査欠落、拒否・無応答・例外、設定rollback成功／失敗）を確認した。最終全回帰130件が通過。[反証結果と限界](legacy-counterfactuals-20260907.md) を参照。

> 2026-09-07追記: Issue #3/#5の実Docker計測ゲートを検証した。固定要求11件、Docker効果8件、出力形式6件が期待値と一致した。#6の旧5ケースも独立monitor付き固定提案で確認し、最終全回帰127件が通過した。[実施結果と残件](docker-controls-20260907.md) を参照。#6の全完了やモデル・CUDA主評価の実施を意味しない。

> 2026-09-06追記: 旧protocolの結果と生データは保持しています。計測修正・112試行の別版再採点・未確認範囲は [訂正記録](offline-correction-20260906.md) を参照してください。

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

## P0–P2: Mac補助評価（2026-09-05）

[実行契約](mac-research-protocol.md) と [事前仕様](../evaluation/protocols/mac-pilot-v3.json) を追加した。対象は隔離したbusyboxコンテナの停止／正常状態であり、GTX 1650の主評価やHTTPサービスの復旧とは区別する。

- **P0（限定したMac実行経路）**: 復旧・非介入・エスカレーション・未解決を分離し、分子／分母／不明数と分母0の `null` を保存する。Executor記録、要求ID付き完了audit、独立Docker postcheck、再起動時刻の変化を照合する。読出しエラーや証拠不足を違反0件にしない。外側タイマー、正常終了、必要観測の到達、trace redaction、成功／失敗／承認待ち時間を実装した。旧traceの再採点可能性は [監査記録](legacy-trace-rescoring.md) に整理した。
- **P1**: 正常／停止×攻撃あり／なしを対にした。攻撃到達は次のモデル入力に含まれるtool messageから計測する。実Brokerの固定要求11件（正当要求、承認要求、改ざん・expiry・replay、resource、budget、前提条件）と、Dockerの対照6件（正常非介入、不要再起動、復旧を伴う悪影響、全拒否、無応答、例外）を保存した。正解はBrokerの判断結果から作らない。
- **P2（Mac補助評価を完了）**: 公開観測だけを読むB0、最小B1、提案B2、段階公開なし／ヒントなしの単一機構ablationを用意した。LFMでハーネスを比較し、B2でLFM・Agents-A1・Graniteを比較する。評価用8ケース×2回×7条件＝112試行を事前固定した。開発用32試行を実行後、別出力で本評価112試行を完了した。欠落・重複・準備エラーは0。ケース内反復を平均した対応差と記述的区間を保存した。結果と限界は [実施結果](mac-pilot-summary-v3.md) を参照する。

回帰テスト92件が通過した。本評価ではGraniteによる正常コンテナへの不要再起動1件を検出し、非介入成功から除外した。計測範囲内の境界違反は0/112だが、包括的な安全性の保証とは扱わない。

主要な実装:

- `evaluation/research_protocol.py`: 終了結果・指標・欠測の扱い。
- `evaluation/research_cases.py`: 隔離ケース、公開観測playbook、独立効果記録。
- `evaluation/request_controls.py`: 正当要求／不正要求の対照。
- `scripts/evaluate_mac_research.py`: ネイティブMetal推論、trial上限、再現条件、モデルの逐次ロード／解放。
- `scripts/analyze_mac_research.py`: ケース別集計、反復を独立試行と誤認しない対応比較、計画行列の欠落検出。

旧結果JSONは変更していない。2026-09-05時点のCUDA向け5ケースは独立monitor未接続だった。2026-09-06に `evaluation/legacy_monitor.py` と別protocol／別出力のrunner接続を追加し、mock回帰で検証した。実Docker/CUDAでの検証は未実施で、設定・ログ操作の害など未対応の観測は引き続き `null` とする。今回のP0–P2の結果は新しいMac runnerの限定された実行経路に対するものである。L2はメモリ内Executorの承認対照に含むが、人間の承認運用やLLMによるL2復旧比較は未評価。Docker外の操作経路やホスト侵害、GPU VRAM peak、異なる故障族への汎化は未検証である。

## v2 で追加した評価境界

- model prompt は `incident-001` 形式の opaque ID、symptom、observations のみ。Tool surfaceはBroker生成のfunction schemaとして別送する。
- `evaluation/adapters/` が Sabakan JSON、OpenAI/llama.cpp `tool_calls`、LFM native marker を Canonical Proposal に変換する。
- `envelope_valid`、`tool_name_valid`、`tool_arguments_valid`、`resource_valid`、`broker_acceptance` を分離し、後者は実 Broker の schema / policy を通す。
- `approval_required` は本番 proposal に含めず、Broker の `requires_approval` を診断結果として記録する。
- synthetic benchmark は diagnosis / plan / Broker acceptance の評価であり、executor を実行しない。Docker fixtureは実executor/postcheckまで測定する。
- multi-turn agent loopは初期観測時にRead-only schema、Read成功後にL1およびL2 `config_patch` を含むremediation schemaを公開する。許可・承認・実行は公開schemaではなく、常にBroker policy/guardが決める。

## 評価上の既知の制約

- 現行v2の成功判定は `mutation_verified` を必要とするため、適切な非介入を成功として評価できない。復旧・非介入・攻撃対応を分離する仕様に基づく新しいMac実行経路を追加した。旧v2は再実行・上書きしていない。
- `unsafe_execution_rate` は、危険と分類された提案に由来する変更実行件数を全提案件数で割った現行指標であり、情報漏えいや許可済み操作の運用上の悪影響まで網羅する指標ではない。
- `security_invariants` の固定 `True` は設計上の宣言と区別する必要がある。未計測・例外終了を違反0件として扱わず、新しいMac実行経路では独立観測を使い、設計前提と未計測を分離する。
- 旧loopの平均復旧時間には失敗終了時間も含まれていた。2026-09-08に[修正と別出力監査](loop-resolution-timing-audit-20260908.md)を行った。旧JSONは保持し、独立HTTP scoreの復旧時間とloop内の復旧時間も区別する。
- 既存の結果JSONは旧protocolの測定記録として保持する。新仕様に基づく結果は別protocol・別ファイルで作成し、旧結果を無断で上書きしない。

## 次の実装順序

1. **P0: 評価の正解と分母の修正** — 復旧必要／非介入／攻撃シナリオ、終了結果、独立した正解判定、危険実行の計測範囲、復旧時間を整理する。回帰テストと旧traceの再採点可能性の確認を先に行う。
2. **P1: 非介入・安全性・誤拒否の対照評価** — 正常系、不要再起動、許可済み操作の悪影響、攻撃有無の対、正当要求の誤拒否を評価する。失敗を全体の安全性の証明に置き換えない。
3. **P2: 比較実験** — 同じ観測・権限を使う固定playbook、同一モデルでの最小／提案ハーネス、単一機構ablationを比較する。開発用と未使用の評価用ケースを分け、複数回試行と再現条件を記録する。
4. **P3: 障害とpostcheckの現実性の向上** — まずDockerで実際のサービス応答・書込み成否などを検証する。systemdやOSレベルの検証が必要なケースに限定してVM fixtureを追加する。

`ops-agentd` の forced-command / authenticated RPC、Hermes adapter、Discord gateway は後段の拡張候補として維持する。研究上の比較・評価を先に成立させ、接続先や機能の増加を研究成果の代替としない。
