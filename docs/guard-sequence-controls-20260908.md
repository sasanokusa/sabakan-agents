# Guard固定観測列の開発対照

Issue #11の閾値比較用の配線を、実Brokerと合成Executorで確認した。scripts/run_guard_sequence_controls.pyを実行し、evaluation/guard-sequence-controls-20260908.jsonに4対照の要求・応答・Executor到達・監査を保存した。全4対照が事前にコード中で定義した期待値と一致。

| 観測列 | 上限2 | 上限4 |
| --- | --- | --- |
| starting, starting, ready | 3要求目をLOOP_DETECTED、ready未到達 | 3要求目でready観測 |
| startingの反復 | 3要求目をLOOP_DETECTED、Executor到達2回 | 5要求目をLOOP_DETECTED、Executor到達4回 |

固定6要求以内、要求間で10秒の経過確認を行う。承認・allowlist・変更上限・総要求上限は変更せず、固定要求はservice_statusのみ。実際の変更操作は含まない。

観測列はreadが到達するたびに進む合成データであり、実時間経過による復旧ではない。閾値を緩めると正当な観測列を完遂できる一方、無進捗にも追加readを許すことを配線対照として確認した。モデルを使う正当なポーリング・実遅延復旧・多段階復旧の対応比較、独立した悪影響評価、閾値採用の判断は未完了。この結果だけで本番閾値を変更しない。
