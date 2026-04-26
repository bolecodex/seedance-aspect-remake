---
name: seedance-aspect-remake
description: 使用本项目的 seedance-aspect CLI 调用火山方舟 Seedance 2.0，将视频横屏转竖屏或竖屏转横屏。适用于需要长视频拆分、TOS 上传、逐段生成、拼接并保留原音轨的任务。
metadata:
  short-description: Seedance 横竖屏视频转换
---

# Seedance 横竖屏转换

使用 `seedance-aspect` 将本地视频在 `16:9` 与 `9:16` 之间转换。工具会先在本地拆分并压缩参考片段，再批量上传 TOS，随后调用 Seedance 2.0、下载生成片段、对齐时长、拼接，并默认合回原音轨。

## ArkCLaw 安装

在火山 ArkCLaw 环境中安装本技能和 CLI：

```bash
bash <(curl -fsSL https://gitee.com/bolecodex/seedance-aspect-remake/raw/main/scripts/setup-gitee.sh)
```

安装脚本会从 Gitee 拉取仓库，创建虚拟环境，安装 `seedance-aspect`，并同步本中文技能到 `${CODEX_HOME:-$HOME/.codex}/skills/seedance-aspect-remake`。

## 前置检查

```bash
which ffmpeg && which ffprobe
seedance-aspect version
test -n "$ARK_API_KEY"
test -n "$VOLC_ACCESSKEY" && test -n "$VOLC_SECRETKEY" && test -n "$TOS_BUCKET"
```

常用环境变量：

- `ARK_API_KEY`：火山方舟 API Key。
- `ARK_BASE_URL`：默认 `https://ark.cn-beijing.volces.com`。
- `SEEDANCE_MODEL`：推荐 `doubao-seedance-2-0-260128`。如果自定义 endpoint 返回 `AccessDenied`，先切回官方模型名验证权限。
- `VOLC_ACCESSKEY`、`VOLC_SECRETKEY`、`TOS_BUCKET`：TOS 上传配置。

## 一键转换

```bash
seedance-aspect run ./input.mp4 -o ./job --target auto-opposite
```

默认目标：

- 横屏输入转 `9:16`。
- 竖屏输入转 `16:9`。
- 手动指定：`--target 9:16` 或 `--target 16:9`。

追加要求时使用 `--prompt`，但不要改变原视频内容和节奏：

```bash
seedance-aspect run ./input.mp4 -o ./job --target 9:16 \
  --prompt "人物保持在竖屏安全区中间，保留原镜头运动和剪辑节奏。"
```

## 分步恢复

长视频建议分步执行，便于失败后恢复。顺序固定为：先本地处理，再上传 TOS，最后提交 Seedance。

```bash
seedance-aspect split ./input.mp4 -o ./job --target auto-opposite --no-upload
seedance-aspect upload ./job/manifest.json
seedance-aspect remake ./job/manifest.json
seedance-aspect status ./job/manifest.json --refresh
seedance-aspect merge ./job/manifest.json -o ./final.mp4
```

`remake` 可以重复运行。已提交的 `task_id` 会继续轮询；已成功的片段不会重复生成。若 manifest 里有片段还没有 TOS URL，先运行 `upload`。

## 真人素材

Seedance 2.0 对含真人人脸的参考图/视频有官方授权要求。如果视频包含已授权真人素材，优先在火山方舟获取对应素材 ID，并使用 `asset://<asset_id>`。

当每个分段都有授权素材 URI 时：

```bash
seedance-aspect split ./input.mp4 -o ./job --target 9:16 \
  --asset-uris "asset://asset-001,asset://asset-002"
seedance-aspect remake ./job/manifest.json
```

如果审核失败，不要尝试规避审核；应完成官方人像授权流程后重试。更多限制见 `references/seedance-api.md`。

## 排障

- `缺少 ARK_API_KEY`：检查 `.env` 或 shell 环境变量。
- `视频参考模式需要 TOS`：配置 `VOLC_ACCESSKEY`、`VOLC_SECRETKEY`、`TOS_BUCKET`。
- `片段尚未上传 TOS`：先运行 `seedance-aspect upload ./job/manifest.json`。
- `仍有片段未成功，不能拼接`：先运行 `seedance-aspect status ./job/manifest.json --refresh`，再重复运行 `remake`。
- `asset:// 数量必须与片段数量一致`：先不传 `--asset-uris` 跑一次 `split --no-upload` 查看片段数，或按 manifest 片段数补齐 URI。
