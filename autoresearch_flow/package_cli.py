"""Small CLI seam; no legacy engine imports."""

from pathlib import Path

from .package_delivery import package


def add_commands(commands):
    p = commands.add_parser(
        "package", help="独立完整 QA 后直接生成三份 ZIP 与七项填表材料"
    )
    p.add_argument(
        "--package-root", type=Path, required=True, help="明确指定的最终提交包"
    )
    p.add_argument(
        "--qa-report",
        type=Path,
        required=True,
        help="包外独立 QA 报告；指定旧题时传新版原标准 standard/report.json",
    )
    p.add_argument(
        "--output-dir",
        type=Path,
        required=True,
        help="包外附件目录；已有目录内自动生成新批次，不覆盖",
    )
    p.add_argument("--legacy-review", type=Path,
                   help="指定旧题：包外原标准 review.json，对应官方 --standard-review")
    p.add_argument("--legacy-worksheet", type=Path,
                   help="指定旧题：含 standard_resolutions 的包外 legacy_review.json")
    p.add_argument("--legacy-result", type=Path,
                   help="指定旧题：standard-waiver.5 完整 report.json；与前两参数同时提供")
    p.add_argument("--name", help="完整包语义名称；子仓名固定，不默认添加题号")
    p.add_argument("--upload-limit-bytes", type=int, default=300_000_000)
    p.add_argument(
        "--part-bytes", type=int, help="默认 min(290000000, 上传上限)，超限才分卷"
    )
    p.add_argument(
        "--form-notes", type=Path, help="可选 Markdown 概述，不要求审批/引用 JSON"
    )


def dispatch(args):
    return package(
        args.package_root,
        args.qa_report,
        args.output_dir,
        name=args.name,
        upload_limit_bytes=args.upload_limit_bytes,
        part_bytes=args.part_bytes,
        form_notes=args.form_notes,
        legacy_review=args.legacy_review,
        legacy_worksheet=args.legacy_worksheet,
        legacy_result=args.legacy_result,
    )
