"""Decoder and material composer for Starfield's compiled component database."""

from __future__ import annotations

import copy
import io
import json
import struct
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Any, BinaryIO, Callable

from .crc import ResourceId, resource_id
from .errors import FormatError, MissingMaterialError


_LIMIT = 8 * 1024 * 1024
_MAT_EXTENSION = int.from_bytes(b"mat\0", "little")

_NULL = 0xFFFFFF01
_STRING = 0xFFFFFF02
_LIST = 0xFFFFFF03
_MAP = 0xFFFFFF04
_REF = 0xFFFFFF05
_INT8 = 0xFFFFFF08
_UINT8 = 0xFFFFFF09
_INT16 = 0xFFFFFF0A
_UINT16 = 0xFFFFFF0B
_INT32 = 0xFFFFFF0C
_UINT32 = 0xFFFFFF0D
_INT64 = 0xFFFFFF0E
_UINT64 = 0xFFFFFF0F
_BOOL = 0xFFFFFF10
_FLOAT = 0xFFFFFF11
_DOUBLE = 0xFFFFFF12

_BUILTIN_NAMES = {
    _NULL: "<null>",
    _STRING: "BSFixedString",
    _LIST: "<collection>",
    _MAP: "<collection>",
    _REF: "pointer",
    _INT8: "int8_t",
    _UINT8: "uint8_t",
    _INT16: "int16_t",
    _UINT16: "uint16_t",
    _INT32: "int32_t",
    _UINT32: "uint32_t",
    _INT64: "int64_t",
    _UINT64: "uint64_t",
    _BOOL: "bool",
    _FLOAT: "float",
    _DOUBLE: "double",
}

_REFERENCE_TYPES = {
    "BSMaterial::BlenderID",
    "BSMaterial::LayerID",
    "BSMaterial::MaterialID",
    "BSMaterial::TextureSetID",
    "BSMaterial::UVStreamID",
    "BSMaterial::LODMaterialID",
    "BSMaterial::LayeredMaterialID",
}

ROOT_MATERIAL_PATHS = (
    r"materials\layered\root\materials.mat",
    r"materials\layered\root\blenders.mat",
    r"materials\layered\root\texturesets.mat",
    r"materials\layered\root\uvstreams.mat",
    r"materials\layered\root\layers.mat",
    r"materials\layered\root\layeredmaterials.mat",
)


class _Input:
    def __init__(self, source: bytes | BinaryIO) -> None:
        self.stream = io.BytesIO(source) if isinstance(source, bytes) else source
        self.chunks_left = 0

    @property
    def position(self) -> int:
        return self.stream.tell()

    def seek(self, position: int) -> None:
        self.stream.seek(position)

    def bytes(self, length: int) -> bytes:
        if length < 0 or length > 2 * 1024 * 1024 * 1024:
            raise FormatError(f"Invalid read size {length}")
        data = self.stream.read(length)
        if len(data) != length:
            raise FormatError(f"Unexpected end of CDB at 0x{self.position:X}")
        return data

    def unpack(self, fmt: str) -> tuple[Any, ...]:
        size = struct.calcsize("<" + fmt)
        return struct.unpack("<" + fmt, self.bytes(size))

    def u8(self) -> int:
        return self.unpack("B")[0]

    def i8(self) -> int:
        return self.unpack("b")[0]

    def u16(self) -> int:
        return self.unpack("H")[0]

    def i16(self) -> int:
        return self.unpack("h")[0]

    def u32(self) -> int:
        return self.unpack("I")[0]

    def i32(self) -> int:
        return self.unpack("i")[0]

    def u64(self) -> int:
        return self.unpack("Q")[0]

    def i64(self) -> int:
        return self.unpack("q")[0]

    def f32(self) -> float:
        return self.unpack("f")[0]

    def f64(self) -> float:
        return self.unpack("d")[0]

    def string(self) -> str:
        length = self.u16()
        if not length:
            return ""
        raw = self.bytes(length)
        return raw[:-1].decode("utf-8", errors="replace") if raw[-1] == 0 else raw.decode(
            "utf-8", errors="replace"
        )

    def resource(self) -> ResourceId:
        filename, extension, directory = self.unpack("III")
        return ResourceId(directory, filename, extension)

    def chunk(self) -> tuple[bytes, int]:
        signature, size = self.unpack("4sI")
        self.chunks_left -= 1
        return signature, size

    def skip_collection(self) -> None:
        _signature, size = self.chunk()
        self.seek(self.position + size)


