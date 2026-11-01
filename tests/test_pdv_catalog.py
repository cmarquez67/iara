import os
import struct
from pathlib import Path

import pytest

from iara.config import PdvConfig, PdvFields
from iara.pdv.catalog import PdvCatalog, normalize, read_dbf

PRODUCTS_FILE = PdvConfig().products_file
FIELDS = [("ID", 10), ("CODIGO", 14), ("DESCRICAO", 60), ("PRECO", 12), ("STATUS", 1)]


def make_dbf(
    rows: list[tuple[str, str, str, float, str]],
    deleted: frozenset[int] = frozenset(),
    fields: list[tuple[str, int]] = FIELDS,
) -> bytes:
    """DBF mínimo com campos como texto e preço com 3 casas."""
    header_len = 32 + 32 * len(fields) + 1
    record_len = 1 + sum(n for _, n in fields)
    out = bytearray(struct.pack("<BBBBIHH", 0x30, 126, 10, 27, len(rows), header_len, record_len))
    out += bytes(32 - len(out))
    for i, (name, length) in enumerate(fields):
        desc = bytearray(32)
        desc[: len(name)] = name.encode("ascii")
        desc[11] = ord("N" if i == 3 else "C")
        desc[16] = length
        out += desc
    out += b"\r"
    for i, (pid, cod, des, preco, sts) in enumerate(rows):
        values = [pid, cod, des, f"{preco:.3f}".rjust(12), sts]
        rec = b"*" if i in deleted else b" "
        for (_, length), value in zip(fields, values, strict=True):
            rec += value.encode("cp1252").ljust(length)[:length]
        out += rec
    return bytes(out) + b"\x1a"


ROWS = [
    ("0000000001", "00000000C15,00", "CANECA 15,00", 15.0, "1"),
    ("0000000002", "00000000C15,90", "CANECA 15,90", 15.9, "1"),
    ("0000000003", "00000000C10,00", "CANECA 10,00", 10.0, "1"),
    ("0000000004", "00000000PL15,0", "PÃO PARA LANCHE 15,00", 15.0, "1"),
    ("0000000005", "00000000000002", "GARRAFA TERMIC20,00", 20.0, "1"),
    ("0000000006", "00000000C99,00", "CANECA 99,00", 99.0, ""),  # inativo
    ("0000000007", "00000000C50,00", "CANECA 50,00", 50.0, "1"),  # apagado
    ("0000000008", "00000000BR0,00", "BRINDE", 0.0, "1"),  # sem preço
]


@pytest.fixture
def dados(tmp_path: Path) -> Path:
    (tmp_path / PRODUCTS_FILE).write_bytes(make_dbf(ROWS, deleted=frozenset({6})))
    return tmp_path


def catalog_at(dados_dir: Path, exclude: tuple[str, ...] = ()) -> PdvCatalog:
    return PdvCatalog(PdvConfig(dados_dir=dados_dir, exclude=list(exclude)))


def test_read_dbf_skips_deleted_and_decodes_cp1252():
    recs = list(read_dbf(make_dbf(ROWS, deleted=frozenset({6}))))
    assert len(recs) == 7
    assert recs[3]["DESCRICAO"] == "PÃO PARA LANCHE 15,00"
    assert recs[0]["PRECO"] == "15.000"


def test_read_dbf_tolerates_file_shorter_than_header_says():
    data = make_dbf(ROWS)
    assert len(list(read_dbf(data[:-200]))) < len(ROWS)


def test_normalize_drops_accents_stopwords_and_splits_glued_price():
    assert normalize("Pão para lanche") == ["pao", "lanche"]
    assert normalize("GARRAFA TERMIC20,00") == ["garrafa", "termic", "20,00"]


def test_only_active_priced_products(dados: Path):
    descs = [p.descricao for p in catalog_at(dados).products()]
    assert "CANECA 99,00" not in descs
    assert "CANECA 50,00" not in descs
    assert "BRINDE" not in descs
    assert len(descs) == 5


def test_file_columns_and_active_status_come_from_config(tmp_path: Path):
    fields = [("X_ID", 10), ("X_COD", 14), ("X_DES", 60), ("X_VAL", 12), ("X_ATV", 1)]
    rows = [
        ("0000000001", "00000000C15,00", "CANECA 15,00", 15.0, "S"),
        ("0000000002", "00000000C20,00", "CANECA 20,00", 20.0, "1"),
    ]
    (tmp_path / "CADASTRO.DBF").write_bytes(make_dbf(rows, fields=fields))
    cfg = PdvConfig(
        dados_dir=tmp_path,
        products_file="CADASTRO.DBF",
        active_status="S",
        fields=PdvFields(codigo="X_COD", descricao="X_DES", preco="X_VAL", status="X_ATV"),
    )
    products = PdvCatalog(cfg).products()
    assert [(p.codigo, p.descricao, p.preco) for p in products] == [("C15,00", "CANECA 15,00", 15.0)]


@pytest.mark.parametrize(
    ("query", "expected"),
    [
        ("canecas", ["CANECA 10,00", "CANECA 15,00", "CANECA 15,90"]),
        ("caneca de 15", ["CANECA 15,00", "CANECA 15,90"]),
        ("caneca 15,90", ["CANECA 15,90"]),
        ("pao", ["PÃO PARA LANCHE 15,00"]),
        ("garrafa térmica", ["GARRAFA TERMIC20,00"]),
        ("sorvete", []),
        ("de", []),
    ],
)
def test_search(dados: Path, query: str, expected: list[str]):
    assert [p.descricao for p in catalog_at(dados).search(query)] == expected


def test_strips_leading_zeros_from_code(dados: Path):
    assert catalog_at(dados).search("caneca 10")[0].codigo == "C10,00"


def test_reloads_when_file_changes(dados: Path):
    catalog = catalog_at(dados)
    assert catalog.search("biscoito") == []
    path = dados / PRODUCTS_FILE
    path.write_bytes(make_dbf([("0000000009", "00000000BI5,00", "BISCOITO 5,00", 5.0, "1")]))
    stat = path.stat()
    os.utime(path, (stat.st_atime, stat.st_mtime + 10))
    assert [p.descricao for p in catalog.search("biscoito")] == ["BISCOITO 5,00"]


def test_missing_file_raises(tmp_path: Path):
    with pytest.raises(OSError):
        catalog_at(tmp_path).products()


def test_types_strip_trailing_price(dados: Path):
    assert catalog_at(dados).types() == ["CANECA", "GARRAFA TERMIC", "PÃO PARA LANCHE"]


def test_exclude_types_not_in_this_store(dados: Path):
    catalog = catalog_at(dados, exclude=("Caneca", "pão para lanche"))
    assert [p.descricao for p in catalog.products()] == ["GARRAFA TERMIC20,00"]
    assert catalog.search("caneca") == []
    assert catalog.types() == ["GARRAFA TERMIC"]
