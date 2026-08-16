#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
detect.py — AI 打假侦探：数字内容「人机验真」编排器（纯真实云端调用）

一条命令，对图片 / 视频 / 文本做「是不是 AI 生成」的真实检测：

  图片 → ims ImageModeration(IMAGE_AIGC)，可选 faceid DetectAIFakeFaces 人脸专项
  视频 → vm CreateVideoModerationTask → 轮询 DescribeTaskDetail（异步两段式）
  文本 → tms TextModeration(TEXT_AIGC)
  可选 → VITA 多模态交叉验证（找"物理破绽"）

所有检测都走腾讯云真实 API，未配置密钥时直接报错，不做本地降级。

用法：
  python detect.py image  <图片路径或URL> [--face] [--vita]
  python detect.py video  <视频URL>          [--face]
  python detect.py text   <文本或文件路径>    [--vita]
  python detect.py auto   <任意输入>
  python detect.py check  # 检查配置就绪状态
"""

import argparse
import base64
import json
import os
import ssl
import sys
import time
from urllib import request, error

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import tc_api


# ---------------------------------------------------------------------------
# 模态分流
# ---------------------------------------------------------------------------

IMAGE_EXTS = {".png", ".jpg", ".jpeg", ".bmp", ".gif", ".webp"}
VIDEO_EXTS = {".mp4", ".mov", ".avi", ".flv", ".webm"}
TEXT_EXTS = {".txt", ".md", ".json", ".csv", ".log"}


def guess_modality(value):
    """根据扩展名或 URL 后缀猜测模态。返回 image/video/text/unknown。"""
    v = value.lower().split("?")[0]
    ext = os.path.splitext(v)[1]
    if ext in IMAGE_EXTS:
        return "image"
    if ext in VIDEO_EXTS:
        return "video"
    if ext in TEXT_EXTS:
        return "text"
    if v.startswith("http://") or v.startswith("https://"):
        return "unknown"
    if os.path.isfile(value):
        try:
            with open(value, "rb") as f:
                head = f.read(64)
            if b"\x00" in head:
                return "unknown"
            return "text"
        except OSError:
            return "unknown"
    return "text"


def read_text_input(value):
    """文本输入：直接文本或文件路径。"""
    if os.path.isfile(value):
        with open(value, "r", encoding="utf-8", errors="ignore") as f:
            return f.read()
    return value


def image_to_base64(path):
    """本地图片转 base64。"""
    if not os.path.isfile(path):
        return None
    with open(path, "rb") as f:
        return base64.b64encode(f.read()).decode("utf-8")


# ---------------------------------------------------------------------------
# 单模态检测（纯云端）
# ---------------------------------------------------------------------------

def _require_credentials():
    if not tc_api.get_credentials():
        return {"error": "CREDENTIALS_NOT_CONFIGURED",
                "hint": "请配置 TENCENTCLOUD_SECRET_ID/KEY（或 .env），见 .env.example"}
    return None


def detect_image(path_or_url, use_face=False, use_vita=False):
    """图片真实云端检测。直接透传腾讯云原始字段（suggestion/label/score）。"""
    is_url = path_or_url.startswith(("http://", "https://"))

    miss = _require_credentials()
    if miss:
        return miss

    biz_type = os.getenv("TENCENTCLOUD_AIGC_RECOG_IMAGE_BIZ_TYPE", "").strip()
    if is_url:
        result = tc_api.detect_image_aigc(image_url=path_or_url, biz_type=biz_type or None)
    else:
        b64 = image_to_base64(path_or_url)
        if b64 is None:
            return {"error": "FILE_NOT_FOUND", "input": path_or_url}
        result = tc_api.detect_image_aigc(image_base64=b64, biz_type=biz_type or None)

    # 附上模态与输入信息，其余字段（suggestion/label/score/detail_results/request_id）原样透传
    result["modality"] = "image"
    result["input"] = path_or_url

    if use_face and not is_url:
        b64 = image_to_base64(path_or_url)
        if b64:
            result["faceid_antifake"] = tc_api.detect_ai_fake_faces(b64, face_input_type=1)

    if use_vita:
        result["vita_crosscheck"] = vita_crosscheck_image(path_or_url, is_url)

    return result


def detect_video(url, use_face=False):
    """视频真实云端检测（异步两段式）。直接透传腾讯云原始字段。"""
    miss = _require_credentials()
    if miss:
        return miss

    biz_type = os.getenv("TENCENTCLOUD_AIGC_RECOG_VIDEO_BIZ_TYPE", "").strip()
    created = tc_api.create_video_aigc_task(url, biz_type=biz_type or None)

    # 创建任务后轮询结果
    detail = None
    task_id = created.get("task_id")
    if task_id:
        for _ in range(30):
            detail = tc_api.query_video_aigc_task(task_id)
            if detail.get("status") in ("FINISH", "ERROR", "CANCELLED"):
                break
            time.sleep(3)

    # 直接透传腾讯云原始字段（suggestion/label/score 等）
    result = detail if detail else created
    result["modality"] = "video"
    result["input"] = url
    if use_face:
        result["faceid_antifake"] = {
            "error": "视频人脸防护盾需 base64 输入，URL 场景请先下载视频"}
    return result


def detect_text(text_or_path, use_vita=False):
    """文本真实云端检测。直接透传腾讯云原始字段。"""
    text = read_text_input(text_or_path)

    miss = _require_credentials()
    if miss:
        return miss

    biz_type = os.getenv("TENCENTCLOUD_AIGC_RECOG_TEXT_BIZ_TYPE", "").strip()
    result = tc_api.detect_text_aigc(text, biz_type=biz_type or None)

    result["modality"] = "text"
    result["input"] = text_or_path

    if use_vita:
        result["vita_crosscheck"] = {"note": "文本态 VITA 交叉验证暂未实现"}

    return result


# ---------------------------------------------------------------------------
# VITA 多模态交叉验证（真实调用）
# ---------------------------------------------------------------------------

VITA_BASE_URL = "https://api.vita.cloud.tencent.com/v1/video2text"
VITA_MODEL = "youtu-vita"
VITA_PROMPT = ("请检查这张图片是否由 AI 生成，重点观察以下物理破绽：手指数量异常、"
               "光影方向矛盾、透视不一致、文字乱码或笔画错误、纹理过度平滑。"
               "请给出判断结论和依据。")


def vita_crosscheck_image(path_or_url, is_url):
    """用 VITA 多模态模型对图片做交叉验证（真实调用）。"""
    api_key = os.getenv("TENCENTCLOUD_VITA_API_KEY", "").strip()
    if not api_key:
        return {"error": "VITA_NOT_CONFIGURED",
                "note": "设置 TENCENTCLOUD_VITA_API_KEY 后自动启用"}
    # 构造图片内容：URL 或本地 base64 data URL
    if is_url:
        image_content = {"type": "image_url", "image_url": {"url": path_or_url}}
    else:
        ext = os.path.splitext(path_or_url)[1].lower().lstrip(".")
        mime = {"jpg": "image/jpeg", "jpeg": "image/jpeg", "png": "image/png",
                "webp": "image/webp"}.get(ext, "image/jpeg")
        b64 = image_to_base64(path_or_url)
        if not b64:
            return {"error": "FILE_NOT_FOUND", "input": path_or_url}
        image_content = {"type": "image_url",
                         "image_url": {"url": f"data:{mime};base64,{b64}"}}

    payload = json.dumps({
        "model": VITA_MODEL,
        "messages": [{"role": "user", "content": [image_content, {"type": "text", "text": VITA_PROMPT}]}],
        "stream": False,
    }, ensure_ascii=False)

    req = request.Request(VITA_BASE_URL + "/chat/completions", data=payload.encode("utf-8"),
                          headers={"Authorization": f"Bearer {api_key}",
                                   "Content-Type": "application/json"},
                          method="POST")
    ctx = ssl.create_default_context()
    try:
        with request.urlopen(req, timeout=120, context=ctx) as resp:
            data = json.loads(resp.read().decode("utf-8"))
        return {"result": data.get("choices", [{}])[0].get("message", {}).get("content", ""),
                "usage": data.get("usage")}
    except error.HTTPError as e:
        return {"error": f"HTTP {e.code}", "detail": e.read().decode("utf-8", errors="ignore")[:300]}
    except error.URLError as e:
        return {"error": f"网络错误: {e.reason}"}


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def build_parser():
    p = argparse.ArgumentParser(description="AI 打假侦探：数字内容人机验真")
    sub = p.add_subparsers(dest="command", required=True)

    for cmd in ("image", "video", "text", "auto"):
        sp = sub.add_parser(cmd, help=f"{cmd} 检测")
        sp.add_argument("input", help="图片/视频/文本的路径或 URL")
        if cmd in ("image", "auto"):
            sp.add_argument("--face", action="store_true", help="追加人脸防护盾专项检测")
        if cmd in ("image", "text", "auto"):
            sp.add_argument("--vita", action="store_true", help="追加 VITA 多模态交叉验证")

    sp = sub.add_parser("check", help="检查配置就绪状态")
    return p


def cmd_check():
    """检查所需环境变量配置状态，输出就绪报告。"""
    rows = []
    required = {
        "TENCENTCLOUD_SECRET_ID": "通用凭证",
        "TENCENTCLOUD_SECRET_KEY": "通用凭证",
        "TENCENTCLOUD_AIGC_RECOG_IMAGE_BIZ_TYPE": "图片 AI 识别审核策略号",
        "TENCENTCLOUD_AIGC_RECOG_VIDEO_BIZ_TYPE": "视频 AI 识别审核策略号",
        "TENCENTCLOUD_AIGC_RECOG_TEXT_BIZ_TYPE": "文本 AI 识别审核策略号",
    }
    optional = {
        "TENCENTCLOUD_VITA_API_KEY": "VITA 交叉验证（可选）",
        "TENCENTCLOUD_TOKEN": "临时密钥 STS Token（可选）",
    }
    for k, desc in list(required.items()) + list(optional.items()):
        v = os.getenv(k, "").strip()
        rows.append({"var": k, "desc": desc,
                     "status": "已配置" if v else ("可选" if k in optional else "缺失")})
    ready = all(os.getenv(k, "").strip() for k in required)
    warnings = []
    sid = os.getenv("TENCENTCLOUD_SECRET_ID", "").strip()
    skey = os.getenv("TENCENTCLOUD_SECRET_KEY", "").strip()
    if sid and not sid.startswith("AKID"):
        warnings.append("SecretId 应以 AKID 开头，当前不匹配")
    if skey and len(skey) != 32:
        warnings.append(f"SecretKey 长度为 {len(skey)}，腾讯云通常为 32 位，可能复制有误")
    print(json.dumps({
        "ready": ready,
        "vars": rows,
        "key_warnings": warnings,
        "console": {
            "api_key": "https://console.cloud.tencent.com/cam/capi",
            "biz_type": "https://console.cloud.tencent.com/cms/clouds/manage",
        },
    }, ensure_ascii=False, indent=2))

    # 真实鉴权校验：用最小图片调用一次真实 API，验证密钥是否真正有效
    print("=== 真实鉴权校验（调用 ims 最小图片验证密钥有效性） ===", flush=True)
    auth = tc_api.verify_credentials()
    print(json.dumps(auth, ensure_ascii=False, indent=2))


def main():
    args = build_parser().parse_args()
    cmd = args.command

    if cmd == "check":
        cmd_check()
        return

    value = args.input
    use_face = getattr(args, "face", False)
    use_vita = getattr(args, "vita", False)

    if cmd == "auto":
        cmd = guess_modality(value)
        if cmd == "unknown":
            print(json.dumps({"error": "无法自动识别模态，请显式指定 image/video/text"},
                             ensure_ascii=False, indent=2))
            sys.exit(1)

    if cmd == "image":
        res = detect_image(value, use_face=use_face, use_vita=use_vita)
    elif cmd == "video":
        res = detect_video(value, use_face=use_face)
    elif cmd == "text":
        res = detect_text(value, use_vita=use_vita)
    else:
        res = {"error": "UNKNOWN_COMMAND"}

    print(json.dumps(res, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
