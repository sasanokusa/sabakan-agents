# 外側タイムアウト時の途中trace保存

Agents-A1開発試行で確認した、外側タイムアウト時に集計済みloop traceが失われる問題を修正した。`run_agent_loop` の任意の `partial_trace` 引数へ、canonical提案、Broker判断、完了済みTool結果を保持する。Mac/CUDA開発runnerはこの引数を接続し、`partial_loop_trace` として保存する。

中断箇所はmodel request、Broker request、承認待ち、承認付きBroker request、postcheck等のphaseで示す。Broker内で中断した場合は、結果が存在しないことを未実行の証拠にしない。完了済みの集計値を再構成せず、途中traceには `trace_complete=false` を付ける。既存の生データは補完・上書きしていない。

検証:

- 全回帰148件通過。次のモデル応答待ちで中断した場合の既存read保持と、Broker内中断時の結果欠落を検証。
- `evaluation/partial-timeout-control-20260907.json`: 実Dockerの停止serviceで、最初にservice_statusを実行し、2回目の固定chatを3秒待機させ、外側1秒で中断。canonical提案とREAD_OKを保持し、phase=model_request、trace_complete=false、未復旧を確認。モデル推論ではない。
- 検証後の実験コンテナ残数0。

この修正は計測の保存経路に限定する。時間上限や復旧・非介入の定義を変更せず、以前のタイムアウトを成功に再分類しない。次のモデル診断は別の事前固定条件で行う。
