# ポケポケ・ひとりでバトル自動操作

USB接続したiPhoneで、ステップアップバトルの初回報酬が未受領の対戦を選び、オートONで繰り返します。

## 実行する

この作業環境では設定済みです。プロジェクトのフォルダで実行します。

```bash
cd pokepoke-auto-worker
bash start.sh
```

起動前にiPhoneをMacにUSB接続し、ロックを解除してください。
Macの「このコンピュータを信頼」や、iPhoneのUI自動操作の許可が求められた場合は許可します。
実行中はiPhoneの画面を点けたままにし、ポケポケを前面にしてください。

初回報酬が未受領のバトルが見つからなくなるまで続けます。
オートONを確認して対戦を開始し、終了後は結果・報酬・新しいバトルの通知を処理して次を探します。

## 停止・再開する

実行しているターミナルで **Ctrl+C** を押すか、別のターミナルで次を実行します。

```bash
cd pokepoke-auto-worker
bash stop.sh
```

停止すると次のバトルへの操作が止まります。進行中のゲーム内オート対戦は続きます。
再開するときは、iPhoneのロックを解除して `bash start.sh` をもう一度実行してください。

## 回数や待ち時間を指定する

```bash
# 10戦で停止する
bash start.sh --max-battles 10

# 1戦の待ち時間上限を20分にする（通常は15分）
bash start.sh --battle-timeout 1200
```

`--max-battles 0` は回数制限なしです。通常の起動もこの設定です。
未対応の画面が60秒続く、通信に失敗する、別アプリが前面になる場合は停止します。

## 初めて別のMacで設定する

必要な環境はmacOS、Xcode、Node.js、Python 3、実機用にビルド・署名済みのWebDriverAgentです。
iPhoneでは開発者モードを有効にしてください。
WebDriverAgentのビルド・署名は別途必要です。このプロジェクトは既存の `.xctestrun` を使います。

```bash
git clone https://github.com/HayatoNabetani/pokepoke-auto-worker.git
cd pokepoke-auto-worker
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
cp config.example.sh config.local.sh
```

`config.local.sh` を編集し、次を設定します。

| 設定 | 指定する内容 |
| --- | --- |
| `IPHONE_UDID` | 操作する実機のUDID |
| `WDA_TESTRUN` | ビルド済みWebDriverAgentの `.xctestrun` の絶対パス |
| `IOS_DEVICE_MODULE` | インストール済み `appium-ios-device` の絶対パス |
| `PYTHON_BIN` | 使用するPython。上記手順では `.venv/bin/python` |
| `NODE_BIN` | 使用するNode.js。通常は `node` |

実機のUDIDは `xcrun xctrace list devices` などで確認できます。
`appium-ios-device` がない場合は `npm install --no-save appium-ios-device` で導入し、
`IOS_DEVICE_MODULE` にこのフォルダ内の `node_modules/appium-ios-device` の絶対パスを指定します。
設定後に `bash start.sh` を実行します。初回は文字認識プログラムのコンパイルに時間がかかります。

## 動かないとき

- 接続待ちになる：USB接続・ロック解除・実機の開発者モードを確認し、`logs/wda.log` を確認します。
- 未対応画面で停止する：`screen.png` と `logs/events.jsonl` を確認します。
- 「既に実行中」と出る：先に `bash stop.sh` を実行します。
- 強制終了後に実行中と表示される：`.runtime/worker.pid` のプロセスが終了していることを確認してから、`.runtime/run.lock` を削除します。

画面認識はiPhone 17の1206×2622画面、ポケポケ1.7.5で確認しています。
異なる画面サイズでは停止します。未受領バトルの選択から勝利・初回報酬受領・一覧復帰までの実機動作を確認済みです。
すべての難易度・エキスパンションでの動作は未検証です。

## Gitに含めない情報

端末識別子や環境固有のパスは `config.local.sh` に保存します。
このファイル、セッションID、画面キャプチャ、ログ、実行状態、仮想環境、署名用ファイルは `.gitignore` で除外します。
テストに含める画像は報酬アイコン周辺だけを切り出したもので、アカウント情報は含みません。

テストは次のコマンドで実行できます。

```bash
python3 -m unittest discover -s tests -v
```
