---
name: seedance-aspect-remake
description: 使用本项目的 seedance-aspect CLI 调用火山方舟 Seedance 2.0，将视频横屏转竖屏或竖屏转横屏。适用于需要长视频拆分、TOS 上传、逐段生成、拼接并保留原音轨的任务。
metadata:
  short-description: Seedance 横竖屏视频转换
---

# Seedance 横竖屏转换

使用 `seedance-aspect` 将本地视频在 `16:9` 与 `9:16` 之间转换。工具会先按原片切镜拆分，调用 Seedance 2.0 生成，逐段对齐时长、拼接，并默认合回原音轨。含真人人脸的视频应使用私域真人/虚拟人像素材库：账号已开通权限时，可让 CLI 自动把拆好的本地片段上传 TOS、录入 Ark 素材库，等待 `Active` 后以 `asset://<asset_id>` 传给 Seedance。

## ArkCLaw 安装

在火山 ArkCLaw 环境中安装本技能和 CLI：

```bash
bash <(curl -fsSL https://gitee.com/bolecodex/seedance-aspect-remake/raw/main/scripts/setup-gitee.sh)
```

安装脚本会从 Gitee 拉取仓库，创建虚拟环境，安装 `seedance-aspect`，并同步本中文技能到 `${CODEX_HOME:-$HOME/.codex}/skills/seedance-aspect-remake`。

## ArkCLaw 环境变量

优先把配置写到安装目录的 `.env`：

```bash
vim "${SEEDANCE_ASPECT_HOME:-$HOME/.local/share/seedance-aspect-remake}/.env"
```

安装脚本会生成 `.env` 模板。推荐内容：

```bash
ARK_API_KEY="..."
SEEDANCE_MODEL="doubao-seedance-2-0-260128"
VOLC_ACCESSKEY="..."
VOLC_SECRETKEY="..."
TOS_BUCKET="..."
TOS_ENDPOINT="tos-cn-beijing.volces.com"
TOS_REGION="cn-beijing"

# 可选：自动录入 Ark 私域素材库
ARK_ASSET_PROJECT_NAME="default"
ARK_ASSET_GROUP_NAME="seedance-aspect-demo"
ARK_ASSET_POLL_INTERVAL=3
ARK_ASSET_POLL_MAX_WAIT=3600

# 可选：手工素材清单
SEEDANCE_ASSET_MAP="/path/to/assets.json"
```

`TOS_REGION` 是推荐变量名；如果 ArkCLaw 里已有 `OS_REGION`，CLI 也会兼容读取。

配置优先级：已导出的 Shell/ArkCLaw 任务环境变量最高，其次是 `SEEDANCE_ASPECT_ENV` 指定文件、当前项目 `.env`、安装目录 `.env`、开发仓库根目录 `.env`。

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
- `SEEDANCE_ASSET_MAP`：可选，私域人像/视频素材清单路径。
- `ARK_ASSET_PROJECT_NAME`：私域素材库 ProjectName，默认 `default`，需与视频生成 API Key 所属项目一致。
- `ARK_ASSET_GROUP_ID` / `ARK_ASSET_GROUP_NAME`：指定已有素材组，或让 CLI 按名称复用/创建素材组。

## 调用技能示例

用户可以这样要求：

```text
调用 seedance-aspect-remake，把 ./video/demo.mp4 这个横屏短剧转成竖屏剧，保留情节、剪辑节奏和原配音不变。
```

较长视频推荐分步表达：

```text
使用 seedance-aspect-remake 分步处理 ./input.mp4：先 split --no-upload，再 upload，之后 remake，最后 merge 输出 ./final_vertical.mp4。
```

私域真人素材示例：

```text
调用 seedance-aspect-remake，把 ./video/海外剧.mp4 转为 16:9 横屏剧；先把拆好的片段自动录入 Ark 私域素材库，再调用 Seedance；按原片切镜分段，长镜头拆段时用上一段最终尾帧续接，保留原配音。
```

## 一键转换

```bash
seedance-aspect run ./input.mp4 -o ./job --target auto-opposite \
  --split-strategy scene --scene-threshold 0.28 --continuity always \
  --reference-audio --generation-duration-mode auto --alignment-mode trim-pad
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
seedance-aspect split ./input.mp4 -o ./job --target auto-opposite \
  --split-strategy scene --scene-threshold 0.28 --continuity always \
  --reference-audio --generation-duration-mode auto --alignment-mode trim-pad --no-upload
seedance-aspect upload ./job/manifest.json
seedance-aspect remake ./job/manifest.json
seedance-aspect status ./job/manifest.json --refresh
seedance-aspect merge ./job/manifest.json -o ./final.mp4
```

`remake` 可以重复运行。已提交的 `task_id` 会继续轮询；已成功的片段不会重复生成。若 manifest 里有片段还没有 TOS URL，先运行 `upload`。

## 私域真人/虚拟人像素材

Seedance 2.0 不支持直接把含真人人脸的原始参考图/视频传入生成接口。若账号已接入私域真人/虚拟人像素材库，优先使用自动入库流程。

自动录入素材库并一键生成：

