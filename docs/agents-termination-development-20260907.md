# Agents-A1の終了契約診断（2026-09-07）

正常確認後の終了契約を明示した開発4件は、復旧2/2、適切な非介入2/2となり、事前の候補選定基準を満たした。主評価・未使用ケースでの性能は未検証である。

`8a5eefb` でplanと文面をcommitした後、既存4ケースを各1回実行。変更はsystem promptへの追記だけで、対象のservice_status/docker_statusがrunningなら正常回答で終了することを明示した。モデル、300秒、8ターン、観測、Tool、Broker、採点は前回と同一。この終了契約はcontainer稼働状態を対象とする当該ケース専用で、HTTPやホスト全体の健康を保証しない。

| ケース | 前回 | 今回 | 経過秒 | Tool数 | 変更数 |
|---|---|---|---:|---:|---:|
| service停止 | 復旧 | 復旧 | 123.2 | 5 | 1 |
| service正常 | 8ターン上限 | 適切な非介入 | 36.0 | 1 | 0 |
| container停止 | 復旧 | 復旧 | 206.6 | 8 | 1 |
| container正常 | 8ターン上限 | 適切な非介入 | 79.1 | 3 | 0 |

4ケースとも、初期HTTP要求の差が宣言したsuffixだけであることを機械検査した。17件のtyped応答はraw/canonical一致、Tool結果15件は次の入力へ到達、変更後に終了した2件は終端未転送、説明不能な未転送は0。2件の通常終了は採点器で受理された。計画行列の欠落・重複は0。

GPUのデバイス全体の観測最大3280MiB、945サンプル。ロード35.9秒、全体518.6秒。既存GPUプロセスは維持され、実験コンテナは削除済み。実験中にユーザー指定のSpark重み取得、依存ツール取得、短いテストとCPUビルド設定生成を実行したため、隔離された速度測定ではない。Sparkのコンパイル開始は本試行サーバー削除後。

生データ `evaluation/agents-termination-dev-20260907.json`、比較解析 `evaluation/agents-termination-analysis-20260907.json`、事前仕様 `evaluation/protocols/agents-termination-dev-20260907.json` を保存。旧結果は上書きしない。再解析は `scripts/analyze_candidate_development.py` に `--baseline evaluation/agents-deadline-dev-20260907.json --comparison prompt_suffix` を指定する。

1反復の開発結果で、因果効果、一般的成功率、機構の有用性を確定しない。今後はこの明示的終了契約を含む共通条件を使い、未使用評価の分割・反復・順序・不確実性を事前固定してから比較する。ユーザー指示によるSpark追加はモデル候補の別変更であり、本結果とは混ぜない。
