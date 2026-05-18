# Seedance Aspect

用官方火山方舟 Seedance 2.0 将视频横屏转竖屏、竖屏转横屏。工具会先在本地拆分并压缩参考片段，再批量上传 TOS、逐段生成、对齐时长、拼接，并默认合回原音轨。

对含真人人脸的视频，Seedance 2.0 不支持直接把原始真人参考视频传入生成接口。若账号已开通私域虚拟人像素材库，本工具可以先把本地拆好的 2-15 秒片段上传到 TOS，再调用 Ark Assets API 录入素材库，等待素材变为 `Active` 后自动把 `asset://<asset_id>` 写入 manifest 并提交 Seedance。

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

# 可选：Ark 私域素材库，已开通权限时推荐配置
ARK_ASSET_PROJECT_NAME="default"
ARK_ASSET_GROUP_NAME="seedance-aspect-demo"
ARK_ASSET_POLL_INTERVAL=3
ARK_ASSET_POLL_MAX_WAIT=3600

# 可选：如果已经有手工维护的私域素材清单
SEEDANCE_ASSET_MAP="/path/to/assets.json"
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
seedance-aspect split ./input.mp4 -o ./job --target 9:16 \
  --split-strategy scene --scene-threshold 0.28 --continuity always --no-upload
seedance-aspect upload ./job/manifest.json
seedance-aspect remake ./job/manifest.json
seedance-aspect merge ./job/manifest.json -o ./final.mp4
seedance-aspect status ./job/manifest.json --refresh
```

需要安装 FFmpeg，并配置 `ARK_API_KEY`、`VOLC_ACCESSKEY`、`VOLC_SECRETKEY`、`TOS_BUCKET`。

## 私域人像资产

### 自动录入素材库

账号已接入私域虚拟人像素材库时，推荐直接使用自动入库流程，不需要手工编写 `assets.json`：

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

分步执行时顺序为：

```bash
seedance-aspect split ./video/海外剧.mp4 \
  -o ./jobs/海外剧_landscape \
  --target 16:9 \
  --split-strategy scene \
  --scene-threshold 0.28 \
  --continuity always \
  --reference-audio \
  --generation-duration-mode auto \
  --alignment-mode trim-pad \
  --no-upload

seedance-aspect ingest-assets ./jobs/海外剧_landscape/manifest.json \
  --asset-group-name seedance-aspect-海外剧

seedance-aspect remake ./jobs/海外剧_landscape/manifest.json
seedance-aspect merge ./jobs/海外剧_landscape/manifest.json \
  -o ./jobs/海外剧_landscape/海外剧_横屏.mp4
```

`ingest-assets` 会复用或创建素材组，逐段创建 `Video` 类型素材，并轮询 `GetAsset` 到 `Active`。如果素材状态变成 `Failed`，CLI 会把失败原因写入 manifest；这通常需要检查素材授权、素材组授权函、ProjectName 是否一致，或视频片段是否满足尺寸、时长、大小和 FPS 要求。

对白剧建议保持默认的 `--reference-audio`、`--generation-duration-mode auto` 和 `--alignment-mode trim-pad`：

- `--reference-audio` 会让参考片段保留原音频，帮助模型判断谁在说话以及口型节奏；最终成片仍使用原音轨。
- `--generation-duration-mode auto` 会把正常长度片段的 `duration` 设为 `-1`，让 Seedance 尽量跟随参考视频时长。
- `--alignment-mode trim-pad` 下载后只裁剪多余尾部或补最后一帧，不整体变速，避免口型被压缩或拉伸。
- 默认 `--continuity always` 会把上一段最终对齐成片的尾帧作为下一段 `first_frame`，帮助 15 秒分段处延续叙事。若本地抽帧或上传失败，会兜底使用 Seedance 返回的 `last_frame_url`；若接口拒绝 `first_frame` 与参考视频混用，工具会把尾帧入库为 Ark 私域图片素材，再以 `reference_image` 重试。

相关环境变量：

- `ARK_ASSET_PROJECT_NAME`：素材库 ProjectName，默认 `default`，需要与视频生成 API Key 所属项目一致。
- `ARK_ASSET_GROUP_ID`：可选，指定已有素材组 ID。
- `ARK_ASSET_GROUP_NAME`：可选，未指定素材组 ID 时自动复用或创建该名称的素材组。
- `ARK_ASSET_BASE_URL`：默认 `https://open.volcengineapi.com`。
- `ARK_ASSET_POLL_INTERVAL`、`ARK_ASSET_POLL_MAX_WAIT`：素材入库轮询间隔和最长等待秒数。

### 手工素材清单

资产清单示例：

```json
{
  "global_references": [
    {
      "uri": "asset://asset-xxxxxxxx",
      "media_type": "image",
      "role": "reference_image",
      "label": "主角"
    }
  ],
  "segment_references": {
    "12": [
      {
        "uri": "asset://asset-yyyyyyyy",
        "media_type": "video",
        "role": "reference_video",
        "label": "第12段授权视频素材"
      }
    ]
  }
}
```

- `global_references` 会应用到每个片段。
- `segment_references` 只追加到指定片段。
- `media_type=image` 默认 `role=reference_image`，适合真人/虚拟人像资产。
- `media_type=video` 使用 `role=reference_video`，适合已入库的授权视频素材。
- `assets/*.json` 默认被 `.gitignore` 忽略，不要把私域素材清单提交到仓库。

已有 `asset://` 素材时可以继续使用素材清单：

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

默认 `always` 会对所有相邻片段续接：工具先让 Seedance 返回 `last_frame_url`，再优先从上一段经过 `trim-pad` 对齐后的本地成片抽取真实尾帧并上传 TOS，作为下一段首帧传给 Seedance；只有本地尾帧不可用时才使用 API 返回尾帧兜底。若接口拒绝 `first_frame` 与参考视频混用，工具会把尾帧图片录入同一 Ark 素材组，改用私域 `reference_image` 重试。若需要旧的保守行为，可用 `--continuity scene-tail`，它只在同一长镜头被 15 秒限制硬切时续接，原片硬切处不续尾帧；如需关闭，用 `--continuity off`。

## 调用技能示例

在 ArkCLaw/Codex 对话里可以这样说：

```text
调用 seedance-aspect-remake，把 ./video/demo.mp4 这个横屏短剧转成 9:16 竖屏，保留剧情、节奏和原配音不变，输出到 ./job_demo。
```

也可以要求分步执行，方便长视频恢复：

```text
使用 seedance-aspect-remake 分步处理 ./input.mp4：先本地 split，再 upload 到 TOS，再 remake，最后 merge 成 ./final_vertical.mp4。
```

真人素材示例：

```text
调用 seedance-aspect-remake，把 ./video/海外剧.mp4 转为 16:9 横屏剧；先把拆好的片段自动录入 Ark 私域素材库，再调用 Seedance；每个相邻片段用上一段最终尾帧作为下一段首帧，保留原配音。
```
