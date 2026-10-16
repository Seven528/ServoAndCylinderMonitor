"""Resolve explicit current-message targets against the bounded upload catalog.

This is an authority boundary, not an analysis planner. Ambiguous references stop
before a model/native call; unmentioned roles retain only a proven canvas source.
"""

from __future__ import annotations

import re
import unicodedata

from .storage import DemoError

ACTION = re.compile(
    r"分析|检查|检测|比对|比较|对比|评估|预览|查看|显示|查询|读取|概览|总结|汇总|列出|"
    r"报告|是否|有没有|怎么样|如何|干涉|净距|间距|压棒|元件|封装|"
    r"\b(?:analy[sz]e|check|compare|inspect|preview|show|read|report|clearance)\b",
    re.IGNORECASE,
)
NEGATIVE = re.compile(
    r"不要|不用|不需要|不必|无需|暂不|禁止|别(?:再|去)?(?:分析|处理|检查)|"
    r"\b(?:do not|don't|never|not)\b",
    re.IGNORECASE,
)
CURRENT_ONLY = re.compile(
    r"只(?:看|分析|检查|处理|查看|针对)(?:一下)?(?:当前|主图|主画布)|"
    r"\bonly (?:the )?(?:current|displayed|visible)\b",
    re.IGNORECASE,
)
BATCH = re.compile(r"批量|\bbatch\b", re.IGNORECASE)
ROLE = r"(?:pcbs?(?![a-z])|holders?(?![a-z])|文件|unis?(?![a-z]))"
GROUP = re.compile(
    r"(?<![a-z0-9])(?P<qual>(?:(?:所有|全部|每个|每份|这些|这|左侧|左栏|"
    r"已导入|导入|已上传|上传|勾选|选中|的|"
    r"[一二两三四五六七八九十]{1,3}(?:个|份|块|张)|\d{1,2}(?!\d)(?:个|份|块|张)?|"
    r"\b(?:all|each|selected|checked|imported|uploaded|three|two|four|five)\b)\s*){1,12})"
    r"(?P<role>" + ROLE + r")",
    re.IGNORECASE,
)
SELECTED = re.compile(r"勾选|选中|\b(?:selected|checked)\b", re.IGNORECASE)
ALL = re.compile(
    r"所有|全部|每个|每份|左侧|左栏|导入|上传|\b(?:all|each|imported|uploaded)\b",
    re.IGNORECASE,
)
NUMBER = re.compile(
    r"\d+|[一二两三四五六七八九十]+|\b(?:two|three|four|five)\b", re.IGNORECASE
)
ALIAS = re.compile(
    r"(?<![a-z0-9_])[a-z0-9]+(?:_[a-z0-9]+)*(?![a-z0-9_])", re.IGNORECASE
)


def normalized(value):
    return unicodedata.normalize("NFKC", value).casefold()


def number(value):
    if value.isdigit():
        return int(value)
    english = {"two": 2, "three": 3, "four": 4, "five": 5}
    if value in english:
        return english[value]
    digits = dict(zip("一二两三四五六七八九", [1, 2, 2, 3, 4, 5, 6, 7, 8, 9]))
    if "十" in value:
        tens, ones = value.split("十", 1)
        return digits.get(tens, 1) * 10 + digits.get(ones, 0)
    return digits.get(value, 0)


def request_text(message, files):
    """Quoted commands and negative clauses cannot grant additional authority."""
    text = normalized(message)
    text = re.sub(r"```[\s\S]*?```|(?m:^\s*>.*$)", " ", text)
    names = {normalized(f["name"]) for f in files}
    names |= {name[:-4] for name in names}

    def quoted(match):
        value = match.group(1).strip()
        # Quoted filenames/identifiers are valid targets; quoted prose is data.
        if value in names or re.fullmatch(r"[a-z0-9_.-]+", value):
            return value
        return " "

    text = re.sub(r'["“`「]([^"”`」\n]+)["”`」]', quoted, text)
    return "，".join(
        part
        for part in re.split(r"[，,；;。\n!?！？]", text)
        if not NEGATIVE.search(part)
        and not re.search(
            r"(?:报告|日志)(?:中|里)(?:提到|写|说)|例如|比如|示例|他说|"
            r"(?:为什么|为何|解释|上次|之前).*(?:批量|分析|报告)|\b(?:example|previously)\b",
            part,
            re.IGNORECASE,
        )
    )


def clarify(label, candidates, reason="无法唯一匹配"):
    names = "；".join(f["name"] for f in candidates[:5])
    suffix = f" 可用文件：{names}。" if names else ""
    raise DemoError(
        f"{label}{reason}，本轮未执行分析。请在消息中指定完整文件名或明确范围。"
        + suffix
        + " 已导入文件无需再次上传。"
    )


def role_near(text, start, end):
    before = re.search(
        r"(?<![a-z])(pcb|holder)\s*[:：_-]?\s*$", text[:start], re.IGNORECASE
    )
    after = re.match(r"\s*(?:的\s*)?(pcb|holder)(?![a-z])", text[end:], re.IGNORECASE)
    return (before or after).group(1).lower() if before or after else None


