"""Load and execute the event-specific models stored by Finespresso."""
from __future__ import annotations

import io
import json
import logging
import pickle
import re
import unicodedata
import os
from pathlib import Path
from dataclasses import dataclass
from typing import Any

import numpy as np
import pandas as pd
from sqlalchemy import text

from engine.news_pipeline.events import normalize_event
from engine.news_pipeline.validation import finite_move

try:
    import joblib
except ImportError:
    joblib = None

log = logging.getLogger(__name__)


class MissingEventModel(RuntimeError):
    """A required event model is unavailable; the article must be retried."""


@dataclass(frozen=True)
class EventModels:
    event: str
    classifier: dict[str, Any]
    regressor: dict[str, Any]


class ModelRegistry:
    def __init__(self, engine):
        self.engine = engine
        self._cache: dict[tuple[str, str], dict[str, Any]] = {}
        self._available_events: tuple[str, ...] | None = None

    def available_events(self) -> tuple[str, ...]:
        """Return only events having usable classifier and regressor records."""
        if self._available_events is None:
            with self.engine.connect() as conn:
                rows = conn.execute(text("""
                    SELECT DISTINCT c.event_type
                    FROM public.model_tracking c
                    WHERE c.model_type='classifier' AND c.accuracy >= 0.5
                      AND (c.model_id LIKE '%actual_sid%' OR c.model_id LIKE '%actual_side%')
                      AND EXISTS (
                        SELECT 1 FROM public.model_tracking r
                        WHERE r.event_type=c.event_type AND r.model_type='regressor'
                          AND (r.model_id LIKE '%price_change_percentage%'
                               OR r.model_id LIKE '%price_chan%')
                          AND r.model_id NOT LIKE '%nextday%'
                      )
                    ORDER BY c.event_type
                """)).scalars().all()
            self._available_events = tuple(str(row) for row in rows if row)
        if not self._available_events:
            raise MissingEventModel("no events have both classifier and regressor models")
        return self._available_events

    def _model_id(self, event: str, kind: str) -> str:
        accuracy = "AND accuracy >= 0.5" if kind == "classifier" else ""
        score = "accuracy DESC" if kind == "classifier" else "r2_score DESC"
        target = ("AND (model_id LIKE '%actual_sid%' OR model_id LIKE '%actual_side%')"
                  if kind == "classifier" else
                  "AND (model_id LIKE '%price_change_percentage%' OR model_id LIKE '%price_chan%') AND model_id NOT LIKE '%nextday%'")
        with self.engine.connect() as conn:
            value = conn.execute(text(f"""
                SELECT model_id FROM public.model_tracking
                WHERE model_type=:kind AND event_type=:event {accuracy} {target}
                ORDER BY {score} LIMIT 1
            """), {"kind": kind, "event": event}).scalar()
        if not value:
            raise MissingEventModel(f"missing {kind} model for event={event}")
        return str(value)

    @staticmethod
    def _load(blob: bytes | None) -> Any:
        if not blob:
            return None
        if joblib is not None:
            try:
                return joblib.load(io.BytesIO(blob))
            except Exception:
                pass
        try:
            return pickle.loads(blob)
        except Exception as exc:
            raise MissingEventModel("model artifact cannot be deserialized; install joblib/scikit-learn") from exc

    def load(self, event: str, kind: str) -> dict[str, Any]:
        event = normalize_event(event)
        key = (event, kind)
        if key in self._cache:
            return self._cache[key]
        model_id = self._model_id(event, kind)
        with self.engine.connect() as conn:
            row = conn.execute(text("""
                SELECT model_blob, scaler_blob, encoder_blob, title_tfidf_blob,
                       content_tfidf_blob, feature_columns
                FROM public.model_tracking WHERE model_id=:model_id
            """), {"model_id": model_id}).mappings().one_or_none()
        if not row:
            raise MissingEventModel(f"model metadata not found: {model_id}")
        components = {"model_id": model_id, "model": self._load(row["model_blob"]),
                      "scaler": self._load(row["scaler_blob"]),
                      "encoder": self._load(row["encoder_blob"]),
                      "title_tfidf": self._load(row["title_tfidf_blob"]),
                      "content_tfidf": self._load(row["content_tfidf_blob"]),
                      "feature_columns": row["feature_columns"] or []}
        if components["model"] is None or not (components["title_tfidf"] or components["content_tfidf"]):
            model_root = os.getenv("NEWS_MODEL_STORAGE_PATH")
            bundle_path = Path(model_root, f"{model_id}.joblib") if model_root else None
            if bundle_path and bundle_path.is_file() and joblib is not None:
                bundle = joblib.load(bundle_path)
                if isinstance(bundle, dict):
                    components.update(bundle)
            if components["model"] is None or not (components["title_tfidf"] or components["content_tfidf"]):
                raise MissingEventModel(f"incomplete {kind} artifact: {model_id}")
        self._cache[key] = components
        return components

    def for_event(self, event: str) -> EventModels:
        normalized = normalize_event(event)
        return EventModels(normalized, self.load(normalized, "classifier"), self.load(normalized, "regressor"))


