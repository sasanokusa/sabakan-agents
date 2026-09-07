# 固定Docker環境へのruntime追加

Spark専用ビルドを既存のDocker評価上限と組み合わせるため、開発runnerに任意の `runtime_overlay` を追加した。指定しない既存planは従来どおり動作する。

overlayはbin_directoryと、llama-server／共有ライブラリ全件のSHA256 inventoryを持つ。実行前に名前集合とhashの両方を検証する。不明な共有ライブラリ、欠落、改変があれば起動前に拒否する。ディレクトリはコンテナ内へread-onlyでmountし、entrypointとライブラリ探索順を変更する。既存のイメージdigest、GPUデバイス、モデルmount、メモリ・CPU・PID上限は保持する。

実Docker対照では、ビルド済みCPU版を固定CUDAイメージ上へ追加し、`--version` がexit 0で `4a3635c` を返すことを確認した。`evaluation/spark-overlay-version-20260907.json` に実コマンドとhashを保存。モデル推論、CUDAライブラリの動的ロード、GPU収容の検証ではない。CUDAビルド完成後に別途確認する。

回帰153件通過（`evaluation/runtime-overlay-validation-20260907.log`）。overlay改変と未記録ライブラリを拒否するテストを含む。この変更だけで主評価の実行条件が凍結されたとは扱わない。
