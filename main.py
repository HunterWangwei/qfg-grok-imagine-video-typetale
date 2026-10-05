# -*- coding: utf-8 -*-
"""
QFG Grok Imagine Video 插件。

通过 qfgapi.com 的 New API 网关调用 grok-imagine-video-1.5
和 grok-imagine-video 模型。API Key 由插件设置页保存。
"""

import base64
import mimetypes
import os
import sys
import time
import traceback
from datetime import datetime

import requests

sys.path.append(os.path.dirname(os.path.dirname(__file__)))
from plugin_utils import load_plugin_config


_PLUGIN_FILE = __file__
_BASE_URL = "https://qfgapi.com"
_DEFAULT_PARAMS = {
    "api_key": "",
    "model": "grok-imagine-video-1.5",
    "aspect_ratio": "16:9",
    "duration": "8",
    "resolution": "720p",
    "timeout": 900,
    "max_poll_attempts": 180,
    "poll_interval": 5,
}
_CREATE_ENDPOINT = "/xai/v1/videos/generations"
_POLL_ENDPOINT = "/v1/videos/{task_id}"
_CONTENT_ENDPOINT = "/v1/videos/{task_id}/content"
_SUCCEEDED_STATUSES = {"completed", "success", "succeeded", "done"}
_FAILED_STATUSES = {"failed", "failure", "cancelled", "canceled", "error"}


class PluginFatalError(Exception):
    """表示 API 已返回确定性失败，不应自动重试。"""


def get_info():
    return {
        "name": "QFG Grok Imagine Video",
        "description": (
            "通过 QFG API 调用 grok-imagine-video-1.5 或 "
            "grok-imagine-video 生成视频。"
        ),
        "version": "1.0.0",
        "author": "Custom",
    }


def get_params():
    params = _DEFAULT_PARAMS.copy()
    params.update(load_plugin_config(_PLUGIN_FILE))
    return params


def _as_int(value, default, minimum=None, maximum=None):
    try:
        result = int(value)
    except (TypeError, ValueError):
        result = default
    if minimum is not None:
        result = max(minimum, result)
    if maximum is not None:
        result = min(maximum, result)
    return result


def _get_first_frame(context):
    first_frame = context.get("first_frame_path")
    if first_frame and os.path.isfile(first_frame):
        return first_frame

    reference_images = context.get("reference_images") or {}
    if reference_images and all(isinstance(key, int) for key in reference_images):
        reference_images = {"参考图片MAP": reference_images}

    first_frame = reference_images.get("首帧")
    if first_frame and os.path.isfile(first_frame):
        return first_frame

    reference_map = reference_images.get("参考图片MAP", {})
    if isinstance(reference_map, dict):
        for key in sorted(reference_map):
            candidate = reference_map.get(key)
            if candidate and os.path.isfile(candidate):
                return candidate
    return None


def _image_as_data_url(path):
    """将软件提供的本地首帧编码为 New API 支持的 Data URL。"""
    if not path or not os.path.isfile(path):
        return None

    mime_type = mimetypes.guess_type(path)[0] or "image/png"
    with open(path, "rb") as image_file:
        encoded = base64.b64encode(image_file.read()).decode("ascii")
    return f"data:{mime_type};base64,{encoded}"


def _extract_task_id(response_data):
    if not isinstance(response_data, dict):
        return None
    data = response_data.get("data")
    nested = data if isinstance(data, dict) else {}
    return (
        response_data.get("id")
        or response_data.get("request_id")
        or response_data.get("task_id")
        or response_data.get("video_id")
        or nested.get("id")
        or nested.get("task_id")
    )


def _extract_status(response_data):
    data = response_data.get("data") if isinstance(response_data, dict) else None
    nested = data if isinstance(data, dict) else {}
    status = response_data.get("status") or nested.get("status") or ""
    return str(status).strip().lower()


def _extract_progress(response_data):
    data = response_data.get("data") if isinstance(response_data, dict) else None
    nested = data if isinstance(data, dict) else {}
    value = response_data.get("progress", nested.get("progress"))
    if value is None:
        return None
    try:
        value = float(str(value).rstrip("%"))
        if 0 <= value <= 1:
            value *= 100
        return max(0, min(100, int(value)))
    except (TypeError, ValueError):
        return None