def _normalize_text(value: Any) -> str:
    value = unicodedata.normalize("NFKD", str(value or ""))
    return re.sub(r"\s+", " ", "".join(c for c in value if unicodedata.category(c) != "Mn")).strip().lower()


def _features(row: dict[str, Any], component: dict[str, Any]) -> np.ndarray:
    row = _engineered(row)
    columns = component.get("feature_columns") or []
    if isinstance(columns, str):
        columns = json.loads(columns)
    base = []
    for name in columns:
        if str(name).startswith(("title_tfidf_", "content_tfidf_")):
            continue
        value = row.get(name, 0)
        if name in {"yf_ticker", "market_status", "event_standardized", "company", "publisher", "industry"}:
            value = hash(str(value or "")) % 1000
        try:
            base.append(float(value or 0))
        except (TypeError, ValueError):
            base.append(0.0)
    values = np.asarray(base)
    for key, source in (("title_tfidf", row.get("title_en") or row.get("title")),
                        ("content_tfidf", row.get("content_en") or row.get("content"))):
        vectorizer = component.get(key)
        if vectorizer:
            values = np.concatenate((values, vectorizer.transform([_normalize_text(source)]).toarray().ravel()))
    scaler = component.get("scaler")
    expected = getattr(scaler, "n_features_in_", len(values)) if scaler else len(values)
    values = np.pad(values[:expected], (0, max(0, expected - len(values))))
    return scaler.transform([values]) if scaler else np.asarray([values])


def _engineered(row: dict[str, Any]) -> dict[str, Any]:
    """Port deterministic feature preparation used during model training."""
    result = dict(row)
    title = str(row.get("title_en") or row.get("title") or "")
    content = str(row.get("content_en") or row.get("content") or "")
    joined = f"{title} {content}".strip().lower()
    words = joined.split()
    sentences = [value for value in re.split(r"[.!?]+", joined) if value.strip()]
    result.update({
        "title_length": len(title), "content_length": len(content),
        "title_word_count": len(title.split()), "content_word_count": len(content.split()),
        "avg_word_length": sum(map(len, words)) / len(words) if words else 0,
        "financial_keyword_count": sum(term in joined for term in ("earnings", "revenue", "profit", "loss", "growth", "guidance", "dividend")),
        "market_keyword_count": sum(term in joined for term in ("bull", "bear", "rally", "volatility", "investor", "analyst", "upgrade", "downgrade")),
        "urgency_keyword_count": sum(term in joined for term in ("urgent", "breaking", "critical", "significant", "unexpected")),
        "regulatory_keyword_count": sum(term in joined for term in ("sec", "fda", "approval", "regulation", "investigation", "lawsuit")),
        "size_keyword_count": sum(term in joined for term in ("billion", "million", "trillion", "massive", "large")),
        "exclamation_count": joined.count("!"), "question_count": joined.count("?"),
        "period_count": joined.count("."), "comma_count": joined.count(","),
        "has_numbers": int(bool(re.search(r"\d", joined))), "has_percentages": int("%" in joined),
        "has_quotes": int('"' in joined or "'" in joined),
        "avg_sentence_length": len(words) / len(sentences) if sentences else 0,
        "sentence_count": len(sentences),
    })
    try:
        stamp = pd.to_datetime(row.get("published_date"))
        result.update({"hour": stamp.hour, "day_of_week": stamp.dayofweek, "day_of_month": stamp.day,
                       "month": stamp.month, "quarter": stamp.quarter, "year": stamp.year,
                       "day_of_year": stamp.dayofyear, "week_of_year": stamp.isocalendar().week,
                       "is_market_hours": int(9 <= stamp.hour <= 16), "is_pre_market": int(4 <= stamp.hour < 9),
                       "is_after_hours": int(16 < stamp.hour <= 20), "is_weekend": int(stamp.dayofweek >= 5),
                       "is_month_end": int(stamp.day >= 28),
                       "is_quarter_end": int(stamp.month in (3, 6, 9, 12) and stamp.day >= 28),
                       "is_year_end": int(stamp.month == 12 and stamp.day >= 28),
                       "is_earnings_season": int(stamp.month in (1, 4, 7, 10) and stamp.day <= 15),
                       "is_high_volatility_period": int(stamp.month in (10, 11))})
    except Exception:
        pass
    return result


def predict(row: dict[str, Any], models: EventModels) -> dict[str, Any]:
    result = dict(row)
    result["event_standardized"] = models.event
    c, r = models.classifier, models.regressor
    encoded = c["model"].predict(_features(result, c))[0]
    result["predicted_side"] = str(c["encoder"].inverse_transform([encoded])[0] if c.get("encoder") else encoded).upper()
    result["predicted_move"] = finite_move(r["model"].predict(_features(result, r))[0])
    result["model_id_classifier"] = c["model_id"]
    result["model_id_regressor"] = r["model_id"]
    return result
