# 実OOM・ENOSPCの開発用対照（2026-09-07）

Issue #15に対して、モデル推論を使わない実障害2件を追加した。
実行は `python3 scripts/run_resource_fault_controls.py --output <新規JSON>`。
既存出力への上書きは拒否する。

| 対照 | 実測結果 |
|---|---|
| cgroup OOM | 64MiB、追加swapなしで実際にOOMKilled=true、exit 137。Broker再起動後も再発 |
| 専用tmpfs容量不足 | 1MiB領域で実際にerrno 28。Brokerの固定ログ解放後、独立した書込み3回が成功し、保護データのSHA256は不変 |

OOMの最初の再起動はBrokerの瞬間的なrunning確認では `MUTATION_VERIFIED` になったが、その後の独立観測では再度OOM停止した。したがってこの結果を復旧成功と数えてはいけない。負荷トリガーを**実験側が明示的に除去した後**の2回目のBroker再起動では、0.5秒間隔の3観測と別プロセス起動を確認した。これは自律的な原因除去の成功ではない。

全コンテナはnetwork=none、read-only root、非root、cap-drop ALL、no-new-privileges、64MiB RAM、0.25 CPU、32 PIDで制限した。最終記録ではDocker inspectの実設定を検査した。ホストディスクを埋めず、専用tmpfsの固定ログのみを切り詰めた。後片付け後の対象コンテナ残数は0。

記録:

- `evaluation/resource-fault-controls-20260907.json`: 初回実測、2件とも期待結果に一致。
- `evaluation/resource-fault-controls-verified-20260907.json`: 実行制限の検査を追加した最終実測、2件とも一致。Broker応答、監査、独立観測、ソースhash、イメージdigestを保存。
- `evaluation/resource-fault-validation-20260907.log`: 全回帰テストのログ。

これは開発用固定対照であり、未使用評価ケース、LLM比較、長時間の再発監視、ホスト全体のメモリ／ディスク復旧を示さない。旧simulated結果はそのまま保持した。主評価に組み込むには、観測window付きの復旧判定、同一初期症状からの診断、公開Tool経由の原因観測を整備し、収集前にprotocolを凍結する必要がある。
