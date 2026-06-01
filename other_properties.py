"""Resolução de campos customizados do Ploomes (OtherProperties).

Na conta da Lar Plásticos há ~1173 campos customizados — muitos espelham o
Sankhya (Status do Cliente, Status Workflow, Nro. Nota, Previsão de Entrega...).
Cada um é identificado por um FieldKey (GUID, ex.: "order_92A1...") e o valor
fica numa de várias colunas (StringValue, IntegerValue, ObjectValueName...).

Este módulo:
  - carrega o mapa FieldKey -> Nome (cache em ploomes_fields.json, atualizável
    pela API via PloomesClient.refresh_fields);
  - extrai OtherProperties de um registro como {nome legível: valor}, já
    resolvendo picklists (usa ObjectValueName quando existe);
  - faz o caminho inverso (nome -> FieldKey) para montar OtherProperties ao
    criar cotações/pedidos.
"""
from __future__ import annotations
import json
from pathlib import Path
from typing import Any, Optional

from paths import app_dir, data_dir

_CACHE_FILE = data_dir() / "ploomes_fields.json"
_BUNDLE_FIELDS = app_dir() / "ploomes_fields.json"


class FieldCatalog:
    """Mapa bidirecional FieldKey <-> Nome do campo customizado."""

    def __init__(self) -> None:
        self._key_to_name: dict[str, str] = {}
        self._name_to_key: dict[str, str] = {}
        self._load_from_disk()

    def _load_from_disk(self) -> None:
        if not _CACHE_FILE.exists() and _BUNDLE_FIELDS.exists():
            try:
                import shutil
                shutil.copy2(_BUNDLE_FIELDS, _CACHE_FILE)
            except OSError:
                pass
        if _CACHE_FILE.exists():
            try:
                data = json.loads(_CACHE_FILE.read_text(encoding="utf-8"))
                self.replace(data)
            except (json.JSONDecodeError, OSError):
                pass

    def replace(self, key_to_name: dict[str, str]) -> None:
        self._key_to_name = dict(key_to_name)
        # nome -> key (último vence; nomes podem repetir entre entidades)
        self._name_to_key = {v: k for k, v in key_to_name.items()}

    def persist(self) -> None:
        try:
            _CACHE_FILE.write_text(
                json.dumps(self._key_to_name, ensure_ascii=False, indent=0),
                encoding="utf-8",
            )
        except OSError:
            pass

    def name(self, key: str) -> str:
        return self._key_to_name.get(key, key)

    def key(self, name: str) -> Optional[str]:
        return self._name_to_key.get(name)

    def __len__(self) -> int:
        return len(self._key_to_name)


# instância única compartilhada
catalog = FieldCatalog()


# Ordem de preferência ao ler o valor de um OtherProperty.
# ObjectValueName vem primeiro: em picklists (Status, CIF/FOB, etc.) é o texto
# legível; o IntegerValue guarda só o ID interno da opção.
_VALUE_COLUMNS = (
    "ObjectValueName", "StringValue", "DecimalValue",
    "DateTimeValue", "IntegerValue", "BoolValue",
)


def _value_of(op: dict) -> Any:
    for col in _VALUE_COLUMNS:
        v = op.get(col)
        if v not in (None, "", []):
            return v
    big = op.get("BigStringValue")
    # BigString costuma ser HTML de UI; só devolve se for texto curto/limpo
    if big and "<" not in str(big)[:40]:
        return big
    return None


def extract(item: dict) -> dict[str, Any]:
    """OtherProperties de um registro -> {nome do campo: valor legível}."""
    out: dict[str, Any] = {}
    for op in item.get("OtherProperties") or []:
        name = catalog.name(op.get("FieldKey", ""))
        val = _value_of(op)
        if val is not None:
            out[name] = val
    return out


def get(props: dict[str, Any], *names: str, default: Any = None) -> Any:
    """Primeiro nome que existir no dict extraído (tolera variações de rótulo)."""
    for n in names:
        if n in props and props[n] not in (None, ""):
            return props[n]
    return default


# ---------------------------------------------------------------------------
# Caminho inverso — montar OtherProperties para CRIAR documento.
# ---------------------------------------------------------------------------
def build_other_property(field_name: str, value: Any) -> Optional[dict]:
    """Monta um item de OtherProperties a partir do nome do campo + valor.

    Escolhe a coluna pelo tipo de Python. Para picklists (precisa do ID da
    opção) passe o ID inteiro — vai em IntegerValue/ObjectValueId.
    """
    key = catalog.key(field_name)
    if key is None:
        return None
    item: dict[str, Any] = {"FieldKey": key}
    if isinstance(value, bool):
        item["BoolValue"] = value
    elif isinstance(value, int):
        item["IntegerValue"] = value
    elif isinstance(value, float):
        item["DecimalValue"] = value
    else:
        item["StringValue"] = str(value)
    return item
