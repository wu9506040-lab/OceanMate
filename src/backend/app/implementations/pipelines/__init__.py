"""Pipelines - 编排层（clean → chunk → embed → store）。"""

from app.implementations.pipelines.ingestion_pipeline import IngestionPipeline


__all__ = ["IngestionPipeline"]