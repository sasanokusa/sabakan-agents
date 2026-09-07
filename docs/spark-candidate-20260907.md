# Spark-X2.5-4Bへの候補入替

追記: 重み取得・SHA検証とCPU読込みは完了。Tool疎通2条件は失敗し、CUDA版はビルド中。[疎通結果](spark-preflight-20260907.md) を参照。

2026-09-07のユーザー指示により、現行候補をSpark-X2.5-4B、Agents-A1-4B、Granite-4.2-3Bへ変更した。LFM2.5-2.6Bは `models/manifest.json` の `archived_models` へ移し、デフォルト候補から外した。開発用CUDA観測比較8件が全失敗で、旧Macの全条件失敗も継続しており、現時点のタスク適合性を根拠に選んだ。モデル一般の価値や未実施条件での順位を断定するものではない。

旧重み、凍結protocol、全traceは保持する。過去のLFM診断runnerは明示的に指定された凍結planに対してarchiveも参照できる。新しい主評価はユーザー指定の候補集合で計画し、Issue #12の旧モデル一覧をそのまま再実行しない。

公式配布は [XHToken/Spark-X2.5-4B-GGUF](https://huggingface.co/XHToken/Spark-X2.5-4B-GGUF)。Q4_K_Mファイルは2,600,224,352 bytes、配布revision `d313463f1ff7dc29db20193fddc4ad8386d16261`、SHA256 `adfcfa19a4ed6a5985da8bf565fe15f8e1a7e131d79bae2d19d48d1c40109428` を固定した。downloaderはrevision指定に対応し、取得後のSHA検証を通ったファイルだけを確定する。

このホストではroot領域の残量が小さいため、重みの保存先を `/mnt/ssd/sabakan-models/Spark-X2.5-4B-Q4_K_M` とし、通常のmanifest相対パスからローカルsymlinkで参照する。重みとホスト固有symlinkはGitに含めない。

公式カードは互換実装として [XHToken/llama.cpp](https://github.com/XHToken/llama.cpp) を案内している。既存の共通CUDAイメージで起動できること、4GiB収容、Tool calling、復旧性能は現時点で未検証。候補への登録は実行検証済みという意味ではない。取得完了後、他モデルをアンロードした状態で互換性を確認し、必要なruntime変更は新しい事前仕様に分ける。
