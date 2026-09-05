# Sabakan Agent

Sabakan は、ローカル LLM を信頼せず、型付き Tool 呼び出しを `sabakan-broker` で強制的に検証するサーバー管理エージェントの実装土台です。

このリポジトリは設計書の実装順序に沿って、まず Broker の安全境界を実装しています。

```text
Conversation / Hermes / LLM
            │  typed request only
            ▼
      sabakan-broker
  schema → policy → approval
  kill switch → budget → intent audit
            │
            ▼
       Executor / ops-agentd
```

## 現在の実装

- 型付き Read / Mutation Tool のスキーマ検証
- host / service / container / logical resource の allowlist
- Read 結果の secret redaction、サイズ・行数制限、ログの重複縮約
- ToolResult 全体の aggregate byte limit（nested mapping / list / log を含む）
- L0 / L1 / L2 / L3 の policy 判定
- Tool ごとのコード所有 permission floor（設定による降格を拒否）
- 具体的な operation hash、期限、nonce、HMAC 署名の Approval 検証
- execution 直前の state hash 再検証（TOCTOU 対策の executor フックを含む）
- resource budget、host circuit breaker、incident tool-loop 制限
- mutation budget / circuit / suspension state の SQLite 永続化
- mutation 前後の `MUTATION_INTENT` / `MUTATION_RESULT` audit（二段階、fail-closed）
- `/run/sabakan/ARMED` と `/etc/sabakan/DISABLED` による fail-closed kill switch
- SQLite audit log（LLM の自然言語説明ではなく Broker が生成）
- ローカル実行用の `SystemExecutor` と、テスト用 executor インターフェース
- incident fixture と標準ライブラリだけで動く回帰テスト
- 3種類の初期評価モデル（Q4_K_M GGUF）と同一条件のOpenAI function-calling評価 runner
- disposable Docker fixture（実Broker execute / postcheck / health restored）

Hermes、Discord、SSH の unrestricted shell はまだ接続していません。Remote control は authenticated RPC / forced-command executor を追加してから接続します。

## モデル評価

モデルは [`models/manifest.json`](models/manifest.json) に記録しています。全モデルを同時にロードせず、次のコマンドで1つずつロード・評価・CUDA解放します。

```bash
# GGUF本体はGitHubへ含めず、manifestのURLとSHA-256から取得
python3 scripts/download_models.py

python3 scripts/evaluate_llamacpp.py --output evaluation/results-v3.json --max-tokens 384

# Local LLM multi-turn execution harness (5 disposable Docker fixtures)
python3 scripts/evaluate_agent_loop.py \
  --context-size 8192 --max-tokens 384 \
  --output evaluation/agent-loop-results-v3.json
```

結果は `evaluation/results-v3.json` に保存されます。旧プロトコルの結果は
`evaluation/results-v1.json`（互換用に `evaluation/results.json` も保持）です。
評価 runner はBrokerの `TOOL_SPECS` からOpenAI function schemaを生成し、3モデルへ
同一の `tools` と `tool_choice=auto` を渡します。モデル固有のtool schemaや
approval promptはありません。llama.cppは各GGUFのchat templateをJinjaで適用します。
モデルが提案した文字列は実行せず、opaqueなincident IDと症状・観測だけを渡します。
出力はJSON / llama.cpp tool_calls / LFM native markerをCanonical Proposalに変換し、
実Brokerのschema・resource registry・policyで評価します。Approval要否はモデル出力
ではなくBrokerの判定結果です。

v2/v3のsynthetic benchmarkは実executor / postcheckを実行しないため、
`Diagnostic Success Rate` と呼びます。Docker fixtureでは実際の
`propose → Broker → execute → postcheck → health restored` を測定し、初期3ケースの
旧5ケース混合の集計は予備実験記録として保持します。復旧不要ケースを含む旧比率を研究用の復旧率として使用しません。