def named_targets(text, files):
    found = {"pcb": set(), "holder": set()}
    remaining = text
    # Longest names first, so a stem or alias cannot absorb a different full name.
    names = {normalized(f["name"]) for f in files}
    names |= {name[:-4] for name in names if len(name[:-4]) >= 3}
    for name in sorted(names, key=lambda x: (-len(x), x)):
        for match in list(
            re.finditer(
                r"(?<![a-z0-9_])" + re.escape(name) + r"(?![a-z0-9_])", remaining
            )
        ):
            role = role_near(text, match.start(), match.end())
            candidates = [
                f
                for f in files
                if name in {normalized(f["name"]), normalized(f["name"])[:-4]}
                and (not role or f["role"] == role)
            ]
            if len(candidates) != 1:
                clarify(name, candidates)
            file = candidates[0]
            found[file["role"]].add(file["id"])
            remaining = (
                remaining[: match.start()]
                + " " * len(match.group())
                + remaining[match.end() :]
            )
    # A missing full filename must not silently become a request for the canvas.
    missing = re.search(r"[^\s，,;；]+\.uni\b", remaining)
    if missing:
        clarify(missing.group(), files, "不在当前导入列表中")
    for match in ALIAS.finditer(remaining):
        token = match.group()
        role = role_near(text, match.start(), match.end())
        joined = re.fullmatch(r"(ep\d+)(holder|pcb)|(holder|pcb)(ep\d+)", token)
        if joined:
            token, role = (
                (joined[1], joined[2]) if joined[1] else (joined[4], joined[3])
            )
        if (
            len(token) < 2
            or not re.search(r"[a-z]", token)
            or (not role and not re.search(r"\d", token))
        ):
            continue
        if re.fullmatch(
            r"side[12]|\d+(?:mm|cm)|pcb|pcbs|holder|holders|panel|single|full|components|copper|drawings|mechanical|all|selected|checked|imported|uploaded|current|three|two|four|five|each|against|with|for|from|and|versus|vs|using|to|of|analyze|analyse|check|inspect",
            token,
        ):
            continue
        candidates = [
            f
            for f in files
            if re.search(
                r"(?<![a-z0-9])" + re.escape(token) + r"(?![a-z0-9])",
                normalized(f["name"]),
            )
            and (not role or f["role"] == role)
        ]
        if not candidates and not (role or re.fullmatch(r"ep\d+\w*|\d{4}n\w+", token)):
            continue  # Units, refdes and unrelated numeric prose are not file names.
        if len(candidates) != 1:
            clarify(
                token, candidates or [f for f in files if not role or f["role"] == role]
            )
        file = candidates[0]
        found[file["role"]].add(file["id"])
        remaining = (
            remaining[: match.start()]
            + " " * len(match.group())
            + remaining[match.end() :]
        )
    return {role: ids for role, ids in found.items() if ids}, remaining


def explicit_targets(message, files, selection, canvas_ids):
    """Return exact IDs, or None for an ordinary canvas-only message.

    Counts refer to all imported files of that role unless the user explicitly
    says selected, or supplies an exact named subset. Never pick the first N.
    """
    text = request_text(message, files)
    named, target_text = named_targets(text, files)
    if CURRENT_ONLY.search(target_text):
        return None
    groups = list(GROUP.finditer(target_text))
    batch = bool(BATCH.search(target_text))
    if not named and not (ACTION.search(text) and (groups or batch)):
        return None
    if re.search(
        r"除了|除外|之外|其余|另外|其他|\b(?:except|excluding|other)\b",
        target_text,
        re.IGNORECASE,
    ):
        clarify("排除式范围", files, "需要明确目标文件")
    targets = {role: set(ids) for role, ids in named.items()}
    for match in groups:
        qualifier, label = match.group("qual", "role")
        roles = (
            ["pcb"]
            if label.startswith("pcb")
            else ["holder"]
            if label.startswith("holder")
            else ["pcb", "holder"]
        )
        candidates = [f for f in files if f["role"] in roles]
        if SELECTED.search(qualifier):
            selected = {*selection.get("pcb_ids", []), selection.get("holder_id")}
            candidates = [f for f in candidates if f["id"] in selected]
        counts = [number(m.group()) for m in NUMBER.finditer(qualifier)]
        if len(counts) > 1:
            clarify(label, candidates, "的数量不明确")
        if counts and not ALL.search(qualifier) and not SELECTED.search(qualifier):
            named_ids = set().union(*(named.get(role, set()) for role in roles))
            if named_ids:
                candidates = [f for f in candidates if f["id"] in named_ids]
        if not candidates or (counts and len(candidates) != counts[0]):
            reason = (
                f"要求 {counts[0]} 份，但当前匹配 {len(candidates)} 份"
                if counts
                else "没有匹配的已导入文件"
            )
            clarify(label, candidates, reason)
        for role in roles:
            ids = {f["id"] for f in candidates if f["role"] == role}
            if not named.get(role, set()).issubset(ids):
                clarify(label, candidates, "的名称与数量/勾选范围冲突")
            targets[role] = ids
    if batch and "pcb" not in targets:
        # Bare batch language refers to checked PCBs, never hidden unchecked ones.
        candidates = [
            f
            for f in files
            if f["role"] == "pcb" and f["id"] in selection.get("pcb_ids", [])
        ]
        if not candidates:
            clarify("批量范围", [f for f in files if f["role"] == "pcb"], "尚未指定")
        targets["pcb"] = {f["id"] for f in candidates}
    # Replace only explicitly named roles, retaining a proven canvas companion.
    # A selected-but-unmentioned Holder is not a companion and is not admitted.
    result = set().union(*targets.values())
    result.update(
        f["id"] for f in files if f["id"] in canvas_ids and f["role"] not in targets
    )
    return result
