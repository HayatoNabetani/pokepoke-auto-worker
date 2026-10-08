# コピー先のconfig.local.shはGit管理されません。
# この3項目を自分の実機・WebDriverAgentに合わせて設定してください。
export IPHONE_UDID=""
export WDA_TESTRUN=""  # ビルド済みWebDriverAgentの.xctestrunファイル
export IOS_DEVICE_MODULE="$HOME/.appium/node_modules/appium-xcuitest-driver/node_modules/appium-ios-device"

# Python仮想環境を使う場合。既存環境を使う場合はpython3に変更できます。
export PYTHON_BIN="$PWD/.venv/bin/python"
export NODE_BIN="node"