def _extract_video_url(response_data):
    if not isinstance(response_data, dict):
        return None

    candidates = [response_data]
    data = response_data.get("data")
    if isinstance(data, dict):
        candidates.append(data)
        output = data.get("output")
        if isinstance(output, dict):
            candidates.append(output)
    output = response_data.get("output")
    if isinstance(output, dict):
        candidates.append(output)
    video = response_data.get("video")
    if isinstance(video, dict):
        candidates.append(video)

    for item in candidates:
        for key in ("video_url", "url", "output_url", "download_url"):
            value = item.get(key)
            if isinstance(value, str) and value.startswith(("http://", "https://")):
                return value
        value = item.get("output")
        if isinstance(value, str) and value.startswith(("http://", "https://")):
            return value
    return None


def _extract_error(response_data):
    if not isinstance(response_data, dict):
        return "任务生成失败"
    data = response_data.get("data")
    nested = data if isinstance(data, dict) else {}
    error = (
        response_data.get("error")
        or response_data.get("message")
        or response_data.get("fail_reason")
        or nested.get("error")
        or nested.get("message")
        or nested.get("fail_reason")
    )
    if isinstance(error, dict):
        error = error.get("message") or error.get("code")
    return str(error or "任务生成失败")


def _create_task(base_url, headers, payload, timeout):
    endpoint = base_url + _CREATE_ENDPOINT
    print(f"[QFG Grok] 提交任务: {endpoint}")
    return requests.post(endpoint, headers=headers, json=payload, timeout=timeout)


def _download_video(url, output_path, timeout):
    headers = {
        "User-Agent": "Mozilla/5.0",
        "Accept": "*/*",
    }
    with requests.get(url, headers=headers, timeout=timeout, stream=True) as response:
        response.raise_for_status()
        with open(output_path, "wb") as output_file:
            for chunk in response.iter_content(chunk_size=1024 * 1024):
                if chunk:
                    output_file.write(chunk)


def _download_task_content(base_url, task_id, headers, output_path, timeout):
    """当轮询结果未提供视频直链时，使用 New API content 接口下载。"""
    endpoint = base_url + _CONTENT_ENDPOINT.format(task_id=task_id)
    with requests.get(endpoint, headers=headers, timeout=timeout, stream=True) as response:
        response.raise_for_status()
        with open(output_path, "wb") as output_file:
            for chunk in response.iter_content(chunk_size=1024 * 1024):
                if chunk:
                    output_file.write(chunk)


