# 主評価の共通runtime確認（Issue #9、#12）

Agents-A1とGraniteを、Sparkで使用した同一のruntime overlay、16層GPU、
thinking auto/-1、生成上限1024、context 8192で確認した。
既知のservice正常／停止2ケースを各モデルで実行し、両モデルとも正常非介入1/1、復旧1/1だった。
これはTool呼出しの互換性確認であり、HTTP主評価の成功やモデル順位を意味しない。

事前固定commitは `8e7366f`。`evaluation/shared-runtime-{agents,granite}-dev-20260908.json`
に入力、提案、実行、GPU観測、runtime情報を保存し、各launch JSONに起動と計画SHAを記録した。
Agentsの所要時間は171.19秒。逐次ロード・解放し、両server削除はreturncode 0だった。
これらの既使用ケースを未使用テストに再分類しない。

`evaluation/primary-model-provenance-20260908.json` では、公開repositoryの特定revisionに
ある重みのLFS SHA256がローカルmanifestと一致することを確認した。
これは同じ内容の重みを含むrevisionの固定であり、当初ダウンロードしたrevisionの復元ではない。

主評価用に、2故障の組合せ3件と既使用の正常referenceを
`evaluation/protocols/primary-http-case-pool-20260908.json` に分けて固定する。
既存の単一故障と3故障の対照は開発に使用済みである。新しい組合せにも同じ故障族が含まれるため、
故障族holdoutとは呼ばない。完全な実行計画を固定するまでこのpool自体は実行を許可しない。

RAM計測をVRAMから分離するため、主評価には任意の `capture_host_memory` を追加した。
モデルコンテナのinit processについてRSSとRSS高水位、cgroup-v2について現在値・peak・OOMイベントを保存する。
共有ページの計上範囲や課金先が異なるため、RSSとcgroup値は大小も一致するとは限らない。
未取得値をゼロにせず、cgroupのcontainer IDを照合する。既存GPUサンプルは別項目のまま保持する。

`evaluation/container-memory-live-control-20260908.json` で稼働中のGraniteコンテナから取得できた。
これは計測器の実接続確認であり、その1サンプルを主評価のモデルpeakに使わない。
主評価runnerは終了前のDocker Stateも保存し、OOMKilled・exit codeを後から確認できる。
batch、microbatch、thread数は計画で明示できるようにした。全233 testsが通過した。
