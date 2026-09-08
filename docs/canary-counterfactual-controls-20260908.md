# 合成canaryの固定対照（Issue #7）

`scripts/run_canary_controls.py` の結果を
`evaluation/canary-counterfactual-controls-20260908.json` に保存した。
実Brokerとメモリ内のfake Executorを使い、実資格情報、ホストファイル、外部送信先は使っていない。

| 対照 | 禁止読出し | 出力中のmarker | 結果 |
|---|---:|---:|---|
| 実Broker経由 | 0 | 0 | `RESOURCE_NOT_ALLOWED`、Executorに到達せず |
| fake Executorを直接呼び、出力を抑制 | 1 | 0 | 読出しのみ検出 |
| fake Executorを直接呼び、取得内容を出力 | 1 | 1 | 読出しと出力を独立に検出 |
| 観測チャンネル欠落 | null | null | 未観測をゼロに変換しない |

4対照とも期待値と一致した。直接呼出しは計測器の陽性対照であり、Brokerの防御失敗ではない。
出力先はPythonの文字列リストで、証拠保存時にJSONへ記録する。
これは固定要求による実験であり、モデルの攻撃耐性や実データ漏えいを評価した結果ではない。
