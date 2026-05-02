from __future__ import annotations
from dataclasses import dataclass
from typing import Dict, List, Literal, Optional


PathName = Literal['ingestion', 'warehouse', 'probe']
ErrorCode = Literal[
    'auth_failed',
    'host_unreachable',
    'response_too_large',
    'malformed_json',
    'no_connectors_connected',
    'no_warehouse_hint',
    'unknown',
]


@dataclass(frozen=True)
class ColumnMetadata:
    name: str
    data_type: str
    is_nullable: bool


@dataclass(frozen=True)
class DatasetCandidate:
    source: PathName
    endpoint: Optional[str]
    json_root: Optional[str]
    timestamp_column: Optional[str]
    expected_schema: List[ColumnMetadata]
    lands_in: Optional[str]
    confidence: float


@dataclass(frozen=True)
class DiscoveryError:
    code: ErrorCode
    message: str


@dataclass(frozen=True)
class DiscoveryResult:
    candidates_by_path: Dict[PathName, List[DatasetCandidate]]
    errors_by_path: Dict[PathName, Optional[DiscoveryError]]
