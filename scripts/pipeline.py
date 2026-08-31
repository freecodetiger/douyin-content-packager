#!/usr/bin/env python3
"""Deterministic gatekeeper for douyin-content-packager."""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import struct
import subprocess
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path


SKILL_ID = "douyin-content-packager"
STATE_VERSION = 2
TRANSCRIPT_EXTENSIONS = {".srt", ".vtt", ".ass", ".ssa", ".lrc", ".txt", ".md", ".json"}
IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".webp", ".heic", ".heif", ".avif"}
RATIOS = ("3:4", "16:9")
PLATFORMS = ("youtube", "bilibili", "xiaohongshu", "douyin", "weixin")


class PipelineError(Exception):
    def __init__(self, message: str, gate: str = "pipeline") -> None:
        super().__init__(message)
        self.gate = gate


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


def emit(payload: dict, exit_code: int = 0) -> None:
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    raise SystemExit(exit_code)


def default_state_dir() -> Path:
    codex_root = Path(os.environ.get("CODEX_HOME", Path.home() / ".codex"))
    return codex_root / "state" / SKILL_ID


def resolve_file(value: str | None) -> Path | None:
    if not value:
        return None
    return Path(value).expanduser().resolve()


def read_text(path: Path) -> str:
    data = path.read_bytes()
    for encoding in ("utf-8-sig", "utf-16", "gb18030"):
        try:
            return data.decode(encoding)
        except UnicodeDecodeError:
            continue
    raise PipelineError(f"字幕文件无法按 UTF-8、UTF-16 或 GB18030 解码：{path}", "G1")


def strings_in_json(value: object) -> list[str]:
    if isinstance(value, str):
        return [value]
    if isinstance(value, list):
        result: list[str] = []
        for item in value:
            result.extend(strings_in_json(item))
        return result
    if isinstance(value, dict):
        preferred = ("text", "content", "caption", "subtitle", "transcript", "sentence", "word")
        result = []
        for key in preferred:
            if key in value:
                result.extend(strings_in_json(value[key]))
        if result:
            return result
        for item in value.values():
            result.extend(strings_in_json(item))
        return result
    return []


def extract_transcript(path: Path) -> str:
    raw = read_text(path)
    suffix = path.suffix.lower()
    if suffix == ".json":
        try:
            raw = "\n".join(strings_in_json(json.loads(raw)))
        except json.JSONDecodeError as exc:
            raise PipelineError(f"字幕 JSON 无效：{exc}", "G1") from exc
    elif suffix in {".ass", ".ssa"}:
        raw = "\n".join(line.split(",", 9)[-1] for line in raw.splitlines() if line.startswith("Dialogue:"))

    raw = re.sub(r"\{[^}]*\}", " ", raw)
    raw = re.sub(r"<[^>]+>", " ", raw)
    raw = re.sub(r"\d{1,2}:\d{2}(?::\d{2})?[,.]\d+\s*--?>\s*\d{1,2}:\d{2}(?::\d{2})?[,.]\d+", " ", raw)
    raw = re.sub(r"^\s*\d+\s*$", " ", raw, flags=re.MULTILINE)
    raw = re.sub(r"\[\d{1,2}:\d{2}(?:[.:]\d+)?\]", " ", raw)
    return re.sub(r"\s+", " ", raw).strip()


def validate_transcript(path: Path | None) -> dict:
    if path is None:
        raise PipelineError("缺少字幕/文字稿文件路径", "G0")
    if not path.is_file():
        raise PipelineError(f"字幕/文字稿文件不存在：{path}", "G0")
    if path.suffix.lower() not in TRANSCRIPT_EXTENSIONS:
        allowed = ", ".join(sorted(TRANSCRIPT_EXTENSIONS))
        raise PipelineError(f"不支持的字幕格式 {path.suffix or '(无扩展名)'}；支持：{allowed}", "G1")
    transcript = extract_transcript(path)
    content_chars = len(re.sub(r"\s+", "", transcript))
    if content_chars < 40:
        raise PipelineError(f"字幕有效文本过短（{content_chars} 字符），无法可靠包装", "G1")
    return {"path": str(path), "format": path.suffix.lower(), "content_chars": content_chars}