@dataclass(slots=True)
class _Field:
    name_ref: int
    type_ref: int
    offset: int
    size: int


@dataclass(slots=True)
class _Class:
    name_ref: int
    type_ref: int
    flags: int
    fields: list[_Field]

    @property
    def is_user(self) -> bool:
        return bool(self.flags & (1 << 2))


@dataclass(slots=True)
class _Object:
    persistent: ResourceId
    db_id: int
    parent: int
    parent_persistent: ResourceId
    has_data: bool


@dataclass(slots=True)
class _Component:
    object_id: int
    index: int
    type_id: int


@dataclass(slots=True)
class _ComponentType:
    class_name: str
    version: int
    is_empty: bool


class _Slot:
    """A mutable reference to one JSON value."""

    def __init__(self, parent: dict[Any, Any] | list[Any], key: Any) -> None:
        self.parent = parent
        self.key = key

    def set(self, value: Any) -> None:
        self.parent[self.key] = value

    def get(self) -> Any:
        return self.parent[self.key]


class MaterialDatabase:
    """A loaded `materialsbeta.cdb` with material export operations."""

    def __init__(self) -> None:
        self._input: _Input | None = None
        self._strings = b""
        self._classes: dict[int, _Class] = {}
        self._objects: dict[int, _Object] = {}
        self._components: list[_Component] = []
        self._component_types: dict[int, _ComponentType] = {}
        self._component_map: dict[int, list[tuple[_Component, int]]] = defaultdict(
            list
        )
        self._resource_to_db: dict[ResourceId, int] = {}
        self._component_json: list[dict[str, Any]] = []
        self._chunk_queue: list[tuple[_Slot, bool]] = []
        self._user_queue: list[tuple[_Slot, int]] = []

    @classmethod
    def from_bytes(cls, data: bytes) -> "MaterialDatabase":
        instance = cls()
        instance._load(_Input(data))
        return instance

    @classmethod
    def from_file(cls, path: str | Path) -> "MaterialDatabase":
        with Path(path).open("rb") as stream:
            return cls.from_bytes(stream.read())

    @classmethod
    def layered(cls, *databases: "MaterialDatabase") -> "MaterialDatabase":
        """Combine base and add-on databases in increasing priority order."""
        result = cls()
        for database in databases:
            component_offset = len(result._component_json)
            result._objects.update(database._objects)
            result._resource_to_db.update(database._resource_to_db)
            result._component_json.extend(database._component_json)
            for object_id, components in database._component_map.items():
                result._component_map[object_id].extend(
                    (component, json_index + component_offset)
                    for component, json_index in components
                )
        return result

    def _type_name(self, reference: int) -> str:
        if reference in _BUILTIN_NAMES:
            return _BUILTIN_NAMES[reference]
        item = self._classes.get(reference)
        offset = item.name_ref if item else reference
        if offset < 0 or offset >= len(self._strings):
            raise FormatError(f"Invalid CDB string reference 0x{offset:08X}")
        end = self._strings.find(b"\0", offset)
        if end < 0:
            end = len(self._strings)
        return self._strings[offset:end].decode("utf-8", errors="replace")

    def _field_name(self, reference: int) -> str:
        if reference < 0 or reference >= len(self._strings):
            raise FormatError(f"Invalid field name reference 0x{reference:08X}")
        end = self._strings.find(b"\0", reference)
        if end < 0:
            end = len(self._strings)
        return self._strings[reference:end].decode("utf-8", errors="replace")

    def _load(self, reader: _Input) -> None:
        self._input = reader
        signature, _header_size, _version, chunk_count = reader.unpack("4sIII")
        if signature != b"BETH":
            raise FormatError("Not a Bethesda component database")
        if chunk_count < 3 or chunk_count > _LIMIT:
            raise FormatError("Invalid CDB chunk count")
        reader.chunks_left = chunk_count - 1

        _signature, string_size = reader.chunk()
        if string_size > _LIMIT:
            raise FormatError("CDB string table exceeds safety limit")
        self._strings = reader.bytes(string_size)

        _signature, _type_chunk_size = reader.chunk()
        type_count = reader.u32()
        if type_count > _LIMIT:
            raise FormatError("CDB type table exceeds safety limit")
        for _ in range(type_count):
            _signature, size = reader.chunk()
            end = reader.position + size
            name_ref, type_ref, flags, field_count = reader.unpack("IIHH")
            if field_count > _LIMIT:
                raise FormatError("CDB field table exceeds safety limit")
            fields = [
                _Field(*reader.unpack("IIHH")) for _ in range(field_count)
            ]
            self._classes[name_ref] = _Class(name_ref, type_ref, flags, fields)
            if reader.position < end:
                reader.seek(end)

        seen_database = False
        seen_index = False
        for _ in range(2):
            _signature, _size = reader.chunk()
            type_reference = reader.u32()
            type_name = self._type_name(type_reference).casefold()
            if type_name == "bsmaterial::internal::compileddb":
                self._read_compiled_header(reader)
                seen_database = True
            elif type_name == "bscomponentdb2::dbfileindex":
                self._read_file_index(reader)
                seen_index = True
            else:
                raise FormatError(f"Unknown CDB database section {type_name}")
        if not seen_database or not seen_index:
            raise FormatError("CDB is missing a required database section")

        for index, component in enumerate(self._components):
            self._component_map[component.object_id].append((component, index))
        for object_info in self._objects.values():
            if object_info.persistent.extension == _MAT_EXTENSION:
                self._resource_to_db[object_info.persistent] = object_info.db_id

        for _ in self._components:
            self._component_json.append(self._read_next_object())

    def _read_compiled_header(self, reader: _Input) -> None:
        reader.string()
        reader.skip_collection()  # resource hash map
        reader.skip_collection()  # collisions
        reader.skip_collection()  # circular references

    def _collection(
        self, reader: _Input, item_reader: Callable[[], Any]
    ) -> list[Any]:
        signature, chunk_size = reader.chunk()
        if signature != b"LIST":
            raise FormatError(f"Expected CDB LIST chunk, got {signature!r}")
        end = reader.position + chunk_size
        _element_type, count = reader.unpack("II")
        if count > _LIMIT:
            raise FormatError("CDB collection exceeds safety limit")
        result = [item_reader() for _ in range(count)]
        if reader.position > end:
            raise FormatError("CDB collection exceeds its declared chunk")
        reader.seek(end)
        return result

    def _map_collection(
        self, reader: _Input, item_reader: Callable[[], Any]
    ) -> list[Any]:
        signature, chunk_size = reader.chunk()
        if signature != b"MAPC":
            raise FormatError(f"Expected CDB MAPC chunk, got {signature!r}")
        end = reader.position + chunk_size
        _key_type, _value_type, count = reader.unpack("III")
        if count > _LIMIT:
            raise FormatError("CDB map exceeds safety limit")
        result = [item_reader() for _ in range(count)]
        if reader.position > end:
            raise FormatError("CDB map exceeds its declared chunk")
        reader.seek(end)
        return result

    def _read_file_index(self, reader: _Input) -> None:
        reader.u8()  # optimized flag

        partial_types = self._map_collection(
            reader, lambda: reader.unpack("HHB")
        )
        for type_id, version, is_empty in partial_types:
            _signature, chunk_size = reader.chunk()
            end = reader.position + chunk_size
            reader.unpack("II")  # user target and cast type
            class_name = reader.string()
            reader.u32()
            self._component_types[type_id] = _ComponentType(
                class_name, version, bool(is_empty)
            )
            if reader.position < end:
                reader.seek(end)

        objects = self._collection(
            reader,
            lambda: _Object(
                reader.resource(),
                reader.u32(),
                reader.u32(),
                reader.resource(),
                bool(reader.u8()),
            ),
        )
        self._objects = {item.db_id: item for item in objects}
        self._components = self._collection(
            reader, lambda: _Component(*reader.unpack("IHH"))
        )
        self._collection(reader, lambda: reader.unpack("IIHH"))  # edges

    def _read_next_object(self) -> dict[str, Any]:
        box: dict[str, Any] = {"value": {}}
        root = _Slot(box, "value")
        self._read_chunk(root)
        while self._chunk_queue or self._user_queue:
            self._read_chunk(root)
        value = root.get()
        if not isinstance(value, dict):
            raise FormatError("A component root was not an object")
        return value

    def _read_chunk(self, root: _Slot) -> None:
        assert self._input is not None
        reader = self._input
        signature, _size = reader.chunk()
        if signature in {b"OBJT", b"DIFF"}:
            self._read_type(root, reader.u32(), signature == b"DIFF")
        elif signature in {b"USER", b"USRD"}:
            if not self._user_queue:
                raise FormatError("CDB USER chunk has no pending cast")
            _target, casted = reader.unpack("II")
            slot, _queued_type = self._user_queue.pop()
            self._read_type(slot, casted, signature == b"USRD", is_cast=True)
            reader.u32()
        elif signature in {b"LIST", b"MAPC"}:
            if not self._chunk_queue:
                raise FormatError("CDB collection chunk has no pending field")
            slot, is_diff = self._chunk_queue.pop()
            if signature == b"LIST":
                self._read_list(slot, is_diff)
            else:
                self._read_map(slot, is_diff)
        else:
            raise FormatError(f"Unsupported CDB chunk {signature!r}")

    def _read_list(self, slot: _Slot, is_diff: bool) -> None:
        assert self._input is not None
        element_type, count = self._input.unpack("II")
        if count > _LIMIT:
            raise FormatError("CDB list exceeds safety limit")
        value: dict[str, Any] = {"Type": "<collection>"}
        data: list[Any] = []
        value["Data"] = data
        if count:
            value["ElementType"] = self._type_name(element_type)
        slot.set(value)
        for _ in range(count):
            data.append(None)
            self._read_type(_Slot(data, len(data) - 1), element_type, is_diff)

    def _scalar_key(self, reference: int) -> str:
        assert self._input is not None
        reader = self._input
        if reference == _STRING:
            return reader.string()
        readers: dict[int, Callable[[], Any]] = {
            _INT8: reader.i8,
            _UINT8: reader.u8,
            _INT16: reader.i16,
            _UINT16: reader.u16,
            _INT32: reader.i32,
            _UINT32: reader.u32,
            _INT64: reader.i64,
            _UINT64: reader.u64,
            _BOOL: lambda: bool(reader.u8()),
            _FLOAT: reader.f32,
            _DOUBLE: reader.f64,
        }
        try:
            value = readers[reference]()
        except KeyError as exc:
            raise FormatError(f"Unsupported CDB map key {self._type_name(reference)}") from exc
        if isinstance(value, bool):
            return "true" if value else "false"
        if isinstance(value, float):
            return f"{value:f}"
        return str(value)

    def _read_map(self, slot: _Slot, is_diff: bool) -> None:
        assert self._input is not None
        key_type, value_type, count = self._input.unpack("III")
        if count > _LIMIT:
            raise FormatError("CDB map exceeds safety limit")
        value: dict[str, Any] = {
            "Type": "<collection>",
            "ElementType": "StdMapType::Pair",
            "Data": [],
        }
        slot.set(value)
        if key_type in _BUILTIN_NAMES:
            data = value["Data"]
            for _ in range(count):
                pair = {
                    "Type": "StdMapType::Pair",
                    "Data": {"Key": self._scalar_key(key_type), "Value": None},
                }
                data.append(pair)
                self._read_type(
                    _Slot(pair["Data"], "Value"), value_type, is_diff
                )
        elif self._type_name(key_type).casefold() == "bsresource::id":
            value["Data"] = None
            for _ in range(count):
                key = str(self._input.resource())
                value[key] = None
                self._read_type(_Slot(value, key), value_type, is_diff)
        else:
            raise FormatError(f"Unsupported CDB map key {self._type_name(key_type)}")

    def _read_type(
        self, slot: _Slot, reference: int, is_diff: bool, *, is_cast: bool = False
    ) -> None:
        assert self._input is not None
        reader = self._input
        if reference == _NULL:
            slot.set(None)
        elif reference == _STRING:
            slot.set(reader.string())
        elif reference in {_LIST, _MAP}:
            raise FormatError("Collection type appeared outside its chunk")
        elif reference == _REF:
            target = reader.u32()
            if target == _NULL:
                slot.set(None)
            elif target in _BUILTIN_NAMES:
                raise FormatError("Reference points to a non-null builtin type")
            else:
                value = {"Type": "<ref>", "Data": None}
                slot.set(value)
                data_slot = _Slot(value, "Data")
                type_info = self._classes.get(target)
                if type_info is None:
                    raise FormatError(f"Reference type 0x{target:08X} is missing")
                if type_info.is_user:
                    self._user_queue.append((data_slot, target))
                else:
                    self._read_type(data_slot, target, is_diff)
        elif reference in {
            _INT8,
            _UINT8,
            _INT16,
            _UINT16,
            _INT32,
            _UINT32,
            _INT64,
            _UINT64,
            _BOOL,
            _FLOAT,
            _DOUBLE,
        }:
            readers: dict[int, Callable[[], Any]] = {
                _INT8: reader.i8,
                _UINT8: reader.u8,
                _INT16: reader.i16,
                _UINT16: reader.u16,
                _INT32: reader.i32,
                _UINT32: reader.u32,
                _INT64: reader.i64,
                _UINT64: reader.u64,
                _BOOL: lambda: bool(reader.u8()),
                _FLOAT: reader.f32,
                _DOUBLE: reader.f64,
            }
            scalar = readers[reference]()
            if isinstance(scalar, bool):
                slot.set("true" if scalar else "false")
            elif isinstance(scalar, float):
                slot.set(f"{scalar:f}")
            else:
                slot.set(str(scalar))
        else:
            type_name = self._type_name(reference)
            if type_name.casefold() == "bscomponentdb2::id":
                if is_diff:
                    reader.u16()
                db_id = reader.u32()
                if is_diff:
                    reader.u16()
                slot.set(str(db_id) if db_id else "")
                return
            type_info = self._classes.get(reference)
            if type_info is None:
                raise FormatError(f"CDB type 0x{reference:08X} is missing")
            if type_info.is_user and not is_cast:
                self._user_queue.append((slot, reference))
                return
            value: dict[str, Any] = {"Type": type_name, "Data": {}}
            slot.set(value)
            data = value["Data"]
            def read_field(field: _Field) -> None:
                name = self._field_name(field.name_ref)
                data[name] = None
                field_slot = _Slot(data, name)
                if field.type_ref in {_LIST, _MAP}:
                    self._chunk_queue.append((field_slot, is_diff))
                else:
                    self._read_type(field_slot, field.type_ref, is_diff)

            if not is_diff:
                for field in type_info.fields:
                    read_field(field)
            else:
                field_index = reader.u16()
                while field_index != 0xFFFF:
                    if field_index >= len(type_info.fields):
                        raise FormatError("CDB diff field index is out of range")
                    read_field(type_info.fields[field_index])
                    field_index = reader.u16()

    def _parent_chain(self, db_id: int) -> list[int]:
        result: list[int] = []
        seen: set[int] = set()
        current = db_id
        while current:
            if current in seen:
                raise FormatError("Cycle in CDB parent graph")
            seen.add(current)
            result.append(current)
            item = self._objects.get(current)
            if item is None:
                break
            current = item.parent
        return result

    @staticmethod
    def _compose(left: Any, right: Any) -> Any:
        if isinstance(right, dict):
            if not right:
                return {}
            if isinstance(left, str):
                return left
            target = left if isinstance(left, dict) else {}
            for key, value in right.items():
                target[key] = MaterialDatabase._compose(target.get(key), value)
            return target
        if isinstance(right, list):
            if not right:
                return []
            target = left if isinstance(left, list) else []
            while len(target) < len(right):
                target.append(None)
            for index, value in enumerate(right):
                if value is not None:
                    target[index] = MaterialDatabase._compose(
                        target[index], value
                    )
            return target
        return copy.deepcopy(right)

    def _full_components(self, db_id: int) -> list[dict[str, Any]]:
        result: list[dict[str, Any]] = []
        for ancestor in reversed(self._parent_chain(db_id)):
            for component, json_index in self._component_map.get(ancestor, []):
                source = self._component_json[json_index]
                source_type = str(source.get("Type", ""))
                target = next(
                    (
                        item
                        for item in result
                        if item.get("Index") == component.index
                        and str(item.get("Type", "")).casefold()
                        == source_type.casefold()
                    ),
                    None,
                )
                if target is None:
                    target = {"Type": source_type, "Index": component.index}
                    result.append(target)
                target["Data"] = self._compose(
                    target.get("Data"), source.get("Data")
                )
        return result

    def _set_parent(
        self, value: dict[str, Any], db_id: int, id_to_path: dict[int, str]
    ) -> None:
        for ancestor in self._parent_chain(db_id)[1:]:
            if ancestor in id_to_path:
                value["Parent"] = id_to_path[ancestor]
                return
        raise FormatError(f"No exported parent path for database object {db_id:08X}")

    def _referenced_ids(self, value: Any, pending: list[int], seen: set[int]) -> None:
        if not isinstance(value, dict):
            return
        if value.get("Type") in _REFERENCE_TYPES:
            data = value.get("Data")
            if not isinstance(data, dict):
                return
            raw_id = data.get("ID")
            if not isinstance(raw_id, str) or not raw_id:
                return
            try:
                db_id = int(raw_id)
            except ValueError:
                return
            object_info = self._objects.get(db_id)
            if object_info is None:
                return
            data["ID"] = str(object_info.persistent)
            if db_id not in seen:
                seen.add(db_id)
                pending.append(db_id)
            return
        data = value.get("Data")
        children = data.values() if isinstance(data, dict) else data if isinstance(data, list) else ()
        for child in children:
            if isinstance(child, dict) and "Type" in child:
                self._referenced_ids(child, pending, seen)

    def material_id(self, path: str) -> int:
        return self._resource_to_db.get(resource_id(path), 0)

    def export_document(
        self, path: str, available_paths: dict[int, str]
    ) -> dict[str, Any]:
        db_id = self.material_id(path)
        if not db_id or not self._component_map.get(db_id):
            raise MissingMaterialError(f"Material is not present in the database: {path}")

        root: dict[str, Any] = {"Components": self._full_components(db_id)}
        self._set_parent(root, db_id, available_paths)
        document: dict[str, Any] = {"Version": 1, "Objects": [root]}
        pending: list[int] = []
        seen = {db_id}
        for component in root["Components"]:
            self._referenced_ids(component, pending, seen)

        while pending:
            referenced_id = pending.pop()
            info = self._objects.get(referenced_id)
            if info is None:
                continue
            item: dict[str, Any] = {
                "ID": str(info.persistent),
                "Components": self._full_components(referenced_id),
            }
            self._set_parent(item, referenced_id, available_paths)
            document["Objects"].append(item)
            for component in item["Components"]:
                self._referenced_ids(component, pending, seen)
        return document

    def write_materials(
        self, paths: list[str], output: str | Path
    ) -> list[Path]:
        id_to_path: dict[int, str] = {}
        for path in [*paths, *ROOT_MATERIAL_PATHS]:
            db_id = self.material_id(path)
            if db_id:
                id_to_path.setdefault(db_id, path)

        output_root = Path(output)
        written: list[Path] = []
        for material_path in paths:
            try:
                document = self.export_document(material_path, id_to_path)
            except MissingMaterialError:
                continue
            relative = Path(*material_path.replace("/", "\\").split("\\"))
            destination = output_root / relative
            destination.parent.mkdir(parents=True, exist_ok=True)
            destination.write_text(
                json.dumps(document, indent=2, ensure_ascii=False),
                encoding="utf-8",
            )
            written.append(destination)
        return written


def load_material_database(path: str | Path) -> MaterialDatabase:
    database_path = Path(path)
    if database_path.suffix.casefold() == ".cdb":
        return MaterialDatabase.from_file(database_path)
    if database_path.suffix.casefold() == ".ba2":
        from .ba2 import Ba2Archive

        archive = Ba2Archive.open(database_path)
        entry = archive.find("materials/materialsbeta.cdb")
        if entry is None:
            candidates = [
                candidate
                for candidate in archive.entries
                if candidate.name.replace("\\", "/").casefold().endswith(
                    "/materialsbeta.cdb"
                )
                or candidate.name.casefold() == "materialsbeta.cdb"
            ]
            if not candidates:
                raise FormatError(
                    f"No materialsbeta.cdb is present in {database_path}"
                )
            if len(candidates) > 1:
                names = ", ".join(candidate.name for candidate in candidates)
                raise FormatError(
                    f"Multiple material databases are present in "
                    f"{database_path}: {names}"
                )
            entry = candidates[0]
        data = archive.read(entry)
        return MaterialDatabase.from_bytes(data)
    raise FormatError(f"Expected a .cdb or .ba2 database, got {database_path}")
