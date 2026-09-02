# Sabakan Agent

Sabakan は、ローカル LLM を信頼せず、型付き Tool 呼び出しを `sabakan-broker` で強制的に検証するサーバー管理エージェントの実装土台です。

このリポジトリは設計書の実装順序に沿って、まず Broker の安全境界を実装しています。

```text
Conversation / Hermes / LLM
            │  typed request only
            ▼
      sabakan-broker
  schema → policy → approval
  kill switch → budget → audit
            │
            ▼
       Executor / ops-agentd
```

## 現在の実装

- 型付き Read / Mutation Tool のスキーマ検証
- host / service / container / logical resource の allowlist
- Read 結果の secret redaction、サイズ・行数制限、ログの重複縮約
- L0 / L1 / L2 / L3 の policy 判定
- 具体的な operation hash、期限、nonce、HMAC 署名の Approval 検証
- execution 直前の state hash 再検証（TOCTOU 対策の executor フックを含む）
- resource budget、host circuit breaker、incident tool-loop 制限
- `/run/sabakan/ARMED` と `/etc/sabakan/DISABLED` による fail-closed kill switch
- SQLite audit log（LLM の自然言語説明ではなく Broker が生成）
- ローカル実行用の `SystemExecutor` と、テスト用 executor インターフェース
- incident fixture と標準ライブラリだけで動く回帰テスト
- 3種類の初期評価モデル（Q4_K_M GGUF）と同一条件の評価 runner

Hermes、Discord、SSH の unrestricted shell はまだ接続していません。Remote control は authenticated RPC / forced-command executor を追加してから接続します。

## モデル評価

モデルは [`models/manifest.json`](models/manifest.json) に記録しています。全モデルを同時にロードせず、次のコマンドで1つずつロード・評価・CUDA解放します。

```bash
# GGUF本体はGitHubへ含めず、manifestのURLとSHA-256から取得
python3 scripts/download_models.py

python3 scripts/evaluate_llamacpp.py
```

結果は `evaluation/results.json` に保存されます。評価 runner はモデルが提案した文字列を実行せず、同一の incident fixture に対する root cause、構造化出力率、承認整合性、unsafe action、不要な mutation、tool call 数などだけを測定します。

評価は公式 llama.cpp の CUDA サーバーをモデルごとに起動します。NVIDIA Container Toolkit が使えないホストでは、ホストの CUDA デバイスとドライバライブラリを明示的に渡します。モデルサーバーは各モデルの測定後に削除され、次のモデルへ GPU メモリを持ち越しません。

## 実行

```bash
cd /home/sasa/sabakan-agent
PYTHONPATH=src:. python3 -m unittest discover -s tests -v

# 現在のホストの read-only status
PYTHONPATH=src python3 -m sabakan_broker status local

# service status（systemd がある環境のみ）
PYTHONPATH=src python3 -m sabakan_broker service-status local nginx
```

Mutation はデフォルトでは実行されません。`/run/sabakan/ARMED` がなく、また `/etc/sabakan/DISABLED` が存在する場合は必ず拒否します。テストでは一時ディレクトリを kill switch の root として使います。Broker 自身や LLM から kill switch を変更する API はありません。

## 設計上の注意

- `config/*.yaml` と fixture は JSON 構文で記述しています。JSON は YAML 1.2 のサブセットなので、外部 YAML 依存なしで読み込めます。PyYAML が導入された環境では通常の YAML も読み込めます。
- `service_restart` などの実行可否は、Tool の引数と policy の allowlist の両方で決まります。
- `Approval` は会話メッセージではなく、別 plane から渡される署名済み object としてのみ検証されます。
- 実運用では `SystemExecutor` を remote `ops-agentd` に置き換え、Broker と privileged executor の間を authenticated RPC にしてください。

実装状況と次の段階は [`docs/implementation-status.md`](docs/implementation-status.md) にまとめています。
