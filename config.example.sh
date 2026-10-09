# コピー先のconfig.local.shはGit管理されません。
# この3項目を自分の実機・WebDriverAgentに合わせて設定してください。
export IPHONE_UDID=""
export WDA_TESTRUN=""  # ビルド済みWebDriverAgentの.xctestrunファイル
export IOS_DEVICE_MODULE="$HOME/.appium/node_modules/appium-xcuitest-driver/node_modules/appium-ios-device"

# Pythonと依存関係はuvで管理します。
export UV_BIN="uv"
export NODE_BIN="node"
