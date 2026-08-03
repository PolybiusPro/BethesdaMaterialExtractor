from __future__ import annotations

import struct
import tempfile
import unittest
from pathlib import Path

from bme import cdb
from bme.cdb import MaterialDatabase, load_material_database
from bme.crc import ResourceId, resource_id
from bme.service import export_from_inputs


def _chunk(signature: bytes, payload: bytes) -> bytes:
    return struct.pack("<4sI", signature, len(payload)) + payload


def _empty_collection() -> bytes:
    return _chunk(b"LIST", struct.pack("<II", 0xFFFFFF01, 0))


def _empty_map() -> bytes:
    return _chunk(
        b"MAPC", struct.pack("<III", cdb._UINT16, cdb._NULL, 0)
    )


def _minimal_database() -> bytes:
    compiled_name = b"BSMaterial::Internal::CompiledDB\0"
    index_name = b"BSComponentDB2::DBFileIndex\0"
    strings = compiled_name + index_name

    string_chunk = _chunk(b"STRT", strings)
    type_chunk = _chunk(b"TYPE", struct.pack("<I", 0))
    compiled_body = (
        struct.pack("<H2s", 2, b"x\0")
        + _empty_map()
        + _empty_collection()
        + _empty_collection()
    )
    compiled = _chunk(b"OBJT", struct.pack("<I", 0) + compiled_body)
    index_body = (
        struct.pack("<B", 0)
        + _empty_map()
        + _empty_collection()
        + _empty_collection()
        + _empty_collection()
    )
    index = _chunk(
        b"OBJT", struct.pack("<I", len(compiled_name)) + index_body
    )
    body = string_chunk + type_chunk + compiled + index
    return struct.pack("<4sIII", b"BETH", len(body), 1, 12) + body


def _single_file_ba2(path: Path, name: str, payload: bytes) -> None:
    encoded_name = name.encode("utf-8")
    header_size = 24
    record_size = 12 + 4 + 20
    data_offset = header_size + record_size
    names_offset = data_offset + len(payload)
    header = struct.pack("<4sI4sIQ", b"BTDX", 1, b"GNRL", 1, names_offset)
    hash_record = struct.pack("<III", 1, 2, 3)
    file_record = struct.pack("<BBH", 0, 1, 0x10)
    chunk = struct.pack(
        "<QIII", data_offset, 0, len(payload), 0xBAADF00D
    )
    names = struct.pack("<H", len(encoded_name)) + encoded_name
    path.write_bytes(header + hash_record + file_record + chunk + payload + names)


def _single_texture_ba2(path: Path, name: str, payload: bytes) -> None:
    encoded_name = name.encode("utf-8")
    header_size = 24
    record_size = 24
    chunk_size = 24
    data_offset = header_size + record_size + chunk_size
    names_offset = data_offset + len(payload)
    header = struct.pack("<4sI4sIQ", b"BTDX", 1, b"DX10", 1, names_offset)
    record = struct.pack(
        "<I4sIBBHHHBBH",
        1,
        b"dds\0",
        2,
        0,
        1,
        chunk_size,
        4,
        4,
        1,
        80,
        0x0800,
    )
    chunk = struct.pack(
        "<QIIHHI", data_offset, 0, len(payload), 0, 0, 0xBAADF00D
    )
    names = struct.pack("<H", len(encoded_name)) + encoded_name
    path.write_bytes(header + record + chunk + payload + names)


def _collection(element_type: int, items: bytes, count: int) -> bytes:
    return _chunk(b"LIST", struct.pack("<II", element_type, count) + items)


def _map(
    key_type: int, value_type: int, items: bytes, count: int
) -> bytes:
    return _chunk(
        b"MAPC",
        struct.pack("<III", key_type, value_type, count) + items,
    )


def _resource(value: ResourceId) -> bytes:
    return struct.pack("<III", value.filename, value.extension, value.directory)


