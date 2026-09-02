"""Unified model registry spanning the parametric and short-rate families."""

from __future__ import annotations

from typing import Dict, List, Optional, Type, Union

from .model import MODEL_REGISTRY, NelsonSiegelModel, make_model
from .short_rate import SHORT_RATE_REGISTRY, ShortRateModel

AnyCurveModel = Union[NelsonSiegelModel, ShortRateModel]


def all_model_classes() -> Dict[str, Type[AnyCurveModel]]:
    """Every registered curve model class keyed by id (parametric first)."""
    out: Dict[str, Type[AnyCurveModel]] = dict(MODEL_REGISTRY)
    out.update(SHORT_RATE_REGISTRY)
    return out


def get_any_model_class(model_id: Optional[str]) -> Type[AnyCurveModel]:
    """Look up a model class from either family (case-insensitive)."""
    key = (model_id or NelsonSiegelModel.model_id).lower().replace("_", "-")
    classes = all_model_classes()
    try:
        return classes[key]
    except KeyError:
        raise ValueError(f"Unknown model '{model_id}'. Available: {', '.join(sorted(classes))}") from None


def make_any_model(model_id: Optional[str] = None, bond_type: Optional[str] = None) -> AnyCurveModel:
    """Instantiate a model from either family, applying bond-type presets for parametric ones."""
    cls = get_any_model_class(model_id)
    if cls.model_id in MODEL_REGISTRY:
        return make_model(cls.model_id, bond_type)
    return cls()


def list_all_models() -> List[Dict[str, object]]:
    """Descriptions of every registered model (see each class's ``describe``)."""
    return [cls.describe() for cls in all_model_classes().values()]


__all__ = ["AnyCurveModel", "all_model_classes", "get_any_model_class", "list_all_models", "make_any_model"]