def generate(context):
    print("=" * 60)
    print("[QFG Grok Imagine Video] 开始生成视频")

    params = context.get("plugin_params") or get_params()
    api_key = str(params.get("api_key", "")).strip()
    model = str(params.get("model", _DEFAULT_PARAMS["model"])).strip()
    if model not in {"grok-imagine-video-1.5", "grok-imagine-video"}:
        model = _DEFAULT_PARAMS["model"]

    if not api_key:
        raise Exception("PLUGIN_ERROR:::请先在插件设置中填写 QFG API Key")

    prompt = str(context.get("prompt", "")).strip()
    if not prompt:
        raise Exception("PLUGIN_ERROR:::提示词不能为空")

    timeout = _as_int(params.get("timeout"), 900, 60, 3600)
    max_polls = _as_int(params.get("max_poll_attempts"), 180, 1, 720)
    poll_interval = _as_int(params.get("poll_interval"), 5, 1, 60)
    duration = _as_int(params.get("duration"), 8, 1, 15)
    aspect_ratio = str(params.get("aspect_ratio", "16:9"))
    resolution = str(params.get("resolution", "720p")).lower()
    if resolution not in {"480p", "720p", "1080p"}:
        resolution = "720p"
    if model == "grok-imagine-video" and resolution == "1080p":
        raise Exception("PLUGIN_ERROR:::grok-imagine-video 不支持 1080p，请选择 480p 或 720p")
    progress_callback = context.get("progress_callback")
    base_url = _BASE_URL.rstrip("/")

    payload = {
        "model": model,
        "prompt": prompt,
        "duration": duration,
        "aspect_ratio": aspect_ratio,
        "resolution": resolution,
    }
    first_frame = _get_first_frame(context)
    if first_frame:
        image_data_url = _image_as_data_url(first_frame)
        if not image_data_url:
            raise Exception("PLUGIN_ERROR:::首帧图片读取或 Base64 编码失败")
        payload["image"] = {"url": image_data_url}
        print(f"[QFG Grok] 已添加首帧图片: {first_frame}")

    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }
    print(f"[QFG Grok] 模型: {model}")
    print(f"[QFG Grok] 画幅: {aspect_ratio}，分辨率: {resolution}，时长: {duration}s")
    print(f"[QFG Grok] API Key: 已设置({len(api_key)}字符)")

    try:
        if progress_callback:
            progress_callback("提交任务")

        response = _create_task(base_url, headers, payload, timeout)
        if response.status_code not in (200, 201, 202):
            raise Exception(
                f"PLUGIN_ERROR:::QFG API 错误 {response.status_code}: {response.text[:1000]}"
            )

        response_data = response.json()
        print(f"[QFG Grok] 创建响应: {response_data}")
        video_url = _extract_video_url(response_data)
        task_id = _extract_task_id(response_data)

        if not video_url and not task_id:
            raise Exception("PLUGIN_ERROR:::API 响应中未找到任务 ID 或视频地址")

        if not video_url:
            if progress_callback:
                progress_callback("排队中")
            poll_url = base_url + _POLL_ENDPOINT.format(task_id=task_id)
            print(f"[QFG Grok] 任务 ID: {task_id}")
            for attempt in range(1, max_polls + 1):
                time.sleep(poll_interval)
                status_response = requests.get(poll_url, headers=headers, timeout=timeout)
                if status_response.status_code != 200:
                    print(
                        f"[QFG Grok] 第 {attempt}/{max_polls} 次查询失败: "
                        f"HTTP {status_response.status_code}"
                    )
                    continue

                status_data = status_response.json()
                status = _extract_status(status_data)
                progress = _extract_progress(status_data)
                print(
                    f"[QFG Grok] 第 {attempt}/{max_polls} 次查询: "
                    f"状态={status or '未知'}，进度={progress if progress is not None else '未知'}"
                )

                if status in _FAILED_STATUSES:
                    raise PluginFatalError(f"PLUGIN_ERROR:::{_extract_error(status_data)}")
                if progress_callback:
                    if progress is not None:
                        progress_callback("生成中", progress)
                    elif status in {"queued", "pending"}:
                        progress_callback("排队中")
                    else:
                        progress_callback("生成中")

                video_url = _extract_video_url(status_data)
                if video_url or status in _SUCCEEDED_STATUSES:
                    break
            else:
                raise Exception(f"PLUGIN_ERROR:::等待生成超时（已查询 {max_polls} 次）")

        output_dir = context.get("output_dir") or context.get("project_path") or "."
        os.makedirs(output_dir, exist_ok=True)
        viewer_index = _as_int(context.get("viewer_index"), 0, 0)
        unique_name = str(context.get("unique_name") or "grok")
        generation_round = _as_int(context.get("generation_round"), 0, 0)
        positions = context.get("output_position") or [0]
        position = positions[0] if isinstance(positions, (list, tuple)) and positions else 0
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
        filename = (
            f"{viewer_index:04d}_{unique_name}_{generation_round}_{position}_"
            f"{timestamp}.mp4"
        )
        output_path = os.path.abspath(os.path.join(output_dir, filename))
        if progress_callback:
            progress_callback("下载中")
        if video_url:
            _download_video(video_url, output_path, timeout)
        else:
            print("[QFG Grok] 未返回 video.url，使用 content 接口下载")
            _download_task_content(base_url, task_id, headers, output_path, timeout)

        if progress_callback:
            progress_callback("生成完成", 100)
        print(f"[QFG Grok] 视频已保存: {output_path}")
        print("=" * 60)
        return [output_path]
    except PluginFatalError:
        traceback.print_exc()
        raise
    except Exception as error:
        print(f"[QFG Grok] 生成失败: {error}")
        traceback.print_exc()
        message = str(error)
        if not message.startswith("PLUGIN_ERROR:::"):
            message = f"PLUGIN_ERROR:::{message}"
        raise Exception(message)
