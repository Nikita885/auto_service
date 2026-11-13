"""Build reproducible 1C XML from reviewed sources; compile with Designer separately."""

import argparse
import xml.etree.ElementTree as ET
from pathlib import Path

MD = "http://v8.1c.ru/8.3/MDClasses"
V8 = "http://v8.1c.ru/8.1/data/core"
XR = "http://v8.1c.ru/8.3/xcf/readable"
FORM = "http://v8.1c.ru/8.3/xcf/logform"
NAME = "МойСервисРабочееМесто"
SOURCE = Path(__file__).resolve().parent


def sub(parent, tag, text=None, **attributes):
    element = ET.SubElement(parent, f"{{{MD}}}{tag}", attributes)
    element.text = text
    return element


def synonym(parent, value):
    item = ET.SubElement(sub(parent, "Synonym"), f"{{{V8}}}item")
    ET.SubElement(item, f"{{{V8}}}lang").text = "ru"
    ET.SubElement(item, f"{{{V8}}}content").text = value


def write(element, path):
    ET.indent(element, space="\t")
    path.parent.mkdir(parents=True, exist_ok=True)
    ET.ElementTree(element).write(path, encoding="utf-8", xml_declaration=True)


def generate(output):
    for prefix, uri in (("", MD), ("v8", V8), ("xr", XR)):
        ET.register_namespace(prefix, uri)
    root = ET.Element(f"{{{MD}}}MetaDataObject", version="2.20")
    processor = sub(root, "ExternalDataProcessor", uuid="83ed3273-2da6-41f8-a2fd-0378d85c5202")
    internal = sub(processor, "InternalInfo")
    generated = ET.SubElement(
        internal,
        f"{{{XR}}}GeneratedType",
        name=f"ExternalDataProcessorObject.{NAME}",
        category="Object",
    )
    ET.SubElement(generated, f"{{{XR}}}TypeId").text = "e63b061f-9303-4cbf-a31f-d8814f620201"
    ET.SubElement(generated, f"{{{XR}}}ValueId").text = "a9abe996-79ec-44a3-a130-8a933b002202"
    properties = sub(processor, "Properties")
    sub(properties, "Name", NAME)
    synonym(properties, "Мой Сервис — мастер")
    sub(properties, "Comment", "Прямое подключение к API. Платформа 8.5.1.1529.")
    sub(properties, "DefaultForm", f"ExternalDataProcessor.{NAME}.Form.Форма")
    sub(properties, "AuxiliaryForm")
    sub(sub(processor, "ChildObjects"), "Form", "Форма")
    write(root, output / f"{NAME}.xml")

    root = ET.Element(f"{{{MD}}}MetaDataObject", version="2.20")
    form = sub(root, "Form", uuid="a37a46ed-b3ae-45b7-9e14-89f7deac8201")
    properties = sub(form, "Properties")
    sub(properties, "Name", "Форма")
    synonym(properties, "Рабочее место мастера")
    sub(properties, "Comment")
    sub(properties, "FormType", "Managed")
    sub(properties, "IncludeHelpInContents", "false")
    write(root, output / NAME / "Forms/Форма.xml")

    root = ET.Element("Form", {"xmlns": FORM, "version": "2.20"})
    ET.SubElement(root, "AutoCommandBar", name="ФормаКоманднаяПанель", id="-1")
    events = ET.SubElement(root, "Events")
    ET.SubElement(events, "Event", name="OnCreateAtServer").text = "ПриСозданииНаСервере"
    ET.SubElement(events, "Event", name="BeforeClose").text = "ПередЗакрытием"
    for name in ("ChildItems", "Attributes", "Commands"):
        ET.SubElement(root, name)
    form_dir = output / NAME / "Forms/Форма/Ext"
    write(root, form_dir / "Form.xml")
    modules = [
        (SOURCE / f"{name}.bsl").read_text(encoding="utf-8-sig")
        for name in ("form", "http", "local", "payment")
    ]
    interface = (SOURCE / "interface.html").read_text(encoding="utf-8")
    assert interface.count("__DATA_JSON__") == 1
    template = '\n&НаСервереБезКонтекста\nФункция ШаблонИнтерфейса()\n    Возврат "'
    template += "\n    |".join(line.replace('"', '""') for line in interface.splitlines())
    template += '";\nКонецФункции\n'
    module_path = form_dir / "Form/Module.bsl"
    module_path.parent.mkdir(parents=True, exist_ok=True)
    module_path.write_text("\n\n".join(modules) + template, encoding="utf-8-sig")
    object_path = output / NAME / "Ext/ObjectModule.bsl"
    object_path.parent.mkdir(parents=True, exist_ok=True)
    object_path.write_text(
        (SOURCE / "object.bsl").read_text(encoding="utf-8-sig"), encoding="utf-8-sig"
    )
    return output / f"{NAME}.xml"


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, required=True)
    arguments = parser.parse_args()
    print(generate(arguments.out.resolve()))