def png_size(path: Path) -> tuple[int, int] | None:
    with path.open("rb") as handle:
        header = handle.read(24)
    if header[:8] == b"\x89PNG\r\n\x1a\n" and len(header) >= 24:
        return struct.unpack(">II", header[16:24])
    return None


def jpeg_size(path: Path) -> tuple[int, int] | None:
    with path.open("rb") as handle:
        if handle.read(2) != b"\xff\xd8":
            return None
        while True:
            marker_start = handle.read(1)
            if not marker_start:
                return None
            if marker_start != b"\xff":
                continue
            marker = handle.read(1)
            while marker == b"\xff":
                marker = handle.read(1)
            if marker in {bytes([value]) for value in range(0xC0, 0xC4)} | {bytes([value]) for value in range(0xC5, 0xC8)} | {bytes([value]) for value in range(0xC9, 0xCC)} | {bytes([value]) for value in range(0xCD, 0xD0)}:
                handle.read(3)
                height, width = struct.unpack(">HH", handle.read(4))
                return width, height
            length_bytes = handle.read(2)
            if len(length_bytes) != 2:
                return None
            length = struct.unpack(">H", length_bytes)[0]
            handle.seek(max(0, length - 2), 1)


def sips_size(path: Path) -> tuple[int, int] | None:
    if not shutil.which("sips"):
        return None
    result = subprocess.run(
        ["sips", "-g", "pixelWidth", "-g", "pixelHeight", str(path)],
        capture_output=True,
        text=True,
        check=False,
    )
    width = re.search(r"pixelWidth:\s*(\d+)", result.stdout)
    height = re.search(r"pixelHeight:\s*(\d+)", result.stdout)
    if result.returncode == 0 and width and height:
        return int(width.group(1)), int(height.group(1))
    return None


def image_size(path: Path) -> tuple[int, int] | None:
    if path.suffix.lower() == ".png":
        return png_size(path) or sips_size(path)
    if path.suffix.lower() in {".jpg", ".jpeg"}:
        return jpeg_size(path) or sips_size(path)
    return sips_size(path)


def validate_photos(values: list[str]) -> list[dict]:
    if not values:
        raise PipelineError("缺少主人公自拍照", "G0")
    photos = []
    errors = []
    for value in values:
        path = resolve_file(value)
        if path is None or not path.is_file():
            errors.append(f"自拍照不存在：{path or value}")
            continue
        if path.suffix.lower() not in IMAGE_EXTENSIONS:
            errors.append(f"不支持的自拍照格式：{path.suffix or '(无扩展名)'} ({path})")
            continue
        size = image_size(path)
        if not size:
            errors.append(f"无法读取自拍照尺寸，请转换为 JPG 或 PNG：{path}")
            continue
        width, height = size
        if min(width, height) < 640 or max(width, height) < 1024:
            errors.append(f"自拍照分辨率不足 {width}x{height}；短边至少 640，长边至少 1024：{path}")
            continue
        photos.append({"path": str(path), "format": path.suffix.lower(), "width": width, "height": height})
    if errors:
        raise PipelineError("；".join(errors), "G1")
    return photos


def save_state(path: Path, state: dict) -> None:
    state["updated_at"] = now()
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")
    temporary.replace(path)


def load_state(path_value: str) -> tuple[Path, dict]:
    path = Path(path_value).expanduser().resolve()
    if not path.is_file():
        raise PipelineError(f"Pipeline 状态文件不存在：{path}")
    state = json.loads(path.read_text(encoding="utf-8"))
    if state.get("skill") != SKILL_ID or state.get("version") != STATE_VERSION:
        raise PipelineError(f"不是兼容的 {SKILL_ID} 状态文件：{path}")
    return path, state


