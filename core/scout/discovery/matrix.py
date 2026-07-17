"""Deterministic campaign matrix with bounded combinatorics (Phase 8.4).

A matrix cell is one bounded combination of
country x language x industry x business_type x commercial_flow x provider.
The matrix size is computed BEFORE execution and fails closed when it exceeds the configured
hard maximum, unless the caller requests a deterministic sample. This prevents combinatorial
explosion and bounds the planned number of provider calls.
"""
from __future__ import annotations

import itertools
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from core.scout.discovery.config import DiscoveryCampaignConfig
from core.scout.discovery.providers import DiscoveryError

_ANY = "*"


@dataclass
class MatrixPlan:
    cells: List[Dict[str, str]] = field(default_factory=list)
    full_size: int = 0
    planned_provider_calls: int = 0
    sampled: bool = False
    dimensions: Dict[str, int] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "full_size": self.full_size,
            "planned_provider_calls": self.planned_provider_calls,
            "sampled": self.sampled,
            "dimensions": dict(self.dimensions),
            "cells": list(self.cells),
        }


def _axis(values: List[str]) -> List[str]:
    cleaned = [v for v in (s.strip() for s in values) if v]
    return cleaned or [_ANY]


def build_matrix(config: DiscoveryCampaignConfig, provider_ids: List[str],
                 sample: Optional[int] = None) -> MatrixPlan:
    """Build the (optionally sampled) campaign matrix, failing closed on overflow.

    `sample` deterministically narrows an over-limit matrix to the first `sample` cells (in a
    stable sorted order). Without it, an over-limit matrix raises so the operator must narrow.
    """
    if not provider_ids:
        raise DiscoveryError("campaign matrix requires at least one provider")
    countries = _axis(config.countries)
    languages = _axis(config.languages)
    industries = _axis(config.industries)
    business_types = _axis(config.business_types)
    flows = _axis(config.required_flows)
    providers = sorted(set(provider_ids))

    dims = {
        "country": len(countries), "language": len(languages), "industry": len(industries),
        "business_type": len(business_types), "flow": len(flows), "provider": len(providers),
    }
    full_size = 1
    for n in dims.values():
        full_size *= n

    all_cells = [
        {"country": c, "language": lang, "industry": ind, "business_type": bt,
         "flow": fl, "provider_id": pid}
        for c, lang, ind, bt, fl, pid in itertools.product(
            countries, languages, industries, business_types, flows, providers)
    ]
    all_cells.sort(key=lambda d: tuple(d[k] for k in
                    ("provider_id", "country", "language", "industry", "business_type", "flow")))

    sampled = False
    cells = all_cells
    if full_size > config.matrix_hard_max:
        if sample is None:
            raise DiscoveryError(
                f"campaign matrix size {full_size} exceeds matrix_hard_max "
                f"{config.matrix_hard_max}; narrow the criteria or pass an explicit sample size")
        if sample < 1:
            raise DiscoveryError("sample size must be positive")
        cells = all_cells[:sample]
        sampled = True

    if len(cells) > config.max_provider_calls:
        # Enforce the provider-call ceiling deterministically (fail closed on the excess).
        if sample is None:
            raise DiscoveryError(
                f"planned provider calls {len(cells)} exceed max_provider_calls "
                f"{config.max_provider_calls}; narrow the matrix or sample")
        cells = cells[: config.max_provider_calls]
        sampled = True

    return MatrixPlan(cells=cells, full_size=full_size, planned_provider_calls=len(cells),
                      sampled=sampled, dimensions=dims)