def _exportable_database(material_path: str, parent_path: str) -> bytes:
    names = [
        "BSMaterial::Internal::CompiledDB",
        "BSComponentDB2::DBFileIndex",
        "ExampleComponent",
        "Value",
    ]
    offsets: dict[str, int] = {}
    table = bytearray()
    for name in names:
        offsets[name] = len(table)
        table.extend(name.encode() + b"\0")

    string_chunk = _chunk(b"STRT", bytes(table))
    class_payload = struct.pack(
        "<IIHHIIHH",
        offsets["ExampleComponent"],
        offsets["ExampleComponent"],
        0,
        1,
        offsets["Value"],
        cdb._UINT32,
        0,
        4,
    )
    type_chunk = _chunk(b"TYPE", struct.pack("<I", 1)) + _chunk(
        b"CLSS", class_payload
    )

    compiled_body = (
        struct.pack("<H2s", 2, b"x\0")
        + _empty_map()
        + _empty_collection()
        + _empty_collection()
    )
    compiled = _chunk(
        b"OBJT",
        struct.pack("<I", offsets["BSMaterial::Internal::CompiledDB"])
        + compiled_body,
    )

    partial_types = _map(
        cdb._UINT16,
        offsets["ExampleComponent"],
        struct.pack("<HHB", 7, 1, 0),
        1,
    )
    encoded_class = b"ExampleComponent\0"
    type_metadata = _chunk(
        b"USER",
        struct.pack("<IIH", 0, offsets["ExampleComponent"], len(encoded_class))
        + encoded_class
        + struct.pack("<I", 0),
    )
    parent_id = resource_id(parent_path)
    material_id = resource_id(material_path)
    empty_resource = ResourceId(0, 0, 0)
    objects = b"".join(
        (
            _resource(parent_id)
            + struct.pack("<II", 1, 0)
            + _resource(empty_resource)
            + struct.pack("<B", 0),
            _resource(material_id)
            + struct.pack("<II", 2, 1)
            + _resource(parent_id)
            + struct.pack("<B", 1),
        )
    )
    index_body = (
        struct.pack("<B", 0)
        + partial_types
        + type_metadata
        + _collection(0, objects, 2)
        + _collection(0, struct.pack("<IHH", 2, 0, 7), 1)
        + _empty_collection()
    )
    index = _chunk(
        b"OBJT",
        struct.pack("<I", offsets["BSComponentDB2::DBFileIndex"])
        + index_body,
    )
    component = _chunk(
        b"OBJT",
        struct.pack("<II", offsets["ExampleComponent"], 42),
    )
    body = string_chunk + type_chunk + compiled + index + component
    return struct.pack("<4sIII", b"BETH", len(body), 1, 15) + body