def current_stage(state: dict) -> str:
    if not state.get("front_photo"):
        return "G1_AWAITING_PHOTO_REVIEW"
    if not state.get("analysis"):
        return "G2_READY_FOR_ANALYSIS"
    if set(state.get("package", {})) != set(PLATFORMS):
        return "G3_READY_FOR_PLATFORM_PACKAGE"
    if not state.get("markdown"):
        return "G3_READY_FOR_MARKDOWN"
    if not state.get("plans"):
        return "G4_READY_FOR_PLANS"
    if not state.get("approval"):
        return "G4_AWAITING_USER_APPROVAL"
    generation = state["generation"]
    if any(generation[ratio].get("image") is None for ratio in RATIOS):
        if any(
            generation[ratio].get("attempts", 0) > 0 and not generation[ratio].get("retry_authorized")
            for ratio in RATIOS
            if generation[ratio].get("image") is None
        ):
            return "G5_GENERATION_FAILED_AWAITING_RETRY_APPROVAL"
        return "G5_READY_FOR_GENERATION"
    if any(generation[ratio].get("qa") is None for ratio in RATIOS):
        return "G6_AWAITING_QA"
    if any(generation[ratio]["qa"]["status"] == "fail" for ratio in RATIOS):
        return "G6_QA_FAILED_AWAITING_RETRY_APPROVAL"
    return "COMPLETE"


def summary(path: Path, state: dict) -> dict:
    return {
        "ok": True,
        "state": str(path),
        "run_id": state["run_id"],
        "stage": current_stage(state),
        "approved_plan": (state.get("approval") or {}).get("plan"),
        "platforms_recorded": sorted(state.get("package", {})),
        "markdown": state.get("markdown"),
        "generation": state["generation"],
    }


def require(condition: bool, message: str, gate: str = "pipeline") -> None:
    if not condition:
        raise PipelineError(message, gate)


def command_start(args: argparse.Namespace) -> None:
    transcript = validate_transcript(resolve_file(args.transcript))
    photos = validate_photos(args.photo)
    if args.website and not re.match(r"^https?://", args.website):
        raise PipelineError("个人网站链接必须以 http:// 或 https:// 开头", "G1")
    run_id = uuid.uuid4().hex[:12]
    state_dir = Path(args.state_dir).expanduser().resolve() if args.state_dir else default_state_dir()
    state_path = state_dir / f"{run_id}.json"
    state = {
        "skill": SKILL_ID,
        "version": STATE_VERSION,
        "run_id": run_id,
        "created_at": now(),
        "updated_at": now(),
        "transcript": transcript,
        "workspace": str(Path.cwd().resolve()),
        "brand": {"channel_name": (args.channel_name or "").strip(), "website": (args.website or "").strip()},
        "photos": photos,
        "front_photo": None,
        "analysis": None,
        "package": {},
        "markdown": None,
        "plans": None,
        "approval": None,
        "generation": {ratio: {"attempts": 0, "image": None, "qa": None, "retry_authorized": False} for ratio in RATIOS},
    }
    save_state(state_path, state)
    emit(summary(state_path, state))


def command_approve_photo(args: argparse.Namespace) -> None:
    path, state = load_state(args.state)
    candidate = str(resolve_file(args.front_photo))
    require(candidate in {photo["path"] for photo in state["photos"]}, "正面主参考必须来自 start 已验证的自拍照", "G1")
    state["front_photo"] = candidate
    save_state(path, state)
    emit(summary(path, state))


def command_record_analysis(args: argparse.Namespace) -> None:
    path, state = load_state(args.state)
    require(current_stage(state) == "G2_READY_FOR_ANALYSIS", "当前阶段不允许登记内容分析", "G2")
    require(all(len(value.strip()) >= 4 for value in (args.core_thesis, args.hook, args.evidence)), "核心、钩子和证据都不能为空", "G2")
    state["analysis"] = {"core_thesis": args.core_thesis.strip(), "hook": args.hook.strip(), "evidence": args.evidence.strip()}
    save_state(path, state)
    emit(summary(path, state))


def text_chars(value: str) -> int:
    return len(re.sub(r"\s+", "", value))


def validate_no_placeholders(values: list[str]) -> None:
    for value in values:
        require(not re.search(r"\{[^{}]+\}", value), f"文案不得保留占位符：{value}", "G3")


def validate_brand(state: dict, body: str, tags: list[str]) -> None:
    channel = state["brand"]["channel_name"]
    website = state["brand"]["website"]
    if channel:
        require(any(channel.lower() in tag.lower() for tag in tags), f"已提供频道名，标签中必须包含：{channel}", "G3")
    if website:
        require(website in body, f"已提供个人网站，正文中必须包含：{website}", "G3")


