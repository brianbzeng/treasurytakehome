"""Validated application, extraction, and review result models."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator


class ApplicationData(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    application_id: str | None = None
    brand_name: str = Field(min_length=1, max_length=200)
    class_type: str = Field(min_length=1, max_length=300)
    abv: float = Field(gt=0, le=100)
    proof: float | None = Field(default=None, gt=0, le=200)
    net_contents: str = Field(min_length=1, max_length=100)
    producer_name_address: str = Field(min_length=1, max_length=500)
    country_of_origin: str | None = Field(default=None, max_length=200)

    @field_validator("application_id", "country_of_origin", mode="before")
    @classmethod
    def empty_string_to_none(cls, value: object) -> object:
        return None if value == "" else value


class ExtractedField(BaseModel):
    model_config = ConfigDict(extra="ignore")

    value: str | None = None
    evidence: str | None = None
    expected_value_found: bool | None = None
    confidence: float = Field(default=0, ge=0, le=1)


class WarningObservation(BaseModel):
    model_config = ConfigDict(extra="ignore")

    verbatim_text: str | None = None
    heading_text: str | None = None
    heading_bold: bool | None = None
    legible: bool | None = None
    evidence: str | None = None
    confidence: float = Field(default=0, ge=0, le=1)


class LabelExtraction(BaseModel):
    model_config = ConfigDict(extra="ignore")

    brand_name: ExtractedField = Field(default_factory=ExtractedField)
    class_type: ExtractedField = Field(default_factory=ExtractedField)
    alcohol_content: ExtractedField = Field(default_factory=ExtractedField)
    net_contents: ExtractedField = Field(default_factory=ExtractedField)
    producer_name_address: ExtractedField = Field(default_factory=ExtractedField)
    country_of_origin: ExtractedField = Field(default_factory=ExtractedField)
    government_warning: WarningObservation = Field(
        default_factory=WarningObservation
    )
    raw_text: str | None = None
    notes: list[str] = Field(default_factory=list)


CheckStatus = Literal["match", "review", "mismatch"]
OverallStatus = Literal["match", "attention", "unable"]


class ReviewCheck(BaseModel):
    key: str
    label: str
    status: CheckStatus
    expected: str | None
    observed: str | None
    explanation: str
    evidence: str | None = None
    confidence: float | None = Field(default=None, ge=0, le=1)
    guidance_title: str | None = None
    guidance_url: str | None = None
    guidance_summary: str | None = None


class ReviewResult(BaseModel):
    application_id: str | None
    overall_status: OverallStatus
    summary: str
    checks: list[ReviewCheck]
    notes: list[str] = Field(default_factory=list)
    processing_ms: int | None = None
    provider: str