評価は公式 llama.cpp の CUDA サーバーをモデルごとに起動します。NVIDIA Container Toolkit が使えないホストでは、ホストの CUDA デバイスとドライバライブラリを明示的に渡します。モデルサーバーは各モデルの測定後に削除され、次のモデルへ GPU メモリを持ち越しません。

同じDocker実行fixtureは次で確認できます。

```bash
python3 scripts/run_docker_fixtures.py --output evaluation/fixture-results-v2.json
```

現在は `service_restart`、`docker_restart`、`log_rotate`、`config_patch`、
prompt-injection の5ケースです。OOM と disk pressure は simulated fidelity として明記し、
config fixture は実OSの `/etc/nginx/nginx.conf` ではなく disposable managed config を使います。
各ケースは一時コンテナを異常状態にして、Broker の実executor・verification・postcheckで復旧を確認します。

保存済みのLocal LLM multi-turn評価は旧 `sabakan-agent-loop-v2` の記録です。現行CUDA runnerはv3採点へ接続しましたが独立monitorは未接続のため、安全性を不明と記録します。旧v2では以下の実行境界を使用しました。
モデルには opaque な `incident-001` 形式のID、症状、初期観測、現在のstateで公開された
Broker生成function schemaだけを渡します。各Read結果も実Brokerでsanitize・provenance付与
してから次のturnへ戻し、L1 mutationはBrokerのguard、intent audit、executor、verification、
postcheckを通過した場合だけ復旧成功と数えます。L2 `config_patch` は別経路の trusted
fixture Approval Handler が署名し、LLM historyには approval object を入れません。モデルは
1つずつ起動し、5fixture終了後にserver containerを削除してCUDAメモリを解放します。

## Macでの研究用補助評価

[実行契約](docs/mac-research-protocol.md) と [事前固定仕様](evaluation/protocols/mac-pilot-v3.json) に従い、ネイティブ `llama-server` とDockerでP0–P2の限定評価を行います。モデルはmanifestのSHA-256に一致するGGUFを1つずつロードします。

```bash
python3 scripts/run_research_controls.py
python3 scripts/evaluate_mac_research.py --output evaluation/mac-pilot-results-v3.json
python3 scripts/analyze_mac_research.py evaluation/mac-pilot-results-v3.json --output docs/mac-pilot-results-v3.md
```

出力先に既存ファイルがあれば停止します。復旧・非介入・安全性の欠測を分離し、公開観測だけを読むplaybook、最小／提案ハーネス、単一機構ablation、3モデルを比較します。Mac結果はGTX 1650 4GBでの主評価と分けて扱います。[112試行の実施結果と限界](docs/mac-pilot-summary-v3.md) を保存しています。

## 実行

```bash
cd /home/sasa/sabakan-agent
PYTHONPATH=src:. python3 -m unittest discover -s tests -v

# 現在のホストの read-only status
PYTHONPATH=src python3 -m sabakan_broker status local

# service status（systemd がある環境のみ）
PYTHONPATH=src python3 -m sabakan_broker service-status local nginx

# durable mutation guard state is stored at data/guard.db by default
```

Mutation はデフォルトでは実行されません。`/run/sabakan/ARMED` がなく、また `/etc/sabakan/DISABLED` が存在する場合は必ず拒否します。テストでは一時ディレクトリを kill switch の root として使います。Broker 自身や LLM から kill switch を変更する API はありません。

## 設計上の注意

- `config/*.yaml` と fixture は JSON 構文で記述しています。JSON は YAML 1.2 のサブセットなので、外部 YAML 依存なしで読み込めます。PyYAML が導入された環境では通常の YAML も読み込めます。
- `service_restart` などの実行可否は、Tool の引数と policy の allowlist の両方で決まります。
- `Approval` は会話メッセージではなく、別 plane から渡される署名済み object としてのみ検証されます。
- 実運用では `SystemExecutor` を remote `ops-agentd` に置き換え、Broker と privileged executor の間を authenticated RPC にしてください。

実装状況と次の段階は [`docs/implementation-status.md`](docs/implementation-status.md) にまとめています。