def command_record_platform(args: argparse.Namespace) -> None:
    path, state = load_state(args.state)
    require(state.get("analysis") is not None and state.get("markdown") is None, "当前阶段不允许登记平台文案", "G3")
    platform = args.platform
    titles = [value.strip() for value in args.title]
    body = args.body.strip()
    tags = [value.strip() for value in args.tag]
    timestamps = [value.strip() for value in args.timestamp]
    dynamic = (args.dynamic or "").strip()
    short_title = (args.short_title or "").strip()
    all_values = titles + [body, args.reason or "", dynamic, short_title] + tags + timestamps
    validate_no_placeholders(all_values)
    require(body and all(tags), "正文和标签不能为空", "G3")
    require(len({tag.lstrip("#").lower() for tag in tags}) == len(tags), "标签不能重复", "G3")
    validate_brand(state, body, tags)

    limits = {"youtube": 100, "bilibili": 25, "xiaohongshu": 20, "douyin": 30}
    if platform in limits:
        require(len(titles) == 3, f"{platform} 必须提供 3 个标题", "G3")
        require(len({re.sub(r"\s+", "", title).lower() for title in titles}) == 3, f"{platform} 标题不能重复", "G3")
        require(all(0 < text_chars(title) <= limits[platform] for title in titles), f"{platform} 标题超过长度限制", "G3")
        require(args.preferred in (1, 2, 3), f"{platform} 必须指定 1–3 的首选标题", "G3")
        require(text_chars(args.reason or "") >= 8, f"{platform} 必须提供具体首选理由", "G3")
    else:
        require(platform == "weixin" and 0 < text_chars(short_title) <= 16, "视频号短标题必须为 1–16 字符", "G3")

    if platform == "youtube":
        require(not dynamic and not short_title, "YouTube 不接受粉丝动态或视频号短标题字段", "G3")
        require(120 <= text_chars(body) <= 5000, "YouTube 描述必须为 120–5000 字符", "G3")
        require(timestamps and all(re.match(r"^\d{1,2}:\d{2}(?::\d{2})?\s+\S+", item) for item in timestamps), "YouTube 必须提供合法时间戳", "G3")
        require(5 <= len(tags) <= 30 and len(", ".join(tags)) <= 500, "YouTube 标签必须为 5–30 个且总长度不超过 500", "G3")
    elif platform == "bilibili":
        require(not timestamps and not short_title, "B站不接受 YouTube 时间戳或视频号短标题字段", "G3")
        require(80 <= text_chars(body) <= 1000, "B站简介必须为 80–1000 字符", "G3")
        require(len(tags) == 9 and all(not tag.startswith("#") for tag in tags), "B站必须提供 9 个不带 # 的标签", "G3")
        require(20 <= text_chars(dynamic) <= 233, "B站粉丝动态必须为 20–233 字符", "G3")
    elif platform == "xiaohongshu":
        require(not timestamps and not dynamic and not short_title, "小红书只接受标题、正文和标签字段", "G3")
        require(300 <= text_chars(body) <= 500, "小红书正文必须为 300–500 字符", "G3")
        require(5 <= len(tags) <= 10 and all(tag.startswith("#") for tag in tags), "小红书必须提供 5–10 个 #标签", "G3")
        require(all("!" not in title and "！" not in title for title in titles), "小红书标题不使用感叹号", "G3")
    elif platform == "douyin":
        require(not timestamps and not dynamic and not short_title, "抖音只接受标题、简介和标签字段", "G3")
        require(20 <= text_chars(body) <= 250, "抖音简介必须为 20–250 字符", "G3")
        require(3 <= len(tags) <= 5 and all(tag.startswith("#") for tag in tags), "抖音必须提供 3–5 个 #标签", "G3")
    elif platform == "weixin":
        require(not titles and args.preferred is None and not (args.reason or "").strip(), "视频号使用短标题，不接受三选一标题或首选理由", "G3")
        require(not timestamps and not dynamic, "视频号不接受 YouTube 时间戳或B站粉丝动态字段", "G3")
        require(60 <= text_chars(body) <= 800, "视频号标题描述必须为 60–800 字符", "G3")
        require(3 <= len(tags) <= 10 and all(tag.startswith("#") for tag in tags), "视频号必须提供 3–10 个 #标签", "G3")

    state["package"][platform] = {
        "titles": titles,
        "preferred": args.preferred,
        "reason": (args.reason or "").strip(),
        "body": body,
        "tags": tags,
        "timestamps": timestamps,
        "dynamic": dynamic,
        "short_title": short_title,
    }
    save_state(path, state)
    emit(summary(path, state))


