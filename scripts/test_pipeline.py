#!/usr/bin/env python3

import json
import struct
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


SCRIPT = Path(__file__).with_name("pipeline.py")


def fake_png(path: Path, width: int, height: int) -> None:
    path.write_bytes(b"\x89PNG\r\n\x1a\n" + struct.pack(">I", 13) + b"IHDR" + struct.pack(">II", width, height))


class PipelineTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.transcript = self.root / "talk.srt"
        self.transcript.write_text(
            "1\n00:00:00,000 --> 00:00:04,000\nRAG 不是简单的向量数据库搜索，它还包括查询改写、检索策略、重排和生成约束。\n"
            "2\n00:00:04,000 --> 00:00:09,000\n真正决定效果的，是整条信息链路是否能让模型获得正确上下文，而不是只看召回数量。\n",
            encoding="utf-8",
        )
        self.photo = self.root / "front.png"
        fake_png(self.photo, 1200, 1600)
        self.state_dir = self.root / "state"

    def tearDown(self) -> None:
        self.temp.cleanup()

    def run_cli(self, *args: str, expected: int = 0) -> dict:
        result = subprocess.run(
            [sys.executable, str(SCRIPT), *args], capture_output=True, text=True, cwd=self.root
        )
        self.assertEqual(result.returncode, expected, result.stdout + result.stderr)
        return json.loads(result.stdout)

    def start(self, channel: str = "", website: str = "") -> dict:
        args = [
            "start", "--transcript", str(self.transcript), "--photo", str(self.photo),
            "--state-dir", str(self.state_dir),
        ]
        if channel:
            args.extend(["--channel-name", channel])
        if website:
            args.extend(["--website", website])
        return self.run_cli(*args)

    def analyze(self, state: str) -> None:
        self.run_cli("approve-photo", "--state", state, "--front-photo", str(self.photo))
        self.run_cli(
            "record-analysis", "--state", state,
            "--core-thesis", "RAG 是完整信息链路",
            "--hook", "向量搜索只是第一步",
            "--evidence", "查询改写、检索策略、重排和生成约束共同决定效果",
        )

    @staticmethod
    def brand_tag(channel: str, with_hash: bool) -> str:
        return ("#" if with_hash else "") + channel

    def record_all_platforms(self, state: str, channel: str = "", website: str = "") -> None:
        website_line = f" 更多资料见 {website}" if website else ""

        youtube_tags = ["RAG", "检索增强生成", "AI应用", "大模型", "知识库"]
        if channel:
            youtube_tags.append(self.brand_tag(channel, True))
        args = [
            "record-platform", "--state", state, "--platform", "youtube",
            "--title", "RAG 完整链路指南 | 2026 新手教程",
            "--title", "RAG 不只是向量搜索 | 查询改写到重排",
            "--title", "向量库为什么救不了 RAG | 完整流程拆解",
            "--preferred", "2", "--reason", "关键词前置且准确呈现视频的反常识结论",
            "--body", ("RAG 的效果不只由向量检索决定。查询改写、检索策略、结果重排和生成约束共同决定模型能否获得正确上下文。" * 3) + website_line,
            "--timestamp", "00:00 什么才是完整的 RAG",
            "--timestamp", "00:04 决定效果的四个环节",
        ]
        for tag in youtube_tags:
            args.extend(["--tag", tag])
        self.run_cli(*args)

        bilibili_tags = ["RAG", "人工智能", "大模型", "知识库", "向量数据库", "检索增强", "AI教程", "技术科普"]
        bilibili_tags.append(channel if channel else "程序员")
        args = [
            "record-platform", "--state", state, "--platform", "bilibili",
            "--title", "【科普】RAG不只是向量搜索",
            "--title", "【干货】拆解RAG完整链路",
            "--title", "向量库为什么救不了RAG",
            "--preferred", "1", "--reason", "类型清晰并用反常识信息制造点击动机",
            "--body", ("很多人把 RAG 理解成向量数据库搜索，但真正的系统还包含查询改写、检索策略、结果重排和生成约束。本期从完整链路解释每一步为什么都会影响最终答案。" * 2) + website_line,
            "--dynamic", "RAG 真的只是向量搜索吗？这期把查询改写、检索、重排与生成约束放回同一条链路，看清效果到底由什么决定。",
        ]
        for tag in bilibili_tags:
            args.extend(["--tag", tag])
        self.run_cli(*args)

        xhs_tags = ["#RAG", "#人工智能", "#大模型", "#知识库", "#AI学习"]
        if channel:
            xhs_tags.append(self.brand_tag(channel, True))
        args = [
            "record-platform", "--state", state, "--platform", "xiaohongshu",
            "--title", "RAG不只是向量搜索🤔",
            "--title", "把RAG完整链路说清楚🧩",
            "--title", "向量库救不了RAG吗🔍",
            "--preferred", "1", "--reason", "反常识结论直接回应常见误区并保留解释空间",
            "--body", ("很多人第一次做 RAG，会把注意力全放在向量数据库和召回数量上。可真正跑起来后才会发现，问题往往出在更前面或更后面。查询有没有改写好，检索策略是否匹配任务，候选结果有没有重排，生成阶段有没有明确约束，都会改变模型最终拿到的上下文。🧩\n\n" * 3) + "这期把这些环节放回同一条链路逐一解释，也会说明为什么单纯增加召回数量不一定让答案更准确。适合正在搭建知识库、调试问答效果，或者刚开始理解 RAG 的朋友。🔍" + website_line,
        ]
        for tag in xhs_tags:
            args.extend(["--tag", tag])
        self.run_cli(*args)

        douyin_tags = ["#RAG", "#人工智能", "#大模型"]
        if channel:
            douyin_tags.append(self.brand_tag(channel, True))
        args = [
            "record-platform", "--state", state, "--platform", "douyin",
            "--title", "RAG不只是向量搜索",
            "--title", "向量库为什么救不了RAG？",
            "--title", "真正决定RAG效果的是这条链路",
            "--preferred", "3", "--reason", "直接给出完整观点并把答案留在视频正文中",
            "--body", "查询改写、检索策略、结果重排和生成约束，任何一环都可能决定 RAG 的最终效果。别再只盯着向量数据库。" + website_line,
        ]
        for tag in douyin_tags:
            args.extend(["--tag", tag])
        self.run_cli(*args)

        weixin_tags = ["#RAG", "#大模型", "#技术科普"]
        if channel:
            weixin_tags.append(self.brand_tag(channel, True))
        args = [
            "record-platform", "--state", state, "--platform", "weixin",
            "--short-title", "RAG完整链路",
            "--body", "RAG 并不等于向量数据库搜索。查询改写、检索策略、结果重排和生成约束共同决定模型能否拿到正确上下文，也决定最终回答是否可靠。本期用一条完整链路把这些关键环节讲清楚。" + website_line,
        ]
        for tag in weixin_tags:
            args.extend(["--tag", tag])
        self.run_cli(*args)

    def prepare_approved(self) -> tuple[str, Path]:
        state = self.start()["state"]
        self.analyze(state)
        self.record_all_platforms(state)
        written = self.run_cli("write-markdown", "--state", state)
        self.run_cli("record-plans", "--state", state, "--plan", "A", "--plan", "B", "--plan", "C")
        self.run_cli("approve-plan", "--state", state, "--plan", "B", "--confirm")
        return state, Path(written["markdown"])

    def test_missing_photo_fails_g0(self) -> None:
        payload = self.run_cli("start", "--transcript", str(self.transcript), "--state-dir", str(self.state_dir), expected=2)
        self.assertEqual(payload["gate"], "G0")

    def test_pair_generation_is_blocked_before_approval(self) -> None:
        started = self.start()
        payload = self.run_cli("can-generate-pair", "--state", started["state"], expected=3)
        self.assertFalse(payload["allowed"])

    def test_five_platform_markdown_and_pair_unlock(self) -> None:
        state, markdown = self.prepare_approved()
        self.assertTrue(markdown.is_file())
        content = markdown.read_text(encoding="utf-8")
        for heading in ("## YouTube", "## B站", "## 小红书", "## 抖音", "## 视频号"):
            self.assertIn(heading, content)
        self.assertIn("### 时间戳", content)
        self.assertIn("### 粉丝动态", content)
        self.assertNotIn("{频道名}", content)
        self.assertNotIn("{个人网站链接}", content)
        self.assertNotIn("推荐发布时间", content)
        payload = self.run_cli("can-generate-pair", "--state", state)
        self.assertTrue(payload["allowed"])
        self.assertEqual(payload["dispatch"], "concurrent-independent-calls")

    def test_optional_brand_is_required_only_when_supplied(self) -> None:
        channel = "硬核AI实验室"
        website = "https://example.com/resources"
        state = self.start(channel, website)["state"]
        self.analyze(state)
        self.record_all_platforms(state, channel, website)
        markdown = Path(self.run_cli("write-markdown", "--state", state)["markdown"])
        content = markdown.read_text(encoding="utf-8")
        self.assertIn(channel, content)
        self.assertIn(website, content)
        self.assertNotIn("{频道名}", content)
        self.assertNotIn("{个人网站链接}", content)

    def test_supplied_website_cannot_be_omitted_from_copy(self) -> None:
        state = self.start(website="https://example.com")["state"]
        self.analyze(state)
        payload = self.run_cli(
            "record-platform", "--state", state, "--platform", "douyin",
            "--title", "RAG不只是向量搜索", "--title", "向量库救不了RAG吗？", "--title", "RAG完整链路才是关键",
            "--preferred", "1", "--reason", "准确呈现视频中的核心反常识观点",
            "--body", "真正决定 RAG 效果的是查询改写、检索、重排和生成约束。",
            "--tag", "#RAG", "--tag", "#人工智能", "--tag", "#大模型",
            expected=2,
        )
        self.assertEqual(payload["gate"], "G3")

    def test_default_markdown_never_overwrites(self) -> None:
        existing = self.root / "outputs" / "talk-全平台发布方案.md"
        existing.parent.mkdir(parents=True)
        existing.write_text("user content", encoding="utf-8")
        state = self.start()["state"]
        self.analyze(state)
        self.record_all_platforms(state)
        written = Path(self.run_cli("write-markdown", "--state", state)["markdown"])
        self.assertEqual(written.name, "talk-全平台发布方案-v2.md")
        self.assertEqual(existing.read_text(encoding="utf-8"), "user content")

    def test_failed_generation_requires_new_authorization(self) -> None:
        state, _ = self.prepare_approved()
        failed = self.run_cli(
            "record-generation-failure", "--state", state, "--ratio", "3:4",
            "--issue", "图像服务返回错误",
        )
        self.assertEqual(failed["stage"], "G5_GENERATION_FAILED_AWAITING_RETRY_APPROVAL")
        blocked = self.run_cli("can-generate", "--state", state, "--ratio", "3:4", expected=3)
        self.assertFalse(blocked["allowed"])
        self.run_cli("authorize-retry", "--state", state, "--ratio", "3:4", "--confirm")
        allowed = self.run_cli("can-generate", "--state", state, "--ratio", "3:4")
        self.assertTrue(allowed["allowed"])

    def test_wrong_output_ratio_is_rejected(self) -> None:
        state, _ = self.prepare_approved()
        square = self.root / "square.png"
        fake_png(square, 1200, 1200)
        payload = self.run_cli("record-generation", "--state", state, "--ratio", "3:4", "--image", str(square), expected=2)
        self.assertEqual(payload["gate"], "G5")


if __name__ == "__main__":
    unittest.main()
