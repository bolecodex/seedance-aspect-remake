# Seedance Aspect

用官方火山方舟 Seedance 2.0 将视频横屏转竖屏、竖屏转横屏。工具会先在本地拆分并压缩参考片段，再批量上传 TOS、逐段生成、对齐时长、拼接，并默认合回原音轨。

## ArkCLaw 一键安装

在火山 ArkCLaw 环境中执行：

```bash
bash <(curl -fsSL https://gitee.com/bolecodex/seedance-aspect-remake/raw/main/scripts/setup-gitee.sh)
```

安装脚本会从 Gitee 拉取本仓库，创建虚拟环境，安装 `seedance-aspect` CLI，并同步中文技能到 `${CODEX_HOME:-$HOME/.codex}/skills/seedance-aspect-remake`。

安装完成后请自行配置 Ark 与 TOS 环境变量；不要把密钥写入仓库。

```bash
export ARK_API_KEY="..."
export SEEDANCE_MODEL="doubao-seedance-2-0-260128"
export VOLC_ACCESSKEY="..."
export VOLC_SECRETKEY="..."
export TOS_BUCKET="..."
export TOS_ENDPOINT="tos-cn-beijing.volces.com"
export TOS_REGION="cn-beijing"
```

> 推荐使用 `SEEDANCE_MODEL=doubao-seedance-2-0-260128`。如果自定义 endpoint 返回 `AccessDenied`，先切回官方模型名验证权限。

## 本地开发安装

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
cp .env.example .env

seedance-aspect run ./input.mp4 -o ./job --target auto-opposite
```

常用分步命令：

```bash
seedance-aspect split ./input.mp4 -o ./job --target 9:16 --no-upload
seedance-aspect upload ./job/manifest.json
seedance-aspect remake ./job/manifest.json
seedance-aspect merge ./job/manifest.json -o ./final.mp4
seedance-aspect status ./job/manifest.json --refresh
```

需要安装 FFmpeg，并配置 `ARK_API_KEY`、`VOLC_ACCESSKEY`、`VOLC_SECRETKEY`、`TOS_BUCKET`。
