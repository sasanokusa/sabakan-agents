# 実HTTP fixtureのモデル実行経路

`evaluation.http_trials.run_http_trial` を追加し、公開観測だけを受け取るchat callbackを、実HTTP fixture、Broker、独立monitor、継続HTTP postcheckに接続した。開発用APIであり、未使用主評価やモデル推論の実施結果ではない。

同じ関数にplaybookとモデルcallbackを渡せる。条件別の段階公開・ヒント・終了文面をplanから受け取り、fixtureの非公開fault名をcallbackへ渡さない。L2はplanで明示したfixture_auto_signatureとunassistedを区別する。正常性はcontainerのrunningだけでなくHTTP応答で判定する。

例外・外側timeoutでも公開入力、取得済み応答、途中trace、監査、monitor、最終HTTP観測、cleanup結果を保存する。未観測の結果を成功や違反0に変換しない。setup失敗はstarted=falseで採点する。

実Dockerの固定対照（モデル推論なし）:

- `evaluation/http-model-path-controls-20260908.json`: 正常系が適切な非介入、設定不備がfixture署名による修復成功。両方で全リソース削除を確認。
- `evaluation/http-model-path-timeout-20260908.json`: 1秒上限でOUTER_TIMEOUT、未復旧として保存し、監査とcleanupを確認。
- 全回帰153件通過。検証ログは `evaluation/http-model-path-validation-20260908.log`。

次はこの経路を、事前固定したモデル用のHTTP開発計画と未使用評価計画へ接続する。既存の稼働状態専用の終了契約をHTTPケースへそのまま適用しない。