class CdbTests(unittest.TestCase):
    def test_load_minimal_database(self) -> None:
        database = MaterialDatabase.from_bytes(_minimal_database())
        self.assertEqual(database.material_id(r"Materials\Nothing.mat"), 0)

    def test_load_nested_creation_database_from_ba2(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            archive_path = Path(folder) / "creation.ba2"
            _single_file_ba2(
                archive_path,
                "materials/creations/example/materialsbeta.cdb",
                _minimal_database(),
            )
            database = load_material_database(archive_path)
            self.assertEqual(database.material_id(r"Materials\Nothing.mat"), 0)

    def test_layered_database_resolves_base_parent(self) -> None:
        parent_path = r"Materials\Base\Parent.mat"
        material_path = r"Materials\Creation\Child.mat"
        parent_resource = resource_id(parent_path)
        material_resource = resource_id(material_path)
        referenced_resource = ResourceId(3, 4, 5)
        unrelated_resource = ResourceId(6, 7, 8)
        empty_resource = ResourceId(0, 0, 0)

        base = MaterialDatabase()
        base._objects[10] = cdb._Object(
            parent_resource, 10, 0, empty_resource, True
        )
        base._objects[2] = cdb._Object(
            unrelated_resource, 2, 0, empty_resource, True
        )
        base._resource_to_db[parent_resource] = 10
        base._component_map[10].append((cdb._Component(10, 0, 0), 0))
        base._component_json.append(
            {"Type": "Example", "Data": {"BaseValue": "1"}}
        )

        creation = MaterialDatabase()
        creation._objects[2] = cdb._Object(
            material_resource, 2, 99, parent_resource, True
        )
        creation._objects[3] = cdb._Object(
            referenced_resource, 3, 99, parent_resource, True
        )
        creation._resource_to_db[material_resource] = 2
        creation._component_map[2].append((cdb._Component(2, 0, 0), 0))
        creation._component_json.append(
            {
                "Type": "Example",
                "Data": {
                    "CreationValue": "2",
                    "Reference": {
                        "Type": "BSMaterial::MaterialID",
                        "Data": {"ID": "3"},
                    },
                },
            }
        )
        creation._component_map[3].append((cdb._Component(3, 0, 0), 1))
        creation._component_json.append(
            {"Type": "Referenced", "Data": {"Value": "3"}}
        )

        layered = MaterialDatabase.layered(base, creation)
        parent_id = layered.material_id(parent_path)
        document = layered.export_document(
            material_path, {parent_id: parent_path}
        )
        self.assertEqual(document["Objects"][0]["Parent"], parent_path)
        self.assertEqual(
            document["Objects"][0]["Components"][0]["Data"],
            {
                "BaseValue": "1",
                "CreationValue": "2",
                "Reference": {
                    "Type": "BSMaterial::MaterialID",
                    "Data": {"ID": str(referenced_resource)},
                },
            },
        )
        self.assertEqual(document["Objects"][1]["ID"], str(referenced_resource))
        self.assertEqual(document["Objects"][1]["Parent"], parent_path)
        self.assertEqual(
            document["Objects"][1]["Components"],
            [
                {
                    "Type": "Example",
                    "Index": 0,
                    "Data": {"BaseValue": "1"},
                },
                {
                    "Type": "Referenced",
                    "Index": 0,
                    "Data": {"Value": "3"},
                },
            ],
        )

    def test_asset_ba2_uses_sibling_base_database(self) -> None:
        material = r"Materials\Example\Surface.mat"
        parent = cdb.ROOT_MATERIAL_PATHS[0]
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            base_archive = root / "Starfield - Materials.ba2"
            asset_archive = root / "Creation - Main.ba2"
            output = root / "output"
            _single_file_ba2(
                base_archive,
                "materials/materialsbeta.cdb",
                _exportable_database(material, parent),
            )
            _single_file_ba2(
                asset_archive,
                "meshes/example.nif",
                material.encode("utf-8") + b"\0",
            )

            discovered: list[str] = []
            written = export_from_inputs(
                asset_archive, output, [], discovered=discovered.extend
            )
            self.assertEqual(discovered, [material])
            self.assertEqual(
                written,
                [output / "Materials" / "Example" / "Surface.mat"],
            )

    def test_main_ba2_exports_case_insensitive_paired_textures(self) -> None:
        material = r"Materials\Example\Surface.mat"
        parent = cdb.ROOT_MATERIAL_PATHS[0]
        texture_payload = bytes(range(8))
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            base_archive = root / "Starfield - Materials.ba2"
            main_archive = root / "Creation - Main.ba2"
            texture_archive = root / "creation - TEXTURES.ba2"
            output = root / "output"
            _single_file_ba2(
                base_archive,
                "materials/materialsbeta.cdb",
                _exportable_database(material, parent),
            )
            _single_file_ba2(
                main_archive,
                "meshes/example.nif",
                material.encode("utf-8") + b"\0",
            )
            _single_texture_ba2(
                texture_archive,
                "textures/example.dds",
                texture_payload,
            )

            written = export_from_inputs(main_archive, output, [])

            material_output = output / "Materials" / "Example" / "Surface.mat"
            texture_output = output / "textures" / "example.dds"
            self.assertEqual(written, [material_output, texture_output])
            self.assertEqual(texture_output.read_bytes()[:4], b"DDS ")
            self.assertEqual(texture_output.read_bytes()[148:], texture_payload)

    def test_diff_fields_are_read_between_their_indices(self) -> None:
        database = MaterialDatabase()
        database._strings = b"Example\0Value\0"
        database._classes = {
            0: cdb._Class(0, 0, 0, [cdb._Field(8, cdb._UINT32, 0, 4)])
        }
        payload = (
            struct.pack("<I", 0)
            + struct.pack("<H", 0)
            + struct.pack("<I", 42)
            + struct.pack("<H", 0xFFFF)
        )
        database._input = cdb._Input(_chunk(b"DIFF", payload))
        self.assertEqual(
            database._read_next_object(),
            {"Type": "Example", "Data": {"Value": "42"}},
        )

    def test_database_to_material_export(self) -> None:
        material = r"materials\example\surface.mat"
        parent = cdb.ROOT_MATERIAL_PATHS[0]
        database = MaterialDatabase.from_bytes(
            _exportable_database(material, parent)
        )
        document = database.export_document(
            material, {database.material_id(parent): parent}
        )
        self.assertEqual(document["Version"], 1)
        self.assertEqual(document["Objects"][0]["Parent"], parent)
        self.assertEqual(
            document["Objects"][0]["Components"],
            [
                {
                    "Type": "ExampleComponent",
                    "Index": 0,
                    "Data": {"Value": "42"},
                }
            ],
        )
        with tempfile.TemporaryDirectory() as folder:
            written = database.write_materials([material], folder)
            self.assertEqual(
                written,
                [Path(folder) / "materials" / "example" / "surface.mat"],
            )
            self.assertTrue(written[0].is_file())


if __name__ == "__main__":
    unittest.main()
