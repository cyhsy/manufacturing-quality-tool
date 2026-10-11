"""知识库 Markdown 解析公共工具。

`knowledge/equipment/`（设备故障）与 `knowledge/quality/`（质量改善）使用同一套
Markdown 结构：

    # 标题

    键: 值                 <- 元数据行（案例编号 / 类别 / 适用设备 等）
    关联信号: 温度, 振动    <- 元数据行，值可用 , / ，/ 、 分隔

    现象:                  <- 段落标题（独占一行，以 : 或 ： 结尾）
    具体条目（每行一条，可带 "- " 前缀）

    原因:
    ...

解析规则（与两个知识库的既有实现保持一致）：

- ``#`` 开头的行为标题（取第一条）；
- 以 ``:`` / ``：`` 结尾且名称在 ``section_keys`` 中的行，开启该段落；
- 形如 ``键: 值`` 且键在 ``metadata_keys`` 中的行，记为元数据并结束当前段落；
- 其余非空行若处于某段落中，则作为该段落条目（自动去掉 ``- `` 前缀）。
"""

import re


_LIST_SEPARATOR_PATTERN = re.compile(r"[,，、;；]")


def split_list(value):
    """把 "温度, 振动 / 主轴" 之类的元数据值拆成列表。"""
    if value is None:
        return []
    return [item.strip() for item in _LIST_SEPARATOR_PATTERN.split(str(value)) if item.strip()]


def parse_case_text(text, section_keys, metadata_keys, fallback_title=""):
    """解析单条案例 Markdown。

    参数：
        text:            Markdown 全文。
        section_keys:    需要识别的段落名，如 ("现象", "原因", "验证方法", "改善措施")。
        metadata_keys:   需要识别的元数据键，如 ("案例编号", "类别", "适用工序", "关联缺陷")。
        fallback_title:  没有标题行时使用的标题（通常是文件名）。

    返回：
        (title, metadata, sections)
    """
    section_keys = tuple(section_keys)
    metadata_keys = tuple(metadata_keys)

    title = ""
    metadata = {}
    sections = {key: [] for key in section_keys}
    current_section = None

    for raw_line in str(text).splitlines():
        line = raw_line.strip()
        if not line:
            continue

        if line.startswith("#"):
            if not title:
                title = line.lstrip("#").strip()
            continue

        # 段落标题，例如 "现象:"
        if line.endswith((":", "：")):
            name = line[:-1].strip()
            if name in section_keys:
                current_section = name
                continue

        matched = False
        if ":" in line or "：" in line:
            separator = ":" if ":" in line else "："
            key, _, value = line.partition(separator)
            key = key.strip()
            value = value.strip()

            if key in section_keys and value:
                sections[key].append(value)
                current_section = key
                matched = True
            elif key in metadata_keys:
                metadata[key] = value
                current_section = None
                matched = True

        if not matched and current_section:
            sections[current_section].append(line.lstrip("-").strip())

    return title or fallback_title, metadata, sections
