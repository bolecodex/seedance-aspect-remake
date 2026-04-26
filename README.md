# Seedance Aspect

用官方火山方舟 Seedance 2.0 将视频横屏转竖屏、竖屏转横屏。工具会先在本地拆分并压缩参考片段，再批量上传 TOS、逐段生成、对齐时长、拼接，并默认合回原音轨。

## ArkCLaw 一键安装

在火山 ArkCLaw 环境中执行：

```bash
bash <(curl -fsSL https://gitee.com/bolecodex/seedance-aspect-remake/raw/main/scripts/setup-gitee.sh)
```

安装脚本会从 Gitee 拉取本仓库，创建虚拟环境，安装 `seedance-aspect` CLI，并同步中文技能到 `${CODEX_HOME:-$HOME/.codex}/skills/seedance-aspect-remake`。

## ArkCLaw 环境变量放哪里

安装完成后，请把 Ark 与 TOS 环境变量放在安装目录的 `.env` 文件里，这是 ArkCLaw 上最省心的方式：

```bash
vim "${SEEDANCE_ASPECT_HOME:-$HOME/.local/share/seedance-aspect-remake}/.env"
```

安装脚本会自动创建这个文件，内容来自 `.env.example`。它只保存在 ArkCLaw 机器本地，不会被提交到仓库。

推荐填写：

```bash
ARK_API_KEY="..."
SEEDANCE_MODEL="doubao-seedance-2-0-260128"
VOLC_ACCESSKEY="..."
VOLC_SECRETKEY="..."
TOS_BUCKET="..."
TOS_ENDPOINT="tos-cn-beijing.volces.com"
TOS_REGION="cn-beijing"
```

> `TOS_REGION` 是推荐变量名；如果 ArkCLaw 里已有 `OS_REGION`，CLI 也会兼容读取。
> 推荐使用 `SEEDANCE_MODEL=doubao-seedance-2-0-260128`。如果自定义 endpoint 返回 `AccessDenied`，先切回官方模型名验证权限。

配置优先级：

1. Shell 或 ArkCLaw 任务里已经导出的环境变量，优先级最高。
2. `SEEDANCE_ASPECT_ENV=/path/to/.env` 指定的文件，适合临时切换配置。
3. 当前工作目录或父目录中的 `.env`，适合每个项目单独配置。
4. `${SEEDANCE_ASPECT_HOME:-$HOME/.local/share/seedance-aspect-remake}/.env`，适合 ArkCLaw 全局安装。
5. 开发仓库根目录的 `.env`，适合本地调试。

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

## 调用技能示例

在 ArkCLaw/Codex 对话里可以这样说：

```text
调用 seedance-aspect-remake，把 ./video/demo.mp4 这个横屏短剧转成 9:16 竖屏，保留剧情、节奏和原配音不变，输出到 ./job_demo。
```

也可以要求分步执行，方便长视频恢复：

```text
使用 seedance-aspect-remake 分步处理 ./input.mp4：先本地 split，再 upload 到 TOS，再 remake，最后 merge 成 ./final_vertical.mp4。
```
