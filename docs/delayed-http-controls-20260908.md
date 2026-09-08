# 実時間で変化する依存先復旧の対照

Issue #11の正当な待機／無進捗比較に向けて、隔離HTTP fixtureの依存コンテナを5秒後に外部controllerが起動する対照を追加した。読み取り回数で観測列を進めず、controllerの単調時計と実Docker startで状態を変える。モデルやBrokerの復旧操作には帰属させない。

最初の `evaluation/delayed-http-controls-20260908.json` では、起動直後の3点HTTP観測が失敗した。コンテナ起動をHTTP復旧と扱う期待値が不適切だったため、この失敗を保持した。

次の固定対照は `scripts/run_delayed_http_controls.py` で、5秒待機後の早期窓、さらに2秒後の別の3点窓を全条件で取得する。`evaluation/delayed-http-two-window-controls-20260908.json` に両窓を保存した。

| 条件 | 早期HTTP窓 | 後のHTTP窓 | 最終期待値 |
| --- | --- | --- | --- |
| 外部controllerによる遅延起動 | 失敗 | 成功 | 一致 |
| 無進捗、controllerなし | 失敗 | 失敗 | 一致 |

両fixtureのcleanup完了。controller終了後にfixtureを削除する。キャンセルは未発火のstartを止め、すでに発火した場合は最大15秒のDocker呼出しの終了を待つ。二重start、不正な遅延値、外部startの例外を区別する。例外メッセージや実資格情報を計測記録に追加しない。

全201 tests成功。実Docker対照は固定操作であり、まだLLM／Broker guardの閾値比較ではない。正当なポーリング・外部復旧・モデル自身による復旧の帰属を分けて、後続の事前固定比較へ接続する。多段階復旧と閾値採用判断は未完了。