def versioned_output(path: Path) -> Path:
    if not path.exists():
        return path
    version = 2
    while True:
        candidate = path.with_name(f"{path.stem}-v{version}{path.suffix}")
        if not candidate.exists():
            return candidate
        version += 1


def render_markdown(state: dict) -> str:
    source = Path(state["transcript"]["path"])
    analysis = state["analysis"]
    package = state["package"]
    brand = state["brand"]
    lines = [
        f"# {source.stem} — 全平台发布方案",
        "",
        f"**素材：** `{source.name}`  ",
        f"**生成日期：** {datetime.now().date().isoformat()}  ",
    ]
    if brand["channel_name"]:
        lines.append(f"**频道/品牌：** {brand['channel_name']}  ")
    if brand["website"]:
        lines.append(f"**个人网站：** {brand['website']}  ")
    lines += [
        "",
        "## 视频内容定位",
        "",
        f"**一句话核心：** {analysis['core_thesis']}",
        f"**传播钩子：** {analysis['hook']}",
        f"**正文依据：** {analysis['evidence']}",
        "",
        "---",
        "",
    ]

    for platform, heading in (("youtube", "YouTube"), ("bilibili", "B站"), ("xiaohongshu", "小红书"), ("douyin", "抖音")):
        item = package[platform]
        lines += [f"## {heading}", "", "### 标题（三选一）", ""]
        for index, title in enumerate(item["titles"]):
            lines.append(f"{chr(65 + index)}. {title}")
        lines += ["", f"**首选建议：{chr(64 + item['preferred'])}。** {item['reason']}", ""]
        body_heading = {"youtube": "描述", "bilibili": "简介", "xiaohongshu": "正文", "douyin": "简介"}[platform]
        lines += [f"### {body_heading}", "", item["body"], ""]
        if platform == "youtube":
            lines += ["### 时间戳", ""] + [f"- {stamp}" for stamp in item["timestamps"]] + [""]
            lines += ["### 标签", "", ", ".join(item["tags"]), ""]
        elif platform == "bilibili":
            lines += ["### 标签（9个）", "", "、".join(item["tags"]), "", "### 粉丝动态", "", item["dynamic"], ""]
        else:
            lines += ["### 标签", "", " ".join(item["tags"]), ""]
        lines += ["---", ""]

    weixin = package["weixin"]
    lines += [
        "## 视频号",
        "",
        "### 短标题",
        "",
        weixin["short_title"],
        "",
        "### 标题＋描述",
        "",
        weixin["body"],
        "",
        "### 标签",
        "",
        " ".join(weixin["tags"]),
        "",
    ]
    return "\n".join(lines).rstrip() + "\n"


def command_write_markdown(args: argparse.Namespace) -> None:
    path, state = load_state(args.state)
    require(current_stage(state) == "G3_READY_FOR_MARKDOWN", "五个平台文案全部通过后才能写 Markdown", "G3")
    if args.output:
        output = Path(args.output).expanduser()
        if not output.is_absolute():
            output = Path(state["workspace"]) / output
    else:
        source = Path(state["transcript"]["path"])
        output = Path(state["workspace"]) / "outputs" / f"{source.stem}-全平台发布方案.md"
    output = versioned_output(output.resolve())
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(render_markdown(state), encoding="utf-8")
    state["markdown"] = str(output)
    save_state(path, state)
    emit(summary(path, state))


def command_record_plans(args: argparse.Namespace) -> None:
    path, state = load_state(args.state)
    require(current_stage(state) == "G4_READY_FOR_PLANS", "必须先通过内容包装阶段", "G4")
    plans = [plan.upper() for plan in args.plan]
    require(len(plans) == 3 and set(plans) == {"A", "B", "C"}, "必须登记且只登记 A、B、C 三套方案", "G4")
    state["plans"] = {"ids": plans, "ratios": list(RATIOS)}
    save_state(path, state)
    emit(summary(path, state))


