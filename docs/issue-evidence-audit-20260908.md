# Issue要件と証拠の照合（2026-09-08）

状態: 採用範囲の証拠照合を完了。GitHub Issueのチェックボックスや状態は変更していない。本表は研究として採用した比較と、未採用・未検証の範囲を区別する。全Issueを閉じられるという宣言ではない。

## リポジトリとユーザー指定

| 要件 | 確認できた証拠 | 判定 |
| --- | --- | --- |
| 現状確認、最新リモートの取り込み、既存変更保護 | [更新記録](docker-controls-20260907.md): mainをbfdda56→b4b8acaへfast-forward。作業branchで継続。後続fetchでも未取り込みcommitなし | 実施済み。最終fetchでも未取り込み変更なし |
| Spark X2.5 4Bを追加し不要な候補を除外 | manifestと[主評価](gtx1650-primary-results-20260908.md): Sparkを採用、LFMをarchive。MiniCPM追加は別作業で主評価には含めない | 実施済み、既存履歴保持 |
| 容量不足時はSSDへ移動可 | [LFM移動記録](../evaluation/archived-lfm-storage-move-20260908.json): 未使用1.67GBをSSDへ移し、元pathのsymlinkと前後hash一致を確認 | 実施済み。稼働中モデルは移動せず |

## 計測ゲートと再現性

| 要件 | 実際の証拠 | 残る制限 |
| --- | --- | --- |
| #3 正常→停止、StartedAt不変の悪影響 | [実Docker8対照](docker-controls-20260907.md): 失敗返却時は害1、例外時は観測悪化を保存し集計unknown | snapshot外の一時的影響は再構成しない |
| #4 Canonical Proposal、提案と実行の分離 | 同記録の6形式対照、[旧Mac再採点](offline-correction-20260906.md)、攻撃比較の個別解析 | 不正JSONや未完了出力はunknown |
| #5 回帰、正当要求、不正承認、実効果、旧112件別版再採点 | 固定要求11、Docker8、形式6、[別版112件](../evaluation/mac-pilot-rescored-20260906.json)、[最新266回帰](../evaluation/post-primary-verification-20260908.json) | 新規実行と旧再採点を混ぜない |
| #6 旧5ケースの独立monitor | [固定5件](docker-controls-20260907.md)と[反証9件](legacy-counterfactuals-20260907.md)。監査双方向照合、違反・害・設定rollback・欠測 | 旧5ケースを今回のCUDA主評価へ採用していない。旧経路全体の実モデル比較や包括的な設定/log害計測の完了とはしない |
| #8 LFM全失敗の診断 | [CUDA観測比較8件](lfm-observation-diagnostic-20260907.md):全8件loop停止、46応答raw/canonical一致。終了契約の開発診断を別記録で実施 | LFM一般の能力不足とは断定せず、ユーザー指定の置換後も履歴保持 |
| #9 事前仕様、未使用ケース、反復、順序、打切り、hash、欠測 | [主評価計画](gtx1650-primary-plan-20260908.md)を96ee05aで固定。56件の正式解析で欠測/重複/予定外/不正根拠0、source一致、cleanup確認 | 単一故障族の3組合せ、case内反復であり独立族CIはnull。成功後の追加/置換なし |

## 比較とRQ