```bash
seedance-aspect run ./video/海外剧.mp4 \
  -o ./jobs/海外剧_landscape \
  --target 16:9 \
  --auto-asset-ingest \
  --asset-group-name seedance-aspect-海外剧 \
  --split-strategy scene \
  --scene-threshold 0.28 \
  --continuity always \
  --reference-audio \
  --generation-duration-mode auto \
  --alignment-mode trim-pad \
  --final-output ./jobs/海外剧_landscape/海外剧_横屏.mp4
```

分步流程：

```bash
seedance-aspect split ./video/海外剧.mp4 -o ./jobs/海外剧_landscape \
  --target 16:9 --split-strategy scene --scene-threshold 0.28 \
  --continuity always --reference-audio \
  --generation-duration-mode auto --alignment-mode trim-pad --no-upload
seedance-aspect ingest-assets ./jobs/海外剧_landscape/manifest.json \
  --asset-group-name seedance-aspect-海外剧
seedance-aspect remake ./jobs/海外剧_landscape/manifest.json
seedance-aspect merge ./jobs/海外剧_landscape/manifest.json \
  -o ./jobs/海外剧_landscape/海外剧_横屏.mp4
```

`ingest-assets` 会把每个本地参考片段上传到 TOS，再调用 Ark Assets API 创建 `Video` 类型素材，并轮询到 `Active`。素材失败时不要绕过审核，应检查素材授权、素材组授权函、ProjectName 一致性，以及片段时长、大小、分辨率、FPS 是否满足要求。

对白剧默认使用口型优先策略：参考片段保留原音频，正常长度片段让 Seedance 自动跟随参考时长，下载后只裁剪/补尾不整体变速。这样能减少“声音在 A 身上、口型却跑到 B 身上”的情况。

默认 `--continuity always` 会让每个相邻片段都参考上一段尾帧作为 `first_frame`。工具优先使用上一段经过 `trim-pad` 对齐后的本地最终尾帧；如果抽帧或上传失败，则兜底使用 Seedance 返回的 `last_frame_url`。若 Seedance 拒绝 `first_frame` 与参考视频混用，工具会把尾帧入库到 Ark 私域素材组，再以 `reference_image` 重试。

如果已经手工拿到 Asset ID，也可以用资产清单传入。

资产清单：

```json
{
  "global_references": [
    {"uri": "asset://asset-001", "media_type": "image", "role": "reference_image", "label": "主角"}
  ],
  "segment_references": {
    "12": [
      {"uri": "asset://asset-012", "media_type": "video", "role": "reference_video"}
    ]
  }
}
```

运行示例：

```bash
seedance-aspect run ./video/海外剧.mp4 \
  -o ./jobs/海外剧_landscape \
  --target 16:9 \
  --asset-map ./assets/海外剧.assets.json \
  --split-strategy scene \
  --scene-threshold 0.28 \
  --continuity always \
  --reference-audio \
  --generation-duration-mode auto \
  --alignment-mode trim-pad \
  --final-output ./jobs/海外剧_landscape/海外剧_横屏.mp4
```

`global_references` 会应用到每个片段；`segment_references` 只追加到指定片段。`media_type=image` 默认 `reference_image`，适合私域人像；`media_type=video` 使用 `reference_video`，适合已入库的授权视频素材。旧参数 `--asset-uris` 仍可用，但它按逐段 `reference_video` 兼容处理。

如果审核失败，不要尝试规避审核；应完成官方人像授权流程后重试。更多限制见 `references/seedance-api.md`。

## 镜头连续性

- 默认 `--split-strategy scene`：用 FFmpeg scene score 找原片切镜点，在 15 秒限制内优先切在画面切换处。
- 默认 `--continuity always`：所有相邻片段都会把上一段最终成片尾帧作为下一段 `first_frame`，减少 15 秒分段导致的叙事断裂。
- 工具会先请求 Seedance 返回 `last_frame_url`，但实际续接优先使用对齐后的本地尾帧；只有本地尾帧不可用时才用 API 尾帧兜底。若 `first_frame` 不能与参考视频混用，会自动把尾帧入库为私域图片素材并以 `reference_image` 重试。
- 如需旧的保守行为，可用 `--continuity scene-tail`：只有同一长镜头被迫拆成多段时才续接，原片硬切处不续尾帧；如需关闭，用 `--continuity off`。

## 排障

- `缺少 ARK_API_KEY`：检查 `.env` 或 shell 环境变量。
- `视频参考模式需要 TOS`：配置 `VOLC_ACCESSKEY`、`VOLC_SECRETKEY`、`TOS_BUCKET`。
- `片段尚未上传 TOS`：先运行 `seedance-aspect upload ./job/manifest.json`。
- `仍有片段未成功，不能拼接`：先运行 `seedance-aspect status ./job/manifest.json --refresh`，再重复运行 `remake`。
- `asset:// 数量必须与片段数量一致`：先不传 `--asset-uris` 跑一次 `split --no-upload` 查看片段数，或按 manifest 片段数补齐 URI。
- `没有可用的 asset:// 私域素材`：检查 `--asset-map` 或 `SEEDANCE_ASSET_MAP`，为全局或对应片段补充授权素材。
- `素材未变为 Active`：检查 Ark 私域素材库权限、素材组授权函、ProjectName、TOS URL 可访问性，以及片段是否满足素材库入库规格。
- `口型和声音错位`：重新 split 并确保启用 `--reference-audio --generation-duration-mode auto --alignment-mode trim-pad`；旧任务里的静音素材需要重新入库，不能只重复 `remake`。