def command_approve_plan(args: argparse.Namespace) -> None:
    path, state = load_state(args.state)
    require(current_stage(state) == "G4_AWAITING_USER_APPROVAL", "当前不在等待方案批准阶段", "G5")
    require(args.confirm, "方案批准必须带 --confirm", "G5")
    plan = args.plan.upper()
    require(plan in state["plans"]["ids"], f"未知方案：{plan}", "G5")
    state["approval"] = {"plan": plan, "confirmed_at": now()}
    save_state(path, state)
    emit(summary(path, state))


def may_generate(state: dict, ratio: str) -> tuple[bool, str]:
    if not state.get("approval"):
        return False, "用户尚未批准封面方案"
    entry = state["generation"][ratio]
    if entry.get("image") is None:
        if entry.get("attempts", 0) == 0 or entry.get("retry_authorized"):
            return True, "allowed"
        return False, "失败重试尚未获得用户授权"
    return False, "该比例已有待 QA 或已验收图片"


def command_can_generate(args: argparse.Namespace) -> None:
    path, state = load_state(args.state)
    allowed, reason = may_generate(state, args.ratio)
    emit({**summary(path, state), "ratio": args.ratio, "allowed": allowed, "reason": reason}, 0 if allowed else 3)


def command_can_generate_pair(args: argparse.Namespace) -> None:
    path, state = load_state(args.state)
    results = {ratio: may_generate(state, ratio) for ratio in RATIOS}
    allowed = all(result[0] for result in results.values())
    reasons = {ratio: result[1] for ratio, result in results.items()}
    emit(
        {
            **summary(path, state),
            "ratios": list(RATIOS),
            "allowed": allowed,
            "reasons": reasons,
            "dispatch": "concurrent-independent-calls" if allowed else None,
        },
        0 if allowed else 3,
    )


def command_record_generation(args: argparse.Namespace) -> None:
    path, state = load_state(args.state)
    allowed, reason = may_generate(state, args.ratio)
    require(allowed, reason, "G5")
    image = resolve_file(args.image)
    require(image is not None and image.is_file(), f"生成图片不存在：{image}", "G5")
    size = image_size(image)
    require(size is not None, f"无法读取生成图片尺寸：{image}", "G5")
    width, height = size
    actual = width / height
    expected = 3 / 4 if args.ratio == "3:4" else 16 / 9
    tolerance = 0.06 if args.ratio == "3:4" else 0.10
    require(abs(actual - expected) <= tolerance, f"{args.ratio} 图片比例不合格：{width}x{height}", "G5")
    entry = state["generation"][args.ratio]
    entry.update({"attempts": entry.get("attempts", 0) + 1, "image": str(image), "width": width, "height": height, "qa": None, "retry_authorized": False})
    save_state(path, state)
    emit(summary(path, state))


def command_record_generation_failure(args: argparse.Namespace) -> None:
    path, state = load_state(args.state)
    allowed, reason = may_generate(state, args.ratio)
    require(allowed, reason, "G5")
    issue = args.issue.strip()
    require(issue, "生成失败必须提供具体原因", "G5")
    entry = state["generation"][args.ratio]
    entry.update(
        {
            "attempts": entry.get("attempts", 0) + 1,
            "image": None,
            "width": None,
            "height": None,
            "qa": {"status": "fail", "issues": [issue], "checked_at": now(), "kind": "generation"},
            "retry_authorized": False,
        }
    )
    save_state(path, state)
    emit(summary(path, state))


def command_record_qa(args: argparse.Namespace) -> None:
    path, state = load_state(args.state)
    entry = state["generation"][args.ratio]
    require(entry.get("image") is not None, "必须先登记该比例的生成图片", "G6")
    issues = args.issue or []
    require(args.status == "pass" or issues, "QA 失败时必须至少提供一个 --issue", "G6")
    entry["qa"] = {"status": args.status, "issues": issues, "checked_at": now()}
    save_state(path, state)
    emit(summary(path, state))


def command_authorize_retry(args: argparse.Namespace) -> None:
    path, state = load_state(args.state)
    require(args.confirm, "重试授权必须带 --confirm", "G6")
    entry = state["generation"][args.ratio]
    require((entry.get("qa") or {}).get("status") == "fail", "只有生成失败或 QA 失败的图片可以申请重试", "G6")
    entry.update({"image": None, "width": None, "height": None, "qa": None, "retry_authorized": True})
    save_state(path, state)
    emit(summary(path, state))


