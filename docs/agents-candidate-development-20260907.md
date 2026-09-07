# Agents-A1の開発用選定試行（2026-09-07）

Issue #10の床効果を避けた比較条件の選定に向け、既存の開発ケース4件を実行した。この条件は選定基準を満たさなかった。主評価を開始する根拠にはしない。

## 実行前の固定

`4bf68f0` で `evaluation/protocols/agents-candidate-dev-20260907.json` をcommitしてから実行した。Agents-A1-4B Q4_K_M、重みSHA検証、固定CUDAイメージ、context 8192、GPU 16層、B2、informative補助観測、max_tokens 384、8ターン、各120秒、1反復。既存GPU処理を維持するため部分offloadを採用した。全層GPU収容やLFMとの速度の対応比較は行っていない。

選定条件は復旧と適切な非介入を少なくとも各1件観測すること。全4件を実行し、失敗による追加試行や途中の条件変更はしなかった。warm-upは別記録。未使用評価ケースは使用していない。

## 結果

| 開発ケース | 結果 | HTTP推論要求数（うち未完了） | 必要な対象status観測 |
|---|---|---|---|
| service停止 | OUTER_TIMEOUT、未復旧 | 6（1） | 完了 |
| service正常 | OUTER_TIMEOUT、正常終了なし | 5（1） | 完了 |
| container停止 | OUTER_TIMEOUT、未復旧 | 6（1） | 未完了 |
| container正常 | OUTER_TIMEOUT、正常終了なし | 5（1） | 未完了 |

復旧0/2、適切な非介入0/2。独立executor記録では全件の変更実行は0。serviceでは正しい状態観測後も追加調査が続いた。containerではhost_status/docker_list等の補助観測から状態を読めたが、必要なdocker_statusには到達しなかった。両モデルの全般的能力やハーネス機構の無効性は、この結果から断定しない。

ロード35.9秒、warm-up・試行・cleanupを含む551.0秒。GPUのデバイス全体の観測最大3280MiB、有効サンプル1004件。既存プロセスPID 1586/1587は実行前後でそれぞれ282/1112MiBで、停止していない。実験コンテナは削除された。サンプリングは瞬間peakを保証せず、モデル単独VRAMとも異なる。解析器の回帰テストを実験中に実行したため、CPU負荷が隔離された速度測定ではない。

## 記録と次の判断

- 生データ: `evaluation/agents-candidate-dev-20260907.json`
- 固定行列検査・行別解析: `evaluation/agents-candidate-analysis-20260907.json`
- 再現: `python3 scripts/diagnose_lfm_observations.py --plan evaluation/protocols/agents-candidate-dev-20260907.json --output <新規JSON>`
- 解析: `python3 scripts/analyze_candidate_development.py <入力JSON> --output <新規JSON>`
- 回帰: `evaluation/agents-candidate-validation-20260907.log`、146件通過。

外側タイムアウトでは既存runnerの集計済みloop traceが失われる。raw応答、実際の入力、executorイベント、Broker監査は残るが、canonical対応や集計Tool数が完全に検査できたとはしない。解析は欠落をnullとして保持した。完了したHTTP応答は18件で、4件の未完了要求のtoken使用量は不明。

次の開発ではまずタイムアウト時の途中trace保存を修正する。その後、時間上限の単一変更による診断か、実HTTP診断ケースへの別試行を実行前に固定する。補助観測以外に模擬応答が残るため、時間を増やせば復旧するとは仮定しない。未使用主評価のprotocolは引き続き未凍結である。
