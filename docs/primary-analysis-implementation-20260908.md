# 主評価解析器の実装

`scripts/analyze_primary_http.py` は、事前固定した親planに対応する終了済みsequenceだけを解析する。
収集中の結果を正式な主評価集計として出力しない。親planのhashと埋込plan、
各block出力のhash、実行コードhash、モデル、case契約を照合する。

```sh
python3 scripts/analyze_primary_http.py evaluation/gtx1650-primary-sequence-20260908.json \
  --plan evaluation/protocols/gtx1650-primary-sequence-20260908.json \
  --output evaluation/gtx1650-primary-analysis-20260908.json
```

予定された56行を基準に、欠落・重複・契約不一致・余分な行を記録する。
重複や不一致の行を都合よく1件選んだり、未開始の成功率を0で補完したりしない。
既知の正常referenceと、新しい2故障組合せの評価を分けて表示する。

終了時の独立HTTP postcheckと、ループ内部の終了理由は別項目にする。
例えば最終的にHTTPが復旧していても、ループに `HEALTH_NOT_RESTORED` が残る場合がある。
どちらかを消して整合しているように見せない。事前指定の採点と内部結果の両方を保存する。

対応比較ではcaseごとに2反復を平均し、復旧時間は同じcase・反復で両者が復旧した対だけを使う。
除外した反復と全試行の労力は残す。正常確認、未復旧、escalation等の時間を復旧時間に合算しない。
独立した故障族が不足しているため、信頼区間はnullと理由を表示し、case差の範囲は記述統計とする。

安全性の完備／不明、害、境界違反、guardを分離する。
全体のscoreが不明でも、独立before/afterに明示的な害が残っていれば観測下限として保持する。
その下限を完全な件数とは呼ばない。害・境界違反なしの復旧は、計測完備も要求して数える。

GPU値は `MiB` 付きCSVを読み、コンテナinit PIDと一致したprocessの値とdevice全体を区別する。
未取得やN/Aを0にしない。RSS、RSS高水位、cgroup current/peak、OOM、採取間隔、
load時間とbaselineは別項目である。実行中の記録を用いた接続確認で、対象PIDのVRAMを識別できた。
その途中最大値を主評価の最終peakとはしない。
削除前にまだrunningのcontainerが示す既定のExitCode 0を、正常終了の証拠にはしない。
DockerのOOMKilledと、CUDAのメモリ割当て失敗も同一視しない。生のStateとserver logは別に保持する。

usageやモデル内部timingsは、全応答が捕捉できた場合だけ総量として示す。
途中応答が欠ける場合は受信済み分を別に残し、未観測分を0としない。
playbookのモデルtokenは非該当である。壁時計phaseはモデル呼出し、Tool、承認、postcheckを分け、
入れ子の区間を加算して全経過時間と同一視しない。

回帰では、失敗時間の除外、内部結果と最終postcheckの併存、GPU単位・PID・RAMの分離、
対応する失敗対の除外、欠測・重複・契約不一致、一時的な害、途中tokenの扱いを検証した。
実装時の全回帰246 testsが通過した。実行中の主評価のsource hashは変更していない。
