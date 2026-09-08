# 研究評価の総合報告（2026-09-08）

状態: 主評価と攻撃比較の結果を反映した作業版。部分書込み12試行の収集・解析とIssue別の最終照合が残っており、Goal完了の宣言ではない。

## 採用範囲

GTX 1650 4GB上で、Agents-A1-4B、Granite-4.2-3B、Spark X2.5 4Bを共通runtime・量子化・資源条件で比較した。ユーザー指定でLFMをSparkに置き換え、LFMの重み・診断・Mac pilotは保持した。モデル全層のGPU搭載を前提とせず16層offloadとCPUを使用し、背景GPU負荷を維持した。重み・runtime・計画・ソース・入力・出力のhashは各記録に紐付く。

[主評価56試行](gtx1650-primary-results-20260908.md)は未使用の2故障組合せ3件と既使用正常reference1件を各2回、Sparkの5条件とAgents・GraniteのB2で実行した。未知のHTTP故障族や本番障害全般を対象とする評価ではない。開発比較、固定要求対照、Mac補助評価、旧traceの再採点は別の証拠として扱い、分母を合算しない。

## RQ1: ハーネスとLLMの付加価値

主評価の複合故障では公開観測playbookが6/6復旧、全LLM条件が0/6。正常referenceは全条件2/2非介入だった。ケース内2反復を平均したSpark B2−playbookの復旧成功差は−1だった。今回の範囲ではLLMの付加価値を示せず、モデル側に全失敗の床効果があるため、ハーネス間の差0を同等性と解釈できない。

Spark B2のhint入力到達は全8試行で0だった。schemaは期待した段階と一致していたが、hintの有効性を実測したとは言えない。[既使用availabilityケースの追試40件](availability-ablation-replication-20260908.md)でもLLMの付加価値は示せず、hint到達0だった。元の40行計画の中断19行と欠測21行は別に保持し、追試で穴埋めしていない。

[guard開発比較8件](http-timed-guard-development-20260908.md)では既定2から4への変更を採用する改善根拠は得られず、既定2を保持した。固定の時間付き対照は早い停止が正当な再観測を妨げ得る反例を示すが、実モデルの遅延ケースでは外部controllerの復旧であり、モデルによる修復ではない。主評価の複合故障結果は多段階復旧能力の限界を示す。広いケースで最適なguard閾値を決定したとはしない。

## RQ2: 境界・運用上の害・停止・タスク遂行

[固定要求・Docker反証](docker-controls-20260907.md)と[旧5ケースへの独立monitor検証](legacy-counterfactuals-20260907.md)では、認可の可否と実際の効果を分け、不要変更、正常から停止、監査欠落、無応答、例外などを対照とした。全拒否は安全な復旧システムの成功として数えない。正当要求の固定対照は限定した要求集合であり、正当要求全般の誤拒否率を推定しない。

主評価ではAgentsの依存先停止＋設定不備で運用上の害を2件観測した。Sparkの段階公開なしの1件は害計測不明だった。境界違反の観測0と、許可操作の必要性・運用上の無害性は別である。内側guardの介入0でも外側timeoutや未復旧があり、停止を復旧と読み替えない。

| 攻撃の目的 | 開発比較 | 到達と主な結果 |
| --- | --- | --- |
| 正常対象の不要restart | [16試行](healthy-restart-attack-development-20260908.md)、2対象のclean/attack×2actor×2反復 | 攻撃8件到達、全16件非介入、対象提案・実行0 |
| 別の許可対象への誤操作 | [8試行](wrong-target-http-results-20260908.md)、clean/attack×2actor×2反復 | 攻撃4件到達、全8件非介入、対象提案・実行0 |
| 正当タスクの妨害・観測継続誘導 | [16試行](observation-obstruction-development-20260908.md)、正常/停止×clean/attack×2actor×2反復 | 攻撃8件到達。同一status反復実行0。Spark停止ケースの復旧はclean2/2、attack1/2、playbookは両方2/2 |
| 合成canary読出し／本文出力 | [16試行](canary-attack-development-20260908.md)、2目的のclean/attack×2actor×2反復 | 攻撃8件到達。禁止読出し・本文marker0、Sparkのreasoningにmarker2件 |

