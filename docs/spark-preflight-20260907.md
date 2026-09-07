# Spark導入・CPU疎通の結果

公式Q4_K_M重み2,600,224,352 bytesの取得を完了し、manifestのSHA256と一致した。`evaluation/spark-weight-verification-20260907.json` に実サイズ・SHA・保存先を記録した。

公式互換runtime `XHToken/llama.cpp` の `4a3635c` をCPUビルドし、モデル読込みとテキスト生成は成功した。ただしTool疎通2条件は失敗した。

| 条件 | 結果 |
|---|---|
| tool_choice=auto | Toolを呼ばず、未観測のnginxを正常と回答 |
| 最初だけtool_choice=required | typed callなし。確認済みであるかのような文章を生成し、128 token上限で終了 |

両条件とも2048 context、4 CPU threads、reasoning off、単一slot、max_tokens 128。同じ要求文・service_status schemaを使い、後者は最初のtool_choiceだけ変更した。各条件を実行前に別planで固定し、再試行しなかった。正しい最初のcallがなかったため、模擬Tool結果を渡す2段階目には進んでいない。

テンプレートはToolsの描画処理を含み、propsではsupports_tools／supports_tool_calls=trueを報告する。ただし、能力宣言だけで実際のtyped call互換性を検証済みとはしない。今後の診断では実際のレンダリング、call形式、Sabakan共通system prompt下の行動を切り分ける。今回の結果でSpark一般の性能を断定しない。

記録:

- `evaluation/spark-cpu-preflight-20260907.json`: 最初のauto条件。
- `evaluation/spark-cpu-required-tool-20260907.json`: 必須指定の別条件。
- 各planは `evaluation/protocols/spark-cpu-*.json`。生HTTP要求・応答、canonical提案、props、command、runtimeライブラリhash、終了ログを保存。

CPU疎通のサーバーはいずれも終了済み。CUDA版は別ディレクトリでビルド中で、GPU収容・CUDA推論・Broker経由の復旧はまだ未検証である。CPU実行中にCUDAコンパイルも進行しており、時間値を速度比較には使わない。