def command_status(args: argparse.Namespace) -> None:
    path, state = load_state(args.state)
    emit(summary(path, state))


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Strict state machine for douyin-content-packager")
    sub = parser.add_subparsers(dest="command", required=True)

    start = sub.add_parser("start")
    start.add_argument("--transcript")
    start.add_argument("--photo", action="append", default=[])
    start.add_argument("--channel-name")
    start.add_argument("--website")
    start.add_argument("--state-dir", help=argparse.SUPPRESS)
    start.set_defaults(func=command_start)

    photo = sub.add_parser("approve-photo")
    photo.add_argument("--state", required=True)
    photo.add_argument("--front-photo", required=True)
    photo.set_defaults(func=command_approve_photo)

    analysis = sub.add_parser("record-analysis")
    analysis.add_argument("--state", required=True)
    analysis.add_argument("--core-thesis", required=True)
    analysis.add_argument("--hook", required=True)
    analysis.add_argument("--evidence", required=True)
    analysis.set_defaults(func=command_record_analysis)

    package = sub.add_parser("record-platform")
    package.add_argument("--state", required=True)
    package.add_argument("--platform", choices=PLATFORMS, required=True)
    package.add_argument("--title", action="append", default=[])
    package.add_argument("--preferred", type=int)
    package.add_argument("--reason")
    package.add_argument("--body", required=True)
    package.add_argument("--tag", action="append", required=True)
    package.add_argument("--timestamp", action="append", default=[])
    package.add_argument("--dynamic")
    package.add_argument("--short-title")
    package.set_defaults(func=command_record_platform)

    markdown = sub.add_parser("write-markdown")
    markdown.add_argument("--state", required=True)
    markdown.add_argument("--output")
    markdown.set_defaults(func=command_write_markdown)

    plans = sub.add_parser("record-plans")
    plans.add_argument("--state", required=True)
    plans.add_argument("--plan", action="append", required=True)
    plans.set_defaults(func=command_record_plans)

    approve = sub.add_parser("approve-plan")
    approve.add_argument("--state", required=True)
    approve.add_argument("--plan", required=True)
    approve.add_argument("--confirm", action="store_true")
    approve.set_defaults(func=command_approve_plan)

    can_generate = sub.add_parser("can-generate")
    can_generate.add_argument("--state", required=True)
    can_generate.add_argument("--ratio", choices=RATIOS, required=True)
    can_generate.set_defaults(func=command_can_generate)

    can_generate_pair = sub.add_parser("can-generate-pair")
    can_generate_pair.add_argument("--state", required=True)
    can_generate_pair.set_defaults(func=command_can_generate_pair)

    generated = sub.add_parser("record-generation")
    generated.add_argument("--state", required=True)
    generated.add_argument("--ratio", choices=RATIOS, required=True)
    generated.add_argument("--image", required=True)
    generated.set_defaults(func=command_record_generation)

    generation_failure = sub.add_parser("record-generation-failure")
    generation_failure.add_argument("--state", required=True)
    generation_failure.add_argument("--ratio", choices=RATIOS, required=True)
    generation_failure.add_argument("--issue", required=True)
    generation_failure.set_defaults(func=command_record_generation_failure)

    qa = sub.add_parser("record-qa")
    qa.add_argument("--state", required=True)
    qa.add_argument("--ratio", choices=RATIOS, required=True)
    qa.add_argument("--status", choices=("pass", "fail"), required=True)
    qa.add_argument("--issue", action="append")
    qa.set_defaults(func=command_record_qa)

    retry = sub.add_parser("authorize-retry")
    retry.add_argument("--state", required=True)
    retry.add_argument("--ratio", choices=RATIOS, required=True)
    retry.add_argument("--confirm", action="store_true")
    retry.set_defaults(func=command_authorize_retry)

    status = sub.add_parser("status")
    status.add_argument("--state", required=True)
    status.set_defaults(func=command_status)
    return parser


def main() -> None:
    try:
        args = build_parser().parse_args()
        args.func(args)
    except PipelineError as exc:
        emit({"ok": False, "gate": exc.gate, "error": str(exc)}, 2)
    except (OSError, json.JSONDecodeError) as exc:
        emit({"ok": False, "gate": "pipeline", "error": str(exc)}, 2)


if __name__ == "__main__":
    main()
