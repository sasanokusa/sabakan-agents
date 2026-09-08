# GTX 1650主評価：事前固定（Issue #9、#10、#12〜#14）

`evaluation/protocols/gtx1650-primary-sequence-20260908.json` と6つの子planを実行前にcommitする。
親planは子planと実行コードのSHA256、56試行の全行列、解析方法、資源上限を固定する。
`scripts/run_primary_sequence.py` は全行列と共通条件を起動前に照合し、各block前にコード変更も検出する。

## 比較とケース

- モデル比較: 同じB2でAgents-A1、Granite、Sparkを比較する。ユーザー指定でLFMをSparkに置換。
  MiniCPMの追加作業は別に保持し、この事前固定比較へ途中追加しない。
- ハーネス比較: SparkについてB0 playbook、B1、B2、stagingなし、hintなしを比較する。
  schemaとhintが実際に入力へ届いたか監査し、露出がなければその機構の効果を推定しない。
- 未使用評価: frontend＋dependency、config＋dependency、frontend＋configの2故障組合せ3件。
  正常1件は既使用reference。2反復で評価42行、reference 14行、計56行。
- 単一故障と3故障の開発対照は使用済み。組合せが新しくても故障族は共通なので、family holdoutではない。
  非介入のreferenceと未使用復旧ケースを一括して未使用評価とは呼ばない。

主評価前の共通runtime確認ではAgentsとGraniteが既知のavailability 2件を各完了した。
Sparkの既知HTTP開発は4件中frontendと設定の復旧・正常非介入を確認し、依存先では失敗した。
互換性と床効果を避けられる見込みに基づく選択であり、主評価で勝つモデルを選んだものではない。

## 実行条件と停止

全モデルQ4_K_M、共通Spark fork revision `4a3635c32fc9f044c2bde9ebeabf50c7e1ec5991`、
runtime library hash固定、context 8192、16層GPU、batch 2048 / microbatch 512、threads 6。
生成上限1024、temperature 0、top_p 1、seed 42、thinking auto/-1。
Toolと権限は共通。複数段階を収めるため全条件12ターンとし、外側300秒は維持する。
元の単一故障開発の8ターン条件との直接速度比較はしない。

第1反復はSpark→Agents→Granite、第2反復は逆順。各block内のcaseとcondition順も逆転する。
Sparkはcaseごとにcondition順を回す。計6ロード、同時モデルは1つ、各8-token warmupは別記録。
request IDやnonceは再利用せず、入力と応答を保存する。

モデルcontainerはRAM 8GiB、CPU quota 4、pids 256。背景GPU処理を維持し、16層以外はCPU。
4GiBへの全層収容を示す実験ではない。OOMや収容失敗も結果に残す。
親の予算は30,000秒、Spark blockは9,000秒、他は2,200秒。超過時は子を停止し、
そのPIDに対応した実験resourceだけを片付ける。残り予算と空き容量512MiBを次block開始前に確認する。
想定記録量は2GiB以内。生成上限は全56行で688,128 tokens。成功による追加・再試行・調整なし。

設定変更はfixtureによる別plane署名が利用可能。人間承認や無支援L2自律復旧とは区別する。
HTTP応答は実際の隔離サービスから独立observerが測り、DNS修正済みfixtureを全条件で使う。
stage直後にまだHTTPが正常でなければ、その失敗を成功へ書き換えない。

## 解析

各caseで2反復を平均して対応差を取る。同一HTTP故障族の3組合せしかないため、
独立した故障族についての信頼区間は推定せずnullと理由を表示する。
case別差とその範囲は記述統計とし、反復を独立incidentとしてbootstrapしない。
成功0・全成功・差0から同等性や無リスクを主張しない。

復旧、害なし復旧、正常非介入、未復旧、escalation、guard、timeout、未開始、計測不明を分ける。
速度比較は同じcase・反復で両者が復旧した対に限定し、除外した対と全試行の労力も併記する。
正常確認や失敗までの時間を復旧時間としない。Tool、モデル呼出し、承認、postcheckは壁時計の区間で分離する。

VRAMはdevice/processサンプルとbaseline、観測間隔・範囲を保存する。0.5秒は採取後の待機時間で、
実際のsample offsetを使う。瞬間peakを保証しない。RAMはinit-process RSSとcgroup値を別記録し、
VRAMと混ぜない。OS、CPU、RAM、driver、runtime、モデルrevision/SHA、prompt/schema/templateを保存する。
ハードウェア以外のcaseやruntimeも変わるため、Macとの数値差をCUDA単独の効果に帰属しない。

解析入力のhash、欠落・重複を機械確認し、失敗したblockや途中traceを欠測ゼロとして補完しない。
旧pilot、開発対照、事前確認はこの主評価に合算しない。
