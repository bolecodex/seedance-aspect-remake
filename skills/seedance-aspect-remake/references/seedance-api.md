# Seedance 2.0 API 要点

本项目面向官方火山方舟 Seedance 2.0。

## 接口

- 创建任务：`POST /api/v3/contents/generations/tasks`
- 查询任务：`GET /api/v3/contents/generations/tasks/{task_id}`
- 鉴权：`Authorization: Bearer $ARK_API_KEY`
- 默认 Base URL：`https://ark.cn-beijing.volces.com`

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

授权素材也使用同一个字段：

```json
{
  "type": "video_url",
  "video_url": {"url": "asset://asset-20260222234430-example"},
  "role": "reference_video"
}
```

## 关键限制

- 参考视频：单个 `2-15s`，最多 3 个，总时长不超过 15s。
- 参考视频大小：单个不超过 50MB。
- 参考视频格式：mp4、mov。
- 输出时长：Seedance 2.0 支持 `4-15s` 或 `-1`；本项目使用具体整数秒。
- 输出比例：本项目使用 `9:16` 或 `16:9`。
- 输出音频：本项目设置 `generate_audio: false`，最终用 FFmpeg 合回原始音轨。
- 真人素材：含真人人脸的参考图/视频需走官方授权素材流程，使用 `asset://<asset_id>`。

