# QFG Grok Imagine Video 插件

用于字字动画（TypeTale）的自定义视频模型插件。插件通过 QFG API 的 New API 兼容接口生成 Grok Imagine Video 视频，支持：

- `grok-imagine-video-1.5`
- `grok-imagine-video`

## 功能

- 在插件设置页输入并本地保存 QFG API Key。
- QFG API 地址固定为 `https://qfgapi.com`，不可修改。
- 可设置模型、画幅比例、视频时长和分辨率。
- 支持异步任务创建、状态轮询、进度回调和视频下载。
- 成功后将 MP4 保存到当前项目输出目录。

## 安装

将整个 `qfg_grok_imagine_video` 文件夹复制到字字动画安装目录：

```text
_internal/plugins/video_plugins/qfg_grok_imagine_video/
```

目录结构应如下：

```text
qfg_grok_imagine_video/
├── main.py
└── ui/
    └── index.html
```

然后在软件的“视频模型管理”页面：

1. 点击“自定义插件”。
2. 选择 `QFG Grok Imagine Video`。
3. 打开插件设置，填写 QFG API Key。
4. 选择模型与生成参数后开始生成。

如果软件已在运行，点击“刷新插件列表”或重启软件。

## API 调用

插件按 New API xAI 视频插件的官方格式调用 QFG：

```text
POST https://qfgapi.com/xai/v1/videos/generations
GET  https://qfgapi.com/v1/videos/{request_id}
GET  https://qfgapi.com/v1/videos/{request_id}/content
```

创建任务请求包含：

```json
{
  "model": "grok-imagine-video-1.5",
  "prompt": "A cinematic shot of a city at sunset",
  "duration": 8,
  "aspect_ratio": "16:9",
  "resolution": "720p"
}
```

认证使用：

```text
Authorization: Bearer YOUR_QFG_API_KEY
```

## 参数说明

| 参数 | 说明 |
| --- | --- |
| API 地址 | 固定为 `https://qfgapi.com` |
| API Key | 在 QFG 获取的用户令牌，仅保存到本机插件配置 |
| 模型 | `grok-imagine-video-1.5` 或 `grok-imagine-video` |
| 画幅比例 | `16:9`、`9:16`、`1:1` |
| 视频时长 | 1 至 15 秒，默认 8 秒 |
| 分辨率 | `480p`、`720p`、`1080p`；经典 `grok-imagine-video` 不支持 `1080p` |

## 图片输入限制

New API 官方格式的 `reference_images` 需要提供公网可访问的图片 URL。字字动画当前传给插件的是本地首帧路径，插件不会把本地文件上传到第三方图床，因此当前版本按文生视频提交任务。

## 安全说明

- 不要把 API Key 提交到 Git 仓库、日志、截图或公开讨论中。
- API Key 由字字动画保存到本机 `user_resources/plugins/video_plugins/qfg_grok_imagine_video/config.json`。
- 本插件与 QFG 及 xAI 没有官方合作关系。账户权限、可用模型、计费规则和内容限制以 QFG 实际服务为准。

## 参考

- [New API xAI Video Plugin](https://github.com/HunterWangwei/new-api-xai-video-plugin/)
