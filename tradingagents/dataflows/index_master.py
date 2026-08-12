"""Versioned, provider-qualified index identity and routing.

The old index catalog was a name-to-code dictionary with a permissive
substring fallback.  This module is deliberately stricter: only an exact
normalized name/alias or an exact provider-qualified code can freeze an index
relationship.  A similar name produces candidates, never an automatic route.
"""

from __future__ import annotations

from datetime import date, datetime
from functools import lru_cache
import re
import unicodedata
from pathlib import Path
from typing import Iterable, Literal, Sequence

from pydantic import BaseModel, ConfigDict, Field, field_validator

from .config import load_project_versioned_config
from .models import MarketDataRequest, ReferenceInstrument, SeriesVariant


INDEX_CATALOG_FILENAME = "index_catalog_v2.yaml"
INDEX_CATALOG_VERSION = "index-catalog-v2"


class IndexCatalogRecord(BaseModel):
    model_config = ConfigDict(extra="forbid")

    instrument_id: str
    code: str
    name: str
    aliases: tuple[str, ...] = ()
    provider: str
    exchange_route: Literal["sh", "sz", "bj"]
    series_variant: Literal["price", "total_return", "net_total_return", "unknown"]
    currency: str = "CNY"
    timezone: str = "Asia/Shanghai"
    source: str = "curated"
    source_as_of: str

    @field_validator("code", "name", "provider", "instrument_id")
    @classmethod
    def non_empty(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("index catalog fields must not be empty")
        return value

    @field_validator("source_as_of", mode="before")
    @classmethod
    def normalize_source_date(cls, value: object) -> str:
        return str(value)

    @property
    def exchange(self) -> Literal["SSE", "SZSE", "BSE"]:
        return {"sh": "SSE", "sz": "SZSE", "bj": "BSE"}[self.exchange_route]


class IndexCatalog(BaseModel):
    model_config = ConfigDict(extra="forbid")

    version: str
    source: str = "curated"
    source_as_of: str
    records: tuple[IndexCatalogRecord, ...]

    @field_validator("source_as_of", mode="before")
    @classmethod
    def normalize_catalog_date(cls, value: object) -> str:
        return str(value)


def normalize_index_name(name: str | None) -> str:
    """Normalize only harmless presentation differences.

    This is not fuzzy matching.  It removes whitespace, Unicode presentation
    variants, and terminal ``指数``/``价格指数`` labels so a displayed formal
    name can match a catalog alias exactly.
    """

    if not name:
        return ""
    text = unicodedata.normalize("NFKC", str(name)).strip()
    text = re.sub(r"[\s\u3000]+", "", text)
    text = re.sub(r"[（(]价格[)）]", "", text)
    text = re.sub(r"(价格指数|指数)$", "", text)
    return text


def validate_index_catalog(records: Sequence[IndexCatalogRecord]) -> None:
    ids: set[str] = set()
    qualified: set[tuple[str, str, str]] = set()
    aliases: dict[str, str] = {}
    for record in records:
        if record.instrument_id in ids:
            raise ValueError(f"duplicate index instrument_id: {record.instrument_id}")
        ids.add(record.instrument_id)
        key = (record.provider, record.code, record.series_variant)
        if key in qualified:
            raise ValueError(f"duplicate provider/code/variant: {key}")
        qualified.add(key)
        for label in (record.name, *record.aliases):
            normalized = normalize_index_name(label)
            if not normalized:
                raise ValueError(f"empty index alias: {record.instrument_id}")
            previous = aliases.get(normalized)
            if previous is not None and previous != record.instrument_id:
                raise ValueError(
                    f"ambiguous index alias {label!r}: {previous} vs {record.instrument_id}"
                )
            aliases[normalized] = record.instrument_id


def _catalog_path(path: str | Path | None) -> str:
    if path is not None:
        return str(Path(path).resolve())
    return "<project>"


@lru_cache(maxsize=4)
def _load_index_catalog_cached(path_key: str) -> IndexCatalog:
    loaded = (
        load_project_versioned_config(INDEX_CATALOG_FILENAME)
        if path_key == "<project>"
        else __import__("tradingagents.dataflows.config", fromlist=["load_versioned_config"])
        .load_versioned_config(path_key)
    )
    records = tuple(IndexCatalogRecord.model_validate(item) for item in loaded.get("records", []))
    if not records:
        raise ValueError("index catalog must contain at least one record")
    catalog = IndexCatalog(
        version=str(loaded["version"]),
        source=str(loaded.get("source", "curated")),
        source_as_of=str(loaded.get("source_as_of", "")),
        records=records,
    )
    validate_index_catalog(catalog.records)
    return catalog


def load_index_catalog(path: str | Path | None = None) -> IndexCatalog:
    return _load_index_catalog_cached(_catalog_path(path))


def clear_index_catalog_cache() -> None:
    _load_index_catalog_cached.cache_clear()


def _record_by_code(
    code: str,
    provider: str | None = None,
    series_variant: str | None = None,
    *,
    catalog: IndexCatalog | None = None,
) -> list[IndexCatalogRecord]:
    normalized_code = str(code).strip()
    return [
        record
        for record in (catalog or load_index_catalog()).records
        if record.code == normalized_code
        and (provider is None or record.provider.casefold() == provider.strip().casefold())
        and (series_variant is None or record.series_variant == series_variant)
    ]


def lookup_index_by_code(
    code: str,
    provider: str | None = None,
    series_variant: str | None = None,
) -> IndexCatalogRecord | None:
    matches = _record_by_code(code, provider, series_variant)
    return matches[0] if len(matches) == 1 else None


def match_index_name(
    name: str | None,
    provider: str | None = None,
) -> list[IndexCatalogRecord]:
    normalized = normalize_index_name(name)
    if not normalized:
        return []
    matches: list[IndexCatalogRecord] = []
    for record in load_index_catalog().records:
        labels = {normalize_index_name(record.name), *(normalize_index_name(a) for a in record.aliases)}
        if normalized in labels and (
            provider is None or record.provider.casefold() == provider.strip().casefold()
        ):
            matches.append(record)
    return matches


def record_to_reference(
    record: IndexCatalogRecord,
    *,
    role: Literal["tracking_index", "benchmark"] = "tracking_index",
    status: Literal["verified", "user_supplied"] = "verified",
    source: str | None = None,
    verified_at: str | None = None,
) -> ReferenceInstrument:
    return ReferenceInstrument(
        role=role,
        code=record.code,
        name=record.name,
        provider=record.provider,
        series_variant=record.series_variant,
        source=source or record.source,
        status=status,
        verified_at=verified_at or record.source_as_of,
        instrument_id=record.instrument_id,
    )


def resolve_index_reference(
    *,
    name: str | None = None,
    code: str | None = None,
    provider: str | None = None,
    series_variant: str | None = None,
    role: Literal["tracking_index", "benchmark"] = "tracking_index",
    user_supplied: bool = False,
    verified_at: str | None = None,
) -> ReferenceInstrument:
    """Resolve a reference without fuzzy name matching.

    A user-supplied code is retained as such even when it is outside the
    curated directory.  Its variant remains ``unknown`` until a source-level
    validation proves otherwise.
    """

    if code:
        matches = _record_by_code(code, provider, series_variant)
        if len(matches) == 1:
            return record_to_reference(
                matches[0], role=role,
                status="user_supplied" if user_supplied else "verified",
                source="user" if user_supplied else matches[0].source,
                verified_at=verified_at,
            )
        if user_supplied:
            normalized_provider = (provider or "").strip()
            return ReferenceInstrument(
                role=role,
                code=str(code).strip(),
                name=(name or "").strip(),
                provider=normalized_provider,
                series_variant=series_variant or "unknown",
                source="user",
                status="user_supplied",
                verified_at=verified_at or date.today().isoformat(),
                instrument_id=(
                    f"{normalized_provider}:{str(code).strip()}:{series_variant or 'unknown'}"
                    if normalized_provider
                    else None
                ),
            )
        return ReferenceInstrument(
            role=role,
            code=str(code).strip(),
            name=(name or "").strip(),
            provider=(provider or "").strip(),
            series_variant=series_variant or "unknown",
            source="unverified",
            status="ambiguous" if len(matches) > 1 else "missing",
            verified_at=verified_at or "",
        )

    matches = match_index_name(name, provider)
    if len(matches) == 1:
        return record_to_reference(matches[0], role=role, verified_at=verified_at)
    if len(matches) > 1:
        return ReferenceInstrument(
            role=role,
            name=(name or "").strip(),
            provider=(provider or "").strip(),
            source="index_catalog_v2",
            status="ambiguous",
            verified_at=verified_at or "",
        )
    return ReferenceInstrument(
        role=role,
        name=(name or "").strip(),
        provider=(provider or "").strip(),
        source="index_catalog_v2",
        status="missing",
        verified_at=verified_at or "",
    )


def make_index_market_data_request(
    reference: ReferenceInstrument | IndexCatalogRecord,
    *,
    start_date: date,
    end_date: date,
    as_of: datetime,
    adjustment: Literal["raw", "forward", "backward"] = "raw",
) -> MarketDataRequest:
    """Build a structured index request only for a catalog-routable identity."""

    record = reference if isinstance(reference, IndexCatalogRecord) else lookup_index_by_code(
        reference.code, reference.provider, reference.series_variant
    )
    if record is None:
        raise ValueError("index request requires a catalog-routable provider/code/variant")
    return MarketDataRequest(
        symbol=record.code,
        exchange=record.exchange,
        instrument_type="index",
        start_date=start_date,
        end_date=end_date,
        frequency="1d",
        adjustment=adjustment,
        as_of=as_of,
        series_variant=record.series_variant,
    )


class IndexMaster:
    """Small façade used by identity resolvers and UI/CLI integrations."""

    def __init__(self, catalog: IndexCatalog | None = None):
        self.catalog = catalog or load_index_catalog()

    def by_code(self, code: str, provider: str | None = None) -> IndexCatalogRecord | None:
        matches = _record_by_code(code, provider, catalog=self.catalog)
        return matches[0] if len(matches) == 1 else None

    def by_name(self, name: str, provider: str | None = None) -> list[IndexCatalogRecord]:
        normalized = normalize_index_name(name)
        return [
            record
            for record in self.catalog.records
            if normalized in {
                normalize_index_name(record.name),
                *(normalize_index_name(alias) for alias in record.aliases),
            }
            and (provider is None or record.provider.casefold() == provider.casefold())
        ]

    def validate(self) -> None:
        validate_index_catalog(self.catalog.records)
