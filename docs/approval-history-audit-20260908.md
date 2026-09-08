# 承認比較の保存済みLLM入力監査

Issue #13の別Approval Planeに関する確認として、承認7状態×2actorの14試行とrollback成功／snapshot喪失の各2試行、計18試行の保存済みpublic_inputsを調べた。[監査出力](../evaluation/approval-history-audit-20260908.json)に入力ファイルhash、解析コードhash、試行ごとの入力数と検出結果を保存した。

`nonce`、`signature`、`approval_request`、`approval_key`、`signing_key`の構造化フィールドと、既知のfixture署名鍵リテラルは0件だった。Tool message内のJSON文字列もdecodeして確認する。合成の承認要求・nonce・署名を含むJSONと既知fixture鍵が検出され、安全な `APPROVAL_REQUIRED` シグナルだけの入力が該当しないことも確認した。

これは保存済み入力の限定的な監査である。実行中の署名・nonce値そのものは解析用に保存しておらず、値単位の照合や符号化・言い換え・未知の経路の不存在を証明しない。入力欠落は空の入力と区別する。人間承認や本番資格情報を用いた実験ではない。別途、既存の `test_agent_loop_approval_plane_is_not_in_model_history` が生成経路の固定対照を検証する。

```sh
python3 scripts/audit_approval_history.py evaluation/http-approval-comparison-dev-20260908.json evaluation/http-rollback-comparison-dev-20260908.json evaluation/http-rollback-unavailable-comparison-dev-20260908.json --output evaluation/approval-history-audit-20260908.json
```

出力は上書き不可。部分書込み比較が終了したら、その新規reportを別の出力へ監査する。
