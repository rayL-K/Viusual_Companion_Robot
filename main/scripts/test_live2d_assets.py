"""Live2D 资源结构测试脚本。

这个脚本不负责真正渲染模型，而是先检查本地模型包是否满足后续渲染器的
基本输入要求：模型主文件可读、贴图存在、表情和动作文件结构完整。这样
我们在接入 Qt/Web/Electron 等显示方案之前，就能提前发现资源路径或 JSON
格式问题。
"""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional


PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_MODEL_ROOT = PROJECT_ROOT / "main" / "assets" / "live2d" / "Strawberry_Rabbit"
DEFAULT_REPORT = PROJECT_ROOT / "main" / "reports" / "live2d_asset_test_report.json"
PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"


@dataclass
class TestResult:
    """单项检查结果。

    `status` 使用英文枚举是为了方便后续机器读取；面向人的输出全部使用中文。
    """

    name: str
    status: str
    detail: str = ""


@dataclass
class Live2DAssetTester:
    """针对一个 Live2D 模型目录执行资源完整性检查。"""

    model_root: Path
    strict_ascii_paths: bool = True
    results: List[TestResult] = field(default_factory=list)
    errors: List[str] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)
    action_sequence: List[Dict[str, str]] = field(default_factory=list)

    def add_ok(self, name: str, detail: str = "") -> None:
        """记录一项通过的检查。"""

        self.results.append(TestResult(name=name, status="ok", detail=detail))

    def add_warning(self, name: str, detail: str) -> None:
        """记录一项不阻断测试的风险。"""

        message = f"{name}: {detail}"
        self.warnings.append(message)
        self.results.append(TestResult(name=name, status="warning", detail=detail))

    def add_error(self, name: str, detail: str) -> None:
        """记录一项会导致测试失败的问题。"""

        message = f"{name}: {detail}"
        self.errors.append(message)
        self.results.append(TestResult(name=name, status="error", detail=detail))

    def load_json(self, path: Path, label: str) -> Optional[Dict[str, Any]]:
        """读取 JSON 文件，并要求顶层结构是对象。"""

        try:
            with path.open("r", encoding="utf-8") as handle:
                data = json.load(handle)
        except Exception as exc:  # noqa: BLE001 - 这里需要把具体资源错误写入报告。
            self.add_error(label, f"JSON 无法解析：{path}（{exc}）")
            return None
        if not isinstance(data, dict):
            self.add_error(label, f"JSON 顶层必须是对象：{path}")
            return None
        return data

    def require_file(self, relative_path: str, label: str) -> Optional[Path]:
        """确认相对路径位于模型目录内，并且对应文件真实存在。"""

        path = (self.model_root / relative_path).resolve()
        try:
            path.relative_to(self.model_root.resolve())
        except ValueError:
            self.add_error(label, f"路径越过了模型根目录：{relative_path}")
            return None
        if not path.is_file():
            self.add_error(label, f"缺少文件：{relative_path}")
            return None
        if path.stat().st_size <= 0:
            self.add_error(label, f"文件为空：{relative_path}")
            return None
        return path

    def check_ascii_paths(self) -> None:
        """检查文件名是否适合 Windows、Linux 和脚本工具链稳定处理。"""

        non_ascii = [
            path.relative_to(self.model_root).as_posix()
            for path in self.model_root.rglob("*")
            if any(ord(char) > 127 for char in path.name)
        ]
        if non_ascii and self.strict_ascii_paths:
            self.add_error("ascii_paths", "存在非 ASCII 资源路径：" + ", ".join(non_ascii))
        elif non_ascii:
            self.add_warning("ascii_paths", "存在非 ASCII 资源路径：" + ", ".join(non_ascii))
        else:
            self.add_ok("ascii_paths", "所有资源文件名和目录名均为 ASCII")

    def check_png(self, relative_path: str) -> None:
        """快速验证贴图文件的 PNG 头部签名。"""

        path = self.require_file(relative_path, f"texture:{relative_path}")
        if path is None:
            return
        with path.open("rb") as handle:
            signature = handle.read(len(PNG_SIGNATURE))
        if signature != PNG_SIGNATURE:
            self.add_error(f"texture:{relative_path}", "PNG 文件头不正确")
        else:
            self.add_ok(f"texture:{relative_path}", f"{path.stat().st_size} 字节")

    def check_model3(self, manifest: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """检查 Live2D Cubism 的主模型文件和它引用的核心资源。"""

        model3_path = manifest.get("model3")
        if not isinstance(model3_path, str):
            self.add_error("manifest.model3", "model3 字段必须是字符串")
            return None
        path = self.require_file(model3_path, "model3")
        if path is None:
            return None
        model3 = self.load_json(path, "model3")
        if model3 is None:
            return None
        if model3.get("Version") != 3:
            self.add_warning("model3.version", f"期望 Version=3，实际为 {model3.get('Version')!r}")

        refs = model3.get("FileReferences")
        if not isinstance(refs, dict):
            self.add_error("model3.FileReferences", "缺少 FileReferences 对象")
            return model3

        for key in ("Moc", "Physics", "DisplayInfo"):
            value = refs.get(key)
            if isinstance(value, str):
                self.require_file(value, f"model3.{key}")
            else:
                self.add_error(f"model3.{key}", "缺少字符串类型的资源引用")

        textures = refs.get("Textures")
        if not isinstance(textures, list) or not textures:
            self.add_error("model3.Textures", "Textures 必须是非空数组")
        else:
            for texture in textures:
                if isinstance(texture, str):
                    self.check_png(texture)
                else:
                    self.add_error("model3.Textures", f"贴图引用无效：{texture!r}")

        self.check_model3_expressions(refs, manifest)
        self.check_model3_motions(refs, manifest)
        self.check_model3_lipsync_group(model3)

        self.add_ok("model3", str(path.relative_to(PROJECT_ROOT)))
        return model3

    def check_model3_expressions(self, refs: Dict[str, Any], manifest: Dict[str, Any]) -> None:
        """确认渲染器可从 model3.json 发现表情文件。"""

        manifest_expressions = manifest.get("expressions")
        model_expressions = refs.get("Expressions")
        if not isinstance(manifest_expressions, dict):
            return
        if not isinstance(model_expressions, list) or not model_expressions:
            self.add_error("model3.Expressions", "model3.json 未声明 Expressions，渲染器无法直接触发表情")
            return
        model_map = {
            item.get("Name"): item.get("File")
            for item in model_expressions
            if isinstance(item, dict)
        }
        for name, relative_path in manifest_expressions.items():
            if model_map.get(name) != relative_path:
                self.add_error("model3.Expressions", f"表情 {name} 未与 manifest 保持一致")
        self.add_ok("model3.Expressions", f"{len(model_expressions)} 个表情声明")

    def check_model3_motions(self, refs: Dict[str, Any], manifest: Dict[str, Any]) -> None:
        """确认渲染器可从 model3.json 发现动作文件。"""

        manifest_motions = manifest.get("motions")
        model_motions = refs.get("Motions")
        if not isinstance(manifest_motions, dict):
            return
        if not isinstance(model_motions, dict) or not model_motions:
            self.add_error("model3.Motions", "model3.json 未声明 Motions，渲染器无法直接触发动作")
            return
        for name, relative_path in manifest_motions.items():
            motion_group = model_motions.get(name)
            if (
                not isinstance(motion_group, list)
                or not motion_group
                or not isinstance(motion_group[0], dict)
                or motion_group[0].get("File") != relative_path
            ):
                self.add_error("model3.Motions", f"动作 {name} 未与 manifest 保持一致")
        self.add_ok("model3.Motions", f"{len(model_motions)} 个动作组声明")

    def check_model3_lipsync_group(self, model3: Dict[str, Any]) -> None:
        """确认 model3.json 声明了嘴部同步参数。"""

        groups = model3.get("Groups")
        if not isinstance(groups, list):
            self.add_error("model3.Groups", "缺少 Groups 数组")
            return
        for group in groups:
            if (
                isinstance(group, dict)
                and group.get("Name") == "LipSync"
                and "ParamMouthOpenY" in group.get("Ids", [])
            ):
                self.add_ok("model3.LipSync", "ParamMouthOpenY")
                return
        self.add_error("model3.LipSync", "LipSync 分组未包含 ParamMouthOpenY")

    def check_expression(self, name: str, relative_path: str) -> None:
        """检查一个表情文件是否包含可驱动的参数变化。"""

        path = self.require_file(relative_path, f"expression:{name}")
        if path is None:
            return
        data = self.load_json(path, f"expression:{name}")
        if data is None:
            return
        if data.get("Type") != "Live2D Expression":
            self.add_warning(f"expression:{name}", f"Type 字段异常：{data.get('Type')!r}")
        params = data.get("Parameters")
        if not isinstance(params, list):
            self.add_error(f"expression:{name}", "Parameters 必须是数组")
            return
        for index, param in enumerate(params):
            if not isinstance(param, dict):
                self.add_error(f"expression:{name}", f"第 {index} 个参数必须是对象")
                continue
            if not isinstance(param.get("Id"), str) or not param["Id"]:
                self.add_error(f"expression:{name}", f"第 {index} 个参数的 Id 无效")
            if not isinstance(param.get("Value"), (int, float)):
                self.add_error(f"expression:{name}", f"第 {index} 个参数的 Value 无效")
            if param.get("Blend") not in {"Add", "Multiply", "Overwrite"}:
                self.add_warning(f"expression:{name}", f"第 {index} 个参数的 Blend 不常见：{param.get('Blend')!r}")
        self.action_sequence.append({"type": "expression", "name": name, "path": relative_path})
        self.add_ok(f"expression:{name}", f"{len(params)} 个参数")

    def check_motion(self, name: str, relative_path: str) -> None:
        """检查一个动作文件是否包含时间长度、帧率和曲线数据。"""

        path = self.require_file(relative_path, f"motion:{name}")
        if path is None:
            return
        data = self.load_json(path, f"motion:{name}")
        if data is None:
            return
        if data.get("Version") != 3:
            self.add_warning(f"motion:{name}", f"期望 Version=3，实际为 {data.get('Version')!r}")
        meta = data.get("Meta")
        curves = data.get("Curves")
        if not isinstance(meta, dict):
            self.add_error(f"motion:{name}", "Meta 必须是对象")
            return
        if not isinstance(curves, list) or not curves:
            self.add_error(f"motion:{name}", "Curves 必须是非空数组")
            return
        duration = meta.get("Duration")
        fps = meta.get("Fps")
        if not isinstance(duration, (int, float)) or duration <= 0:
            self.add_error(f"motion:{name}", f"Duration 无效：{duration!r}")
        if not isinstance(fps, (int, float)) or fps <= 0:
            self.add_error(f"motion:{name}", f"Fps 无效：{fps!r}")
        curve_count = meta.get("CurveCount")
        if isinstance(curve_count, int) and curve_count != len(curves):
            self.add_warning(f"motion:{name}", f"CurveCount={curve_count}，实际曲线数={len(curves)}")
        for index, curve in enumerate(curves):
            if not isinstance(curve, dict):
                self.add_error(f"motion:{name}", f"第 {index} 条曲线必须是对象")
                continue
            if not isinstance(curve.get("Target"), str) or not curve["Target"]:
                self.add_error(f"motion:{name}", f"第 {index} 条曲线的 Target 无效")
            if not isinstance(curve.get("Id"), str) or not curve["Id"]:
                self.add_error(f"motion:{name}", f"第 {index} 条曲线的 Id 无效")
            segments = curve.get("Segments")
            if not isinstance(segments, list) or not segments:
                self.add_error(f"motion:{name}", f"第 {index} 条曲线的 Segments 无效")
            elif not all(isinstance(value, (int, float)) for value in segments):
                self.add_error(f"motion:{name}", f"第 {index} 条曲线包含非数字片段值")
        self.action_sequence.append({"type": "motion", "name": name, "path": relative_path})
        self.add_ok(f"motion:{name}", f"{duration} 秒，{len(curves)} 条曲线")

    def run(self) -> Dict[str, Any]:
        """执行完整资源检查并返回可写入 JSON 的报告对象。"""

        if not self.model_root.is_dir():
            self.add_error("model_root", f"缺少模型目录：{self.model_root}")
            return self.to_report(None)

        self.check_ascii_paths()
        manifest_path = self.require_file("manifest.json", "manifest")
        if manifest_path is None:
            return self.to_report(None)

        manifest = self.load_json(manifest_path, "manifest")
        if manifest is None:
            return self.to_report(None)
        self.add_ok("manifest", str(manifest_path.relative_to(PROJECT_ROOT)))

        model3 = self.check_model3(manifest)

        expressions = manifest.get("expressions")
        if not isinstance(expressions, dict) or not expressions:
            self.add_error("manifest.expressions", "expressions 必须是非空对象")
        else:
            for name, relative_path in expressions.items():
                if isinstance(name, str) and isinstance(relative_path, str):
                    self.check_expression(name, relative_path)
                else:
                    self.add_error("manifest.expressions", f"表情条目无效：{name!r} -> {relative_path!r}")

        motions = manifest.get("motions")
        if not isinstance(motions, dict) or not motions:
            self.add_error("manifest.motions", "motions 必须是非空对象")
        else:
            for name, relative_path in motions.items():
                if isinstance(name, str) and isinstance(relative_path, str):
                    self.check_motion(name, relative_path)
                else:
                    self.add_error("manifest.motions", f"动作条目无效：{name!r} -> {relative_path!r}")

        return self.to_report(model3)

    def to_report(self, model3: Optional[Dict[str, Any]]) -> Dict[str, Any]:
        """把内部检查状态整理成稳定的报告结构。"""

        return {
            "model_root": str(self.model_root),
            "status": "pass" if not self.errors else "fail",
            "summary": {
                "checks": len(self.results),
                "errors": len(self.errors),
                "warnings": len(self.warnings),
                "actions": len(self.action_sequence),
                "expressions": len([item for item in self.action_sequence if item["type"] == "expression"]),
                "motions": len([item for item in self.action_sequence if item["type"] == "motion"]),
            },
            "model3_version": model3.get("Version") if isinstance(model3, dict) else None,
            "action_sequence": self.action_sequence,
            "results": [result.__dict__ for result in self.results],
            "errors": self.errors,
            "warnings": self.warnings,
        }


def parse_args() -> argparse.Namespace:
    """解析命令行参数。"""

    parser = argparse.ArgumentParser(description="检查 Live2D 模型资源和动作资源。")
    parser.add_argument("--model-root", type=Path, default=DEFAULT_MODEL_ROOT, help="Live2D 模型目录")
    parser.add_argument("--report", type=Path, default=DEFAULT_REPORT, help="测试报告输出路径")
    parser.add_argument(
        "--allow-non-ascii-paths",
        action="store_true",
        help="允许资源路径包含非 ASCII 字符，仅作为兼容性调试开关使用",
    )
    return parser.parse_args()


def main() -> int:
    """脚本入口，负责执行检查、写出报告并返回进程退出码。"""

    args = parse_args()
    tester = Live2DAssetTester(
        model_root=args.model_root.resolve(),
        strict_ascii_paths=not args.allow_non_ascii_paths,
    )
    report = tester.run()

    args.report.parent.mkdir(parents=True, exist_ok=True)
    with args.report.open("w", encoding="utf-8") as handle:
        json.dump(report, handle, ensure_ascii=False, indent=2)
        handle.write("\n")

    print("=== Live2D 资源结构测试 ===")
    print(f"模型目录：    {report['model_root']}")
    print(f"测试状态：    {report['status']}")
    print(f"检查数量：    {report['summary']['checks']}")
    print(f"动作总数：    {report['summary']['actions']}")
    print(f"表情数量：    {report['summary']['expressions']}")
    print(f"动作文件：    {report['summary']['motions']}")
    print(f"警告数量：    {report['summary']['warnings']}")
    print(f"错误数量：    {report['summary']['errors']}")
    print(f"报告路径：    {args.report}")

    if tester.warnings:
        print("\n警告：")
        for warning in tester.warnings:
            print(f"  - {warning}")

    if tester.errors:
        print("\n错误：")
        for error in tester.errors:
            print(f"  - {error}")
        return 1

    print("\n所有 Live2D 表情和动作资源均通过结构检查。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
