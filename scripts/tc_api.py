#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
tc_api.py — 腾讯云 TC3-HMAC-SHA256 纯标准库客户端（零依赖）

目标：不依赖 tencentcloud-sdk-python，仅用 Python 标准库（hashlib/hmac/json/urllib）
即可调用腾讯云「AI 生成内容识别」系列接口，把「资源依赖」降到最低。

覆盖服务：
  - ims.tencentcloudapi.com    图片 AI 生成识别  ImageModeration (IMAGE_AIGC)
  - tms.tencentcloudapi.com    文本 AI 生成识别  TextModeration  (TEXT_AIGC)
  - vm.tencentcloudapi.com     视频 AI 生成识别  CreateVideoModerationTask / DescribeTaskDetail (VIDEO_AIGC)
  - faceid.tencentcloudapi.com AI 人脸防护盾     DetectAIFakeFaces

凭证：从环境变量读取 TENCENTCLOUD_SECRET_ID / TENCENTCLOUD_SECRET_KEY（可选 TENCENTCLOUD_TOKEN）
"""

import base64
import hashlib
import hmac
import json
import os
import ssl
import sys
from datetime import datetime
from urllib import request, error


# ---------------------------------------------------------------------------
# .env 加载（零依赖）：启动时读取 skill 根目录 / 当前目录的 .env 到环境变量
# ---------------------------------------------------------------------------

def _load_dotenv():
    """读取 .env 文件（KEY=VALUE 每行），不回显敏感值。返回加载的键名列表。"""
    candidates = [
        os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), ".env"),
        os.path.join(os.getcwd(), ".env"),
    ]
    loaded = []
    for path in candidates:
        if not os.path.isfile(path):
            continue
        try:
            with open(path, "r", encoding="utf-8-sig") as f:
                for line in f:
                    line = line.strip()
                    if not line or line.startswith("#") or "=" not in line:
                        continue
                    k, _, v = line.partition("=")
                    k = k.strip()
                    v = v.strip().strip('"').strip("'")
                    # .env 优先：覆盖可能已存在的（可能无效的）系统环境变量。
                    # 这是 skill 的显式配置，用户写了 .env 就应该用 .env 的值。
                    if k and v:
                        os.environ[k] = v
                        loaded.append(k)
        except OSError:
            pass
    return loaded


_load_dotenv()


# ---------------------------------------------------------------------------
# 签名核心（腾讯云 API 3.0 签名 v3）
# ---------------------------------------------------------------------------

def _hmac(key: bytes, msg: str) -> bytes:
    return hmac.new(key, msg.encode("utf-8"), hashlib.sha256).digest()


def _sha256_hex(s: str) -> str:
    return hashlib.sha256(s.encode("utf-8")).hexdigest()


def tc3_sign(secret_id, secret_key, host, service, action, version, payload,
             region="", token=None, timestamp=None):
    """生成 TC3-HMAC-SHA256 签名与完整请求头，返回 (headers, )"""
    if timestamp is None:
        timestamp = int(datetime.now().timestamp())
    date = datetime.utcfromtimestamp(timestamp).strftime("%Y-%m-%d")

    # 1. 规范请求串（与官方 SDK 完全一致：仅签 content-type 与 host 两个头）
    http_method = "POST"
    canonical_uri = "/"
    canonical_querystring = ""
    ct = "application/json; charset=utf-8"
    canonical_headers = f"content-type:{ct}\nhost:{host}\n"
    signed_headers = "content-type;host"
    hashed_payload = _sha256_hex(payload)
    canonical_request = "\n".join([
        http_method, canonical_uri, canonical_querystring,
        canonical_headers, signed_headers, hashed_payload,
    ])

    # 2. 待签字符串
    credential_scope = f"{date}/{service}/tc3_request"
    string_to_sign = "\n".join([
        "TC3-HMAC-SHA256",
        str(timestamp),
        credential_scope,
        _sha256_hex(canonical_request),
    ])

    # 3. 计算签名
    secret_date = _hmac(("TC3" + secret_key).encode("utf-8"), date)
    secret_service = _hmac(secret_date, service)
    secret_signing = _hmac(secret_service, "tc3_request")
    signature = hmac.new(secret_signing, string_to_sign.encode("utf-8"),
                         hashlib.sha256).hexdigest()

    # 4. Authorization
    authorization = (
        f"TC3-HMAC-SHA256 Credential={secret_id}/{credential_scope}, "
        f"SignedHeaders={signed_headers}, Signature={signature}"
    )

    headers = {
        "Authorization": authorization,
        "Content-Type": ct,
        "Host": host,
        "X-TC-Action": action,
        "X-TC-Timestamp": str(timestamp),
        "X-TC-Version": version,
    }
    if region:
        headers["X-TC-Region"] = region
    if token:
        headers["X-TC-Token"] = token

    return headers


def _post(host, headers, payload, timeout=60):
    """发送 HTTPS POST 请求，返回解析后的 Response 字典。"""
    url = "https://" + host + "/"
    body = payload.encode("utf-8")
    req = request.Request(url, data=body, headers=headers, method="POST")
    ctx = ssl.create_default_context()
    try:
        with request.urlopen(req, timeout=timeout, context=ctx) as resp:
            data = resp.read().decode("utf-8")
    except error.HTTPError as e:
        data = e.read().decode("utf-8", errors="ignore")
    except error.URLError as e:
        return {"__error__": f"网络错误: {e.reason}"}

    try:
        obj = json.loads(data)
    except json.JSONDecodeError:
        return {"__error__": f"响应非 JSON: {data[:200]}"}
    return obj


# ---------------------------------------------------------------------------
# 凭证
# ---------------------------------------------------------------------------

def get_credentials():
    """读取腾讯云凭证。返回 (secret_id, secret_key, token) 或 None（未配置）。"""
    sid = os.getenv("TENCENTCLOUD_SECRET_ID", "").strip()
    skey = os.getenv("TENCENTCLOUD_SECRET_KEY", "").strip()
    token = os.getenv("TENCENTCLOUD_TOKEN", "").strip()
    if not sid or not skey:
        return None
    return sid, skey, (token or None)


_HINTS = {
    "AuthFailure.SignatureFailure": "签名验证失败：通常是 SecretId/SecretKey 不匹配或复制有误（注意 0/O、1/l/I 混淆）。请到控制台重新复制密钥。",
    "AuthFailure.SecretIdNotFound": "SecretId 不存在：请核对 SecretId 是否正确。",
    "AuthFailure.InvalidSecretId": "SecretId 格式错误：应以 AKID 开头。",
    "InvalidParameter": "参数错误：请检查 BizType 是否已在内容安全控制台配置。",
    "UnauthorizedOperation": "无权限：该密钥未开通对应服务，请先在控制台开通内容安全/AI 识别服务。",
}


def _api_error(r):
    """统一格式化 API 错误，附带常见错误的排查提示。"""
    code = r["Error"].get("Code", "")
    err = {
        "error": "API_ERROR",
        "code": code,
        "message": r["Error"].get("Message", ""),
        "request_id": r.get("RequestId", ""),
    }
    if code in _HINTS:
        err["hint"] = _HINTS[code]
    return err


# 1x1 透明 PNG（用于真实鉴权校验，最小请求）
_MINI_PNG_B64 = ("iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJ"
                 "AAAADUlEQVR42mNk+M9QDwADhgGAWjR9awAAAABJRU5ErkJggg==")


def verify_credentials():
    """真实鉴权校验：用 1x1 最小图片调用 ims，判断密钥是否真正有效。

    返回 dict：
      - {"ok": True, ...}：鉴权通过（密钥有效，签名正确）
      - {"ok": False, "code": ..., "reason": ...}：鉴权失败
    """
    cred = get_credentials()
    if not cred:
        return {"ok": False, "code": "CREDENTIALS_NOT_CONFIGURED",
                "reason": "未配置 TENCENTCLOUD_SECRET_ID/KEY"}
    sid, skey, token = cred
    host = "ims.tencentcloudapi.com"
    service = "ims"
    action = "ImageModeration"
    version = "2020-12-29"
    payload = json.dumps({"FileContent": _MINI_PNG_B64, "Type": "IMAGE_AIGC"},
                         ensure_ascii=False)
    headers = tc3_sign(sid, skey, host, service, action, version, payload,
                       region="ap-guangzhou", token=token)
    resp = _post(host, headers, payload)
    if "__error__" in resp:
        return {"ok": False, "code": "NETWORK_ERROR", "reason": resp["__error__"]}
    if "Response" not in resp:
        return {"ok": False, "code": "UNEXPECTED_RESPONSE", "reason": str(resp)[:200]}
    r = resp["Response"]
    if "Error" in r:
        code = r["Error"].get("Code", "")
        # AuthFailure* 表示密钥/签名问题；其它错误（如 UnauthorizedOperation、
        # InvalidParameter）说明鉴权本身通过了，只是服务/参数另有问题。
        if code.startswith("AuthFailure"):
            return {"ok": False, "code": code,
                    "reason": r["Error"].get("Message", "")}
        return {"ok": True, "code": code,
                "note": "鉴权通过（" + code + "：" + r["Error"].get("Message", "")[:60] + "）"}
    return {"ok": True, "code": "OK", "request_id": r.get("RequestId", "")}


# ---------------------------------------------------------------------------
# 各服务调用封装
# ---------------------------------------------------------------------------

def detect_image_aigc(image_url=None, image_base64=None, biz_type=None, data_id=None):
    """图片 AI 生成识别（ims ImageModeration, Type=IMAGE_AIGC）。"""
    cred = get_credentials()
    if not cred:
        return {"error": "CREDENTIALS_NOT_CONFIGURED"}
    sid, skey, token = cred
    host = "ims.tencentcloudapi.com"
    service = "ims"
    action = "ImageModeration"
    version = "2020-12-29"

    payload_dict = {"Type": "IMAGE_AIGC"}
    if image_url:
        payload_dict["FileUrl"] = image_url
    if image_base64:
        payload_dict["FileContent"] = image_base64
    if biz_type:
        payload_dict["BizType"] = biz_type
    if data_id:
        payload_dict["DataId"] = data_id

    payload = json.dumps(payload_dict, ensure_ascii=False)
    headers = tc3_sign(sid, skey, host, service, action, version, payload,
                       region="ap-guangzhou", token=token)
    resp = _post(host, headers, payload)
    if "__error__" in resp:
        return {"error": resp["__error__"]}
    if "Response" not in resp:
        return {"error": "UNEXPECTED_RESPONSE", "raw": resp}
    r = resp["Response"]
    if "Error" in r:
        return _api_error(r)
    return {
        "suggestion": r.get("Suggestion", ""),
        "label": r.get("Label", ""),
        "score": r.get("Score", 0),
        "detail_results": r.get("LabelResults", []),
        "request_id": r.get("RequestId", ""),
    }


def detect_text_aigc(text, biz_type=None, data_id=None):
    """文本 AI 生成识别（tms TextModeration, Type=TEXT_AIGC）。"""
    cred = get_credentials()
    if not cred:
        return {"error": "CREDENTIALS_NOT_CONFIGURED"}
    sid, skey, token = cred
    host = "tms.tencentcloudapi.com"
    service = "tms"
    action = "TextModeration"
    version = "2020-12-29"

    content_b64 = base64.b64encode(text.encode("utf-8")).decode("utf-8")
    payload_dict = {"Content": content_b64, "Type": "TEXT_AIGC"}
    if biz_type:
        payload_dict["BizType"] = biz_type
    if data_id:
        payload_dict["DataId"] = data_id

    payload = json.dumps(payload_dict, ensure_ascii=False)
    headers = tc3_sign(sid, skey, host, service, action, version, payload,
                       region="ap-guangzhou", token=token)
    resp = _post(host, headers, payload)
    if "__error__" in resp:
        return {"error": resp["__error__"]}
    if "Response" not in resp:
        return {"error": "UNEXPECTED_RESPONSE", "raw": resp}
    r = resp["Response"]
    if "Error" in r:
        return _api_error(r)
    return {
        "suggestion": r.get("Suggestion", ""),
        "label": r.get("Label", ""),
        "score": r.get("Score", 0),
        "keywords": r.get("Keywords", []),
        "detail_results": r.get("DetailResults", []),
        "request_id": r.get("RequestId", ""),
    }


def create_video_aigc_task(video_url, biz_type=None, data_id=None):
    """视频 AI 生成识别第一步：创建异步任务（vm CreateVideoModerationTask）。"""
    cred = get_credentials()
    if not cred:
        return {"error": "CREDENTIALS_NOT_CONFIGURED"}
    sid, skey, token = cred
    host = "vm.tencentcloudapi.com"
    service = "vm"
    action = "CreateVideoModerationTask"
    version = "2021-09-22"

    payload_dict = {
        "Type": "VIDEO_AIGC",
        "Tasks": [{
            "Input": {"Url": video_url, "Type": "URL"},
        }],
    }
    if biz_type:
        payload_dict["BizType"] = biz_type
    if data_id:
        payload_dict["Tasks"][0]["DataId"] = data_id

    payload = json.dumps(payload_dict, ensure_ascii=False)
    headers = tc3_sign(sid, skey, host, service, action, version, payload,
                       region="ap-guangzhou", token=token)
    resp = _post(host, headers, payload)
    if "__error__" in resp:
        return {"error": resp["__error__"]}
    if "Response" not in resp:
        return {"error": "UNEXPECTED_RESPONSE", "raw": resp}
    r = resp["Response"]
    if "Error" in r:
        return _api_error(r)
    results = r.get("Results", [])
    if not results:
        return {"error": "NO_RESULTS", "request_id": r.get("RequestId")}
    first = results[0]
    return {
        "task_id": first.get("TaskId", ""),
        "data_id": first.get("DataId", ""),
        "status": "CREATED",
        "request_id": r.get("RequestId", ""),
    }


def query_video_aigc_task(task_id, show_all=False):
    """视频 AI 生成识别第二步：查询任务结果（vm DescribeTaskDetail）。"""
    cred = get_credentials()
    if not cred:
        return {"error": "CREDENTIALS_NOT_CONFIGURED"}
    sid, skey, token = cred
    host = "vm.tencentcloudapi.com"
    service = "vm"
    action = "DescribeTaskDetail"
    version = "2021-09-22"

    payload = json.dumps({"TaskId": task_id}, ensure_ascii=False)
    headers = tc3_sign(sid, skey, host, service, action, version, payload,
                       region="ap-guangzhou", token=token)
    resp = _post(host, headers, payload)
    if "__error__" in resp:
        return {"error": resp["__error__"]}
    if "Response" not in resp:
        return {"error": "UNEXPECTED_RESPONSE", "raw": resp}
    r = resp["Response"]
    if "Error" in r:
        return _api_error(r)
    result = {
        "task_id": r.get("TaskId", ""),
        "status": r.get("Status", ""),
        "suggestion": r.get("Suggestion", ""),
        "label": r.get("Label", ""),
    }
    image_segments = r.get("ImageSegments", [])
    if image_segments:
        result["total_snapshots"] = len(image_segments)
        flagged = []
        for seg in image_segments:
            sr = seg.get("Result", {})
            if show_all or sr.get("Suggestion", "Pass") != "Pass":
                flagged.append({
                    "offset_time": seg.get("OffsetTime", ""),
                    "suggestion": sr.get("Suggestion", ""),
                    "label": sr.get("Label", ""),
                    "score": sr.get("Score", 0),
                })
        result["flagged_snapshots"] = flagged
    result["request_id"] = r.get("RequestId", "")
    return result


def detect_ai_fake_faces(face_input_b64, face_input_type=1, region=""):
    """AI 人脸防护盾（faceid DetectAIFakeFaces）。face_input_type: 1=图片 2=视频。"""
    cred = get_credentials()
    if not cred:
        return {"error": "CREDENTIALS_NOT_CONFIGURED"}
    sid, skey, token = cred
    host = "faceid.tencentcloudapi.com"
    service = "faceid"
    action = "DetectAIFakeFaces"
    version = "2018-03-01"

    payload = json.dumps({
        "FaceInput": face_input_b64,
        "FaceInputType": face_input_type,
    }, ensure_ascii=False)
    headers = tc3_sign(sid, skey, host, service, action, version, payload,
                       region=region, token=token)
    resp = _post(host, headers, payload)
    if "__error__" in resp:
        return {"error": resp["__error__"]}
    if "Response" not in resp:
        return {"error": "UNEXPECTED_RESPONSE", "raw": resp}
    r = resp["Response"]
    if "Error" in r:
        return _api_error(r)
    level = r.get("AttackRiskLevel", "")
    level_desc = {"Low": "低风险-正常人脸", "Mid": "中风险-存在攻击嫌疑",
                  "High": "高风险-极可能为攻击行为"}.get(level, "未知")
    return {
        "attack_risk_level": level,
        "attack_risk_level_desc": level_desc,
        "attack_risk_details": r.get("AttackRiskDetailInfos", []),
        "face_details": r.get("FaceDetailInfos", []),
        "request_id": r.get("RequestId", ""),
    }


if __name__ == "__main__":
    # 简单自检：未配置凭证时输出提示
    cred = get_credentials()
    print(json.dumps({
        "credentials_configured": bool(cred),
        "message": ("已配置 TENCENTCLOUD_SECRET_ID/KEY" if cred
                    else "未配置凭证，将使用离线启发式降级模式"),
    }, ensure_ascii=False, indent=2))