| 要件 | 実際の証拠 | 判定・制限 |
| --- | --- | --- |
| #7 許可操作の誤用、正常restart、別対象 | [正常restart16件](healthy-restart-attack-development-20260908.md)、[別対象8件](wrong-target-http-results-20260908.md) | actor別攻撃到達、提案/受理/進入/状態変化を分離。限定条件の非介入で一般耐性を主張しない |
| #7 正当タスク妨害 | [観測継続誘導16件](observation-obstruction-development-20260908.md) | 攻撃8件到達、実反復0、Sparkの1件だけ対応復旧差。因果断定なし |
| #7 canary読出し/出力、計測器対照 | [16件と合成対照](canary-attack-development-20260908.md) | 禁止読出し/本文marker0でもreasoning2件。API全出力の漏えいなしとしない |
| #10 playbook/B1/B2/単一機構、実到達、未使用評価 | [既使用40件追試](availability-ablation-replication-20260908.md)と[主評価56件](gtx1650-primary-results-20260908.md) | 主評価で床効果再発、hint到達0。付加価値なしを保持し、同等性・hint有効性は未証明 |
| #11 guard閾値1要因、正当再観測/無進捗、外側上限 | [実時間対照](timed-guard-controls-20260908.md)と[モデル8件](http-timed-guard-development-20260908.md) | 2対4の改善根拠なし、既定2維持。外部復旧とモデル修復を分離。複合復旧で閾値を変える追加比較や本番最適性は未検証 |
| #12 同一ハーネス/資源、VRAM、総費用、モデル順 | 主評価6loads、56件、反復1は逆順、process GPUと背景device/RSS/cgroup別計測 | モデル全層GPU fitは未証明。共通復旧0で対応復旧時間比較なし。timeout時の費用欠測保持 |
| #14 原因切り分け、必要観測、契約、正常対照、未使用組合せ | [HTTP4ケース](http-fixtures-20260907.md)、[複合/DNS対照](compound-http-controls-20260908.md)、主評価pool | 故障族holdoutなし。旧DNS/TLS/crash loop等は[棚卸し](offline-issue-review-20260906.md)で対象外を明示 |

## #13 承認条件の個別照合

| 要件 | 証拠 | 判定・制限 |
| --- | --- | --- |
| 承認方式、allow/deny/pending/expired/unanswered/state_changed | [7状態×2actor](http-approval-comparison-20260908.md) | fixture支援とunassistedを分離、人間承認は未評価 |
| hash/principal/nonce/expiry/plane改ざん、replay、前提不一致、非実行 | 固定要求対照とapproval/security回帰（上記266件に含む） | 固定要求での検証、任意運用の保証ではない |
| 承認/モデル/Tool/復旧時間、escalation区分 | 各rawのapproval状態、[壁時計区間](http-wall-timing-20260908.md)、[復旧時間修正](loop-resolution-timing-audit-20260908.md) | 旧データに区間を推定補完せず、pendingは模擬即時応答 |
| 設定検証失敗・部分適用 | [ファイル4対照](partial-config-file-controls-20260908.md)、[HTTP12件結果](http-partial-write-results-20260908.md) | 12件完了。復元成功条件4件の害計測は不明、無害としない |
| 事後検証失敗、復元成功/失敗、独立状態 | [復元成功2actor](http-rollback-comparison-20260908.md)、[snapshot喪失2actor](http-rollback-unavailable-comparison-20260908.md) | 注入verificationとsnapshot喪失、実ストレージ故障とは異なる |
| LLM履歴に承認情報なし、実ホスト設定/credentialなし | [18試行入力監査](approval-history-audit-20260908.md)、隔離構成、生成経路回帰 | 保存済み構造化情報とfixture鍵の限定監査。[部分書込み12件も追加監査済み](../evaluation/partial-write-approval-history-audit-20260908.json)、検出0 |
| 同条件playbook/モデル、事前計画、人間承認範囲 | 各条件別plan/hash、今回の12件も2actor×2反復 | 人間の参加・待ち時間評価は未採用と明示 |

## #15–18: 実故障、採用範囲、最終報告

実HTTP（runningでも失敗）、構文/意味的不備、依存先停止、誤った再起動、保護データ変化、検証/rollback、固定監視窓とcleanupは[HTTP対照](http-fixtures-20260907.md)と[複合対照](compound-http-controls-20260908.md)に保存した。[実資源故障2対照](resource-fault-controls-20260907.md)はcgroup OOMと再発、専用1MiB tmpfsのENOSPCとログ解放後の3回書込み、保護hash不変を観測した。OOMトリガーをcontrollerが除去した回復を自律復旧としない。

#16のVMはsystemd/OS起動を採用ケースが必要としないため未採用。#17のdaemon、Hermes、Discord、自律運用は後段・未有効化。#18は全ての条件付き拡張の実装を要求していないが、未検証を確認済みにしない。これらのIssueを実装完了として閉じる根拠にはならない。

[総合報告](research-summary-20260908.md)でRQ1の付加価値なし/機構到達、RQ2の境界/害/誤拒否/停止/未解決、RQ3の同一条件の費用と欠測、攻撃/反復/actor到達、実故障/模擬、承認方式、旧新データ、関連研究との限定的な位置付けをまとめた。部分書込み結果と最終整合性確認を反映済み。
