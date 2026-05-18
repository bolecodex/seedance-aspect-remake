# Seedance 2.0 API 要点

本项目面向官方火山方舟 Seedance 2.0。

## 接口

- 创建任务：`POST /api/v3/contents/generations/tasks`
- 查询任务：`GET /api/v3/contents/generations/tasks/{task_id}`
- 鉴权：`Authorization: Bearer $ARK_API_KEY`
- 默认 Base URL：`https://ark.cn-beijing.volces.com`

## 私域素材库接口

账号已开通私域真人/虚拟人像素材库时，本项目使用 Ark Assets API 自动入库：

- `CreateAssetGroup`：创建或复用素材组，当前使用 `GroupType=AIGC`。
- `CreateAsset`：把 TOS 公网 URL 录入为 `Video` 素材。
- `GetAsset`：轮询素材状态，只有 `Active` 后才写入 `asset://<asset_id>` 并传给 Seedance。

相关配置：

- `VOLC_ACCESSKEY`、`VOLC_SECRETKEY`：用于 Ark Assets API 签名，也用于 TOS 上传。
- `ARK_ASSET_PROJECT_NAME`：默认 `default`，需和视频生成 API Key 所属项目一致。
- `ARK_ASSET_GROUP_ID` 或 `ARK_ASSET_GROUP_NAME`：指定素材组。

## 默认模型

- `doubao-seedance-2-0-260128`
- 可用 `SEEDANCE_MODEL` 或 CLI `--model` 覆盖。

## 请求结构

视频参考模式使用：

```json
{
  "model": "doubao-seedance-2-0-260128",
  "content": [
    {"type": "text", "text": "保持原视频动作、镜头、节奏不变，仅调整构图比例。"},
    {
      "type": "video_url",
      "video_url": {"url": "https://bucket.tos-cn-beijing.volces.com/segment.mp4"},
      "role": "reference_video"
    }
  ],
  "ratio": "9:16",
  "duration": 12,
  "resolution": "720p",
  "watermark": false,
  "generate_audio": false
}
```

授权视频素材使用同一个视频字段：

```json
{
  "type": "video_url",
  "video_url": {"url": "asset://asset-20260222234430-example"},
  "role": "reference_video"
}
```

私域真人/虚拟人像素材通常作为参考图：

```json
{
  "type": "image_url",
  "image_url": {"url": "asset://asset-20260222234430-example"},
  "role": "reference_image"
}
```

连续片段可把上一段最终尾帧作为下一段首帧：

```json
{
  "type": "image_url",
  "image_url": {"url": "https://bucket.tos-cn-beijing.volces.com/tail.png"},
  "role": "first_frame"
}
```

提交任务时设置：

```json
{"return_last_frame": true}
```

## 关键限制

- 参考视频：单个 `2-15s`，最多 3 个，总时长不超过 15s。
- 参考视频大小：单个不超过 50MB。
- 参考视频格式：mp4、mov。
- 输出时长：Seedance 2.0 支持 `4-15s` 或 `-1`；对白剧优先使用 `-1` 让模型跟随参考视频时长。
- 输出比例：本项目使用 `9:16` 或 `16:9`。
- 输出音频：本项目设置 `generate_audio: false`，最终用 FFmpeg 合回原始音轨；参考视频片段默认保留原音频用于口型和说话人判断。
- 时长对齐：默认裁剪/补尾，不整体变速，避免口型节奏被压缩或拉伸。
- 尾帧：`return_last_frame: true` 后，查询结果可能返回 `content.last_frame_url`。本项目记录该 URL，但连续性续接优先使用最终 trim/pad 后的本地尾帧；若 `first_frame` 与参考视频不能混用，会将尾帧入库为 Ark 私域图片素材并以 `reference_image` 重试。
- 真人素材：含真人人脸的参考图/视频需走官方授权素材流程，使用私域素材 `asset://<asset_id>`；不要尝试规避官方审核。