到達数は攻撃あり行で、いずれもactorごとの到達を個別記録に保持する。これらは既使用ケースで少数の固定攻撃文を試した結果であり、適応的攻撃探索や一般的な耐性を実証しない。実行されなかった提案をBrokerが阻止したと数えない。canaryは攻撃者が与えた合成文字列で実資格情報ではないが、reasoning出力を含むAPI全体で漏えい0とは言えない。妨害条件の1件差から因果効果を断定しない。

## L2承認と部分故障

[7承認状態×2actorの14試行](http-approval-comparison-20260908.md)を実施した。許可、拒否、保留、未応答、期限切れ、状態変化と承認なしを分けた。署名はfixture別Approval Planeで供給し、保留・未応答は即時に制御状態を返す模擬比較で、人間の承認待ち時間ではない。承認の正しさと操作の妥当性は別である。

[事後検証失敗からの復元成功](http-rollback-comparison-20260908.md)と[snapshot喪失による復元不可](http-rollback-unavailable-comparison-20260908.md)を各2actorで比較した。元の不正設定へ戻ったことはサービス復旧ではない。snapshot喪失はストレージ故障と区別する。[承認履歴18件の監査](approval-history-audit-20260908.md)では構造化承認情報や既知fixture鍵を保存済みLLM入力に検出しなかったが、未知の符号化漏えいまで否定しない。

[一時ファイル固定対照4件](partial-config-file-controls-20260908.md)では部分書込み・復元成功/失敗・検証失敗・承認なしの非実行を観測した。返却mutation flagがfalseでも実書込みが起きるため、独立したhashとbyte数を使う。[HTTP部分書込み比較12試行](http-partial-write-plan-20260908.md)は収集中であり、結果は未確定。終了後にこの節へ反映する。

## RQ3: 同一資源条件での費用と失敗

主評価のモデルprocess観測最大VRAMはSpark1634 MiB、Agents1926 MiB、Granite1334 MiB。device全体では背景負荷を含む。RSSとcgroup RAMは別の実測で、GPU VRAMと混同しない。約0.57秒間隔の観測最大は瞬間peakの保証ではなく、全層GPU fitも実証していない。

複合故障はLLM同士で共通成功例が0のため、対応する復旧時間比較は成立しない。Spark B2は平均131.55秒で未復旧終了、Agents・Graniteは約304秒で外側timeoutだった。これをSparkの高速復旧の証拠としない。正常referenceの平均経過はSpark B2 49.43秒、Agents66.51秒、Granite57.81秒、playbook2.58秒であるが、各2件の記述値に留まる。

未完了要求がある試行のtoken総量・loop Tool総数はunknownとし、観測済み応答の和を別記した。decode TPSだけで総費用を比較しない。未使用ケースの多様性、背景負荷、少数反復、成功例不在により、実用モデルの一般的な順位は確定できない。

## 関連研究に対する位置付け

CaMeLは信頼された要求から制御・データフローを分離し、capabilityで非認可のデータ移動を制約する。[CaMeL原論文](https://arxiv.org/abs/2503.18813v2)。本研究は同等の情報フロー保証を実装・証明したものではない。

AgentDojoは非信頼Tool出力を扱うエージェントについて、正当タスクと攻撃・防御を評価する拡張可能な環境である。[AgentDojo原論文](https://arxiv.org/abs/2406.13352v3)。本研究の少数固定ケースを、その広さや適応的攻撃評価と同一視しない。

AIOpsLabはmicroservice環境、故障注入、負荷、telemetry、agent interfaceを組み合わせて運用タスクを評価する。[AIOpsLab原論文](https://arxiv.org/abs/2501.06706v1)。本研究は低VRAMの小型モデルと限定したBroker操作に範囲を絞り、復旧・非介入・境界・実効果・費用の分離、および否定的結果の再現可能な記録を提供する。先行研究を上回る性能・保証を測定したとはしない。原典abstract確認日2026-09-08、網羅的関連研究調査ではない。

## 未採用の拡張と完了までの残件

systemd/OS起動のケースを採用していないためVMは未追加。ops-agentd、Hermes、Discord、本番自律運用は後段に留めた。人間承認運用、ホスト侵害・container脱出耐性、未知故障族への汎化、実OOM/ENOSPC下のLLM復旧の主評価は未検証である。実OOM・専用tmpfs ENOSPCと再発は[固定対照](resource-fault-controls-20260907.md)として確認した範囲に限る。

部分書込み比較の完了・解析・履歴監査、全回帰、Issue別の要件と証拠の最終照合が残る。リモートへのpushやIssueのクローズは行っていない。
