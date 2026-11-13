"""Проверка ссылок BSL на реальные метаданные и экспортные методы конфигурации."""

import argparse
import re
from pathlib import Path
from xml.etree import ElementTree as ET


def verify(config: Path):
    source = Path(__file__).parent
    text = "\n".join(p.read_text(encoding="utf-8-sig") for p in source.glob("*.bsl"))
    failures, checked = [], []
    for module, method in sorted(set(re.findall(r"\b(\w+)\.(\w+)\s*\(", text))):
        path = config / "CommonModules" / module / "Ext/Module.bsl"
        if not path.exists():
            continue
        body = path.read_text(encoding="utf-8-sig")
        pattern = rf"(?:Функция|Процедура)\s+{method}\s*\([^)]*\)\s*Экспорт"
        (checked if re.search(pattern, body, re.I) else failures).append(f"{module}.{method}")
    for family, name, method in sorted(
        set(re.findall(r"(?<![\w.])(Справочники|Документы)\.(\w+)\.(\w+)\s*\(", text))
    ):
        if method in ("ПолучитьСсылку", "ПустаяСсылка", "СоздатьДокумент", "СоздатьЭлемент"):
            continue
        folder = "Catalogs" if family == "Справочники" else "Documents"
        path = config / folder / name / "Ext/ManagerModule.bsl"
        body = path.read_text(encoding="utf-8-sig") if path.exists() else ""
        pattern = rf"(?:Функция|Процедура)\s+{method}\s*\([^)]*\)\s*Экспорт"
        (checked if re.search(pattern, body, re.I) else failures).append(
            f"{family}.{name}.{method}"
        )
    folders = {
        "Справочники": "Catalogs",
        "Документы": "Documents",
        "РегистрыСведений": "InformationRegisters",
        "Перечисления": "Enums",
    }
    for family, name in sorted(
        set(
            re.findall(
                r"(?<![\w.])(Справочники|Документы|РегистрыСведений|Перечисления)\.(\w+)", text
            )
        )
    ):
        path = config / folders[family] / (name + ".xml")
        (checked if path.exists() else failures).append(f"{family}.{name}")
    # Особенность этой конфигурации: GUID у работ и строка GUID у запасов.
    path = config / "DefinedTypes/УникальныйИдентификаторИС.xml"
    types = [item.text for item in ET.parse(path).iter() if item.tag.endswith("}Type")]
    if "xs:string" not in types:
        failures.append("УникальныйИдентификаторИС: ожидается xs:string")
    return checked, failures


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--report", type=Path, required=True)
    args = parser.parse_args()
    checked, failures = verify(args.config)
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(
        "# Статическая сверка с конфигурацией\n\n"
        f"Проверено: {len(checked)} ссылок. Несоответствий: {len(failures)}.\n\n"
        "Это проверка наличия экспортов и метаданных, а не запуск оборудования.\n\n"
        + "\n".join(f"- {item}" for item in checked)
        + "\n\n"
        + "\n".join(f"ОШИБКА: {item}" for item in failures),
        encoding="utf-8",
    )
    print(f"Checked {len(checked)} references; mismatches: {len(failures)}")
    raise SystemExit(bool(failures))
