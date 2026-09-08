# HTTP部分書込み比較の事前計画

Issue #9/#13に対し、[一時ファイル固定対照](partial-config-file-controls-20260908.md)から、公開観測playbookとSparkの比較へ進める。これは準備記録であり、実モデル試行は未実行。

[計画JSON](../evaluation/protocols/http-partial-write-dev-20260908.json)は既使用のHTTP設定不備ケースを対象とする。clean、部分書込み後の復元、部分書込み後の復元失敗の3条件×2actor×2反復、計12枠。第2反復で6条件の順を逆転する。1モデルロード、最大4500秒、各試行8ターン／300秒、既定guard、fixture別plane署名を使う。人間承認運用は未評価。成功による打切り・再試行・ケース追加をしない。

新しい入口 `scripts/run_http_partial_development.py` が、そのプロセス内の試行中だけHttpExecutorの生成を包み、実体の型を保持したままconfig_pathを観測付きPathに置き換える。主評価で固定したExecutor、Broker、HTTP monitorは変更しない。初回候補のprefixを書き込んでからOSErrorを注入する。復元失敗条件は2回目の書込みだけを拒否し、以後の書込みは通常通り許す。再提案がguardや承認を通れるかは元の実装に従う。実ENOSPCの発生を意味しない。

書込み境界ごとのhash、byte数、検証結果を保存し、元のHTTP monitorが採る変更前後の状態・postcheckと区別する。元から不正な設定へ戻せたことはHTTP復旧ではない。返却mutation flagだけで書込みなしとしない。faultが発動する提案まで到達しなかった試行は、部分適用からの復旧成功ではない。元Executor内部の即時復元と、Brokerの事後検証後のrollbackを別に扱う。

主評価の全block終了・resource cleanup完了と、実際のモデルcontainer不在を起動条件とする。入口と補助コードのhashも計画に固定し、起動時に照合する。主評価の正式解析を先に済ませ、その後に他の追加比較と逐次実行する。

検証: ファイルの実書込み・復元／残留変更・後続書込み、Executorの型維持、例外後の生成関数復元、条件検証の3テストが成功。単体テストはコンテナ登録を空にし、Docker呼出しがあれば失敗させる。最初のテストでは架空containerへ再起動を試みて失敗したため、この検証範囲を明確に修正した。実HTTPとの統合確認は未実行。稼働中の主評価に対するCLI起動拒否も確認し、新規出力・モデル起動がないことを確認した。

```sh
python3 scripts/run_http_partial_development.py --plan evaluation/protocols/http-partial-write-dev-20260908.json --output evaluation/http-partial-write-dev-20260908.json --port 18094
```

解析では全12枠と欠測を保持し、actor・条件・反復を揃えて比較する。承認、実際の書込み、即時復元、残留設定、HTTP復旧、害・境界・計測完全性、停止理由、時間・トークン費用を分離する。単一の既使用ケースから推測統計による一般化は行わない。

入口のhash固定後、全回帰262件が成功。主評価の固定済みsource hashに差分がないことも確認した。

## 終了後の解析

`scripts/analyze_http_partial.py` は終了済みreportだけを受け付け、予定12枠・欠測・重複とactor内のcleanとの差を保存する。初回prefix直後の復元結果を、最終設定と後続書込みから独立させる。後続書込みの生イベント名は観測Pathの試行番号に基づく名前を保持するため、`rollback_write` という名前だけで後続のモデル再提案をBroker rollbackと数えない。Broker rollback回数とconfig Executorの実結果は別欄に保存する。

HTTP復旧・害・境界・approval・停止・部分的な時間計測・トークン欠測は主評価の共通解析関数を使用する。解析ソースhashと入力hashを記録する。部分適用の肯定的な証拠は途中試行でも保持し、復元観測がなければunknownにする。clean条件の空write_eventsは計装を付けないためであり、無書込みの証拠ではない。

解析器の4テストが成功。不正な元設定への復元、初回復元失敗と後続有効書込みの分離、部分証拠と欠測、実行中拒否と12枠の欠測・重複を検証した。

```sh
python3 scripts/analyze_http_partial.py evaluation/http-partial-write-dev-20260908.json --output evaluation/http-partial-write-analysis-20260908.json
```
