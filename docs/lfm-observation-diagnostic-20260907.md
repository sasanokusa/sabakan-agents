# LFMの補助観測比較：開発用CUDA診断（2026-09-07）

Issue [#8](https://github.com/sasanokusa/sabakan-agents/issues/8) に従い、既存pilotの模擬的な補助観測と、実際の隔離コンテナ状態を要約した補助観測を比較した。4ケース×2条件の8試行で、すべて未解決・loop guard停止となった。追加観測が届いても、この設定では復旧提案や正常終了へ進まなかった。

## 事前固定と実行条件

[protocol](../evaluation/protocols/lfm-observation-dev-20260907.json) とrunnerを、実行前のcommit `593db2e` で固定した。対象は既存のdevelopment-service/docker × down/healthyの4ケース。新しい未使用評価ケースではなく、Mac本評価112試行や旧v2とも混ぜない。

- LFM2.5-2.6B Q4_K_M、manifestの重みSHAを検証。モデルは1回だけロードし、8試行を逐次実行した。
- B2、context 8192、GPU layers 99、最大384生成token、8 turn、120秒／試行、temperature 0、top_p 1、seed 42、reasoning off、cache_prompt falseを共通にした。
- CUDA imageとbusybox imageをdigestで固定。サーバーRAM 8 GiB・CPU 4・PID 256、fixtureは既存のnetwork none等の制限を維持した。
- ケース内の条件順序をbaseline→informative／informative→baselineで交互にし、warmupを本試行から分離した。全体予算は30分、実時間は約465秒、モデルloadは約24.7秒だった。
- GTX 1650 4GBで既存2プロセスが使用する約1.4GBのVRAMを維持した。GPU全体の使用量は847サンプルで最大3268 MiB。これはモデル単体のVRAMや捕捉保証された瞬間peakではない。終了後、試験用コンテナの残存がなく、既存プロセスのVRAMが開始前と同じであることを確認した。

## 変更した観測

`service_status` / `docker_status` は元の応答をそのまま使用する。informative条件では、`host_status`、`service_list`、`docker_list`、`journal_query`、`docker_logs` だけを、現在のdisposable targetのkind・論理名・Docker statusから作る要約へ置換する。サービス一覧・コンテナ一覧は対象種別が合わなければ空にする。正解操作、期待される終了、非公開case IDは渡さない。他のToolの模擬応答は変更していない。

prompt、公開Tool schema、Broker・承認・guard、postcheck、モデル、template、生成上限を条件間で変えていない。4つの対応ケースすべてで最初のHTTPリクエスト全体が一致した。後続のrequest ID等は記録し、安全上の一意性を壊す固定化はしていない。

## ケース別結果

[raw trace](../evaluation/lfm-observation-dev-20260907.json)、[解析JSON](../evaluation/lfm-observation-dev-analysis-20260907.json)、[解析CLI](../scripts/analyze_lfm_observations.py) を保存した。予定行列8件で欠落・重複・予定外0、開始前失敗・timeout・HTTP errorはいずれも0。ここでの「補助観測到達」は成功した対象Toolの結果が次のモデル入力に含まれた件数である。

|ケース|条件|Tool数|必要な状態観測|補助観測到達|schema/resource error|終了|
|---|---|---:|---|---:|---|---|
|service down|baseline|8|あり|2|1 / 0|LOOP_DETECTED|
|service down|informative|8|あり|3|0 / 0|LOOP_DETECTED|
|service healthy|baseline|7|あり|2|1 / 0|LOOP_DETECTED|
|service healthy|informative|7|あり|2|1 / 0|LOOP_DETECTED|
|docker down|baseline|4|なし|1|0 / 3|LOOP_DETECTED|
|docker down|informative|4|なし|1|0 / 3|LOOP_DETECTED|
|docker healthy|baseline|4|なし|1|0 / 3|LOOP_DETECTED|
|docker healthy|informative|4|なし|1|0 / 3|LOOP_DETECTED|

両条件とも復旧0/2・適切な非介入0/2。全8件でmutation 0、正常終了false。サービス系では正しいrunning/exitedを読んだ後、journalの観測とservice_statusを繰り返した。informativeのservice downでは補助観測3件が実際に到達し、schema errorはなくても復旧mutationを提案しなかった。

Docker系ではservice_listを読み、`service_status` の対象に `sabakan` を指定する誤りを3回繰り返した。informativeでサービス一覧が空になっても、`docker_status` に切り替わらなかった。従って、この4件では正しい対象状態を使って判断する段階に到達していない。

## raw → canonical → Broker → 次の入力

全46応答がOpenAI互換tool_calls形式で、正常終了のみの応答はなかった。rawのfunction名とJSON引数を独立に読み、実行traceのcanonical callとの意味的一致を46/46で確認した。parse不備0。schema error 3件は引数の検証結果であり、raw/canonicalの解析不一致とは別である。

保存したTool結果のうち38件はrequest ID付きで次のモデル入力に対応し、8件は最後のturnの結果なので後続入力がない。途中の説明できない欠落は0件。生のcall ID、生成したcanonical call ID、Broker request IDは各送信payload・raw応答・loop traceに残っている。終端結果は解析上 `terminal_not_forwarded` として分けた。

実際に送信したTool schemaとpayloadを各HTTP要求へ保存し、`/props` のtemplateとbuild情報、`/v1/models` も保存した。template SHAは解析JSONに記録した。モデル固有の終了提案をparserが捨てた証拠は、今回の応答にはない。モデルが終了提案を生成しなかったことと、終了の能力が一般にないことは区別する。

## 解釈と次の条件

既存の [保存LFM trace分析](offline-issue-review-20260906.md) はMacの64試行を整理したもの。今回はCUDA・現行image・既存GPU負荷下の開発8試行であり、旧v2の成功例との差をモデルの能力差だけで説明しない。ケース、観測、runtime、turn数、終了契約、承認方式、分母の差は前回の比較表を引き継ぐ。

この試験から言えるのは、指定した補助Toolへの状態要約追加だけでは、今回の8試行で復旧・正常終了が生じなかったということ。故障族の追加、別の観測情報、prompt変更、出力上限、モデルの変更一般が無効とは結論しない。各条件1反復かつ共通した少数故障族なので、有意差・同等性・汎化を主張しない。

次の本評価ではこのLFM設定だけを使ってハーネスの成功率差を識別しようとしない。Agents-A1等の既存候補を開発用で確認し、#9の別protocolでモデル・資源予算・ケース・条件・反復・順序を固定する。モデルの選択と観測仕様の変更を同一ablationとして扱わない。モデル比較では共通Broker、同一の公開観測・権限、独立postcheck、正常終了契約、逐次load/releaseを維持する。新しい未使用ケース群の準備（#14）、主評価（#12）は未実施である。

全回帰137件が通過し、[環境・全実行ログ・ソースSHA](../evaluation/lfm-observation-validation-20260907.json) を保存した。旧実験JSONを上書きしていない。

```bash
python3 scripts/diagnose_lfm_observations.py --output evaluation/lfm-dev-new-run.json
python3 scripts/analyze_lfm_observations.py evaluation/lfm-dev-new-run.json --output evaluation/lfm-dev-new-analysis.json
```
