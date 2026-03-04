"""Pydantic schemas for Agent and Testimonial endpoints."""

from datetime import date as date_type
from typing import List, Optional

from pydantic import BaseModel, Field


class AgentPublic(BaseModel):
    """Public agent profile — returned by consumer-facing API."""
    name: str
    slug: str
    title: Optional[str] = None
    bio: Optional[str] = None
    photo_url: Optional[str] = None
    phone: Optional[str] = None
    phone_display: Optional[str] = None
    email: Optional[str] = None
    calendar_url: Optional[str] = None
    npn: Optional[str] = None
    location: Optional[str] = None
    carrier_count: int = 47
    carriers: List[str] = []


class AgentUpdate(BaseModel):
    """Fields an admin can update on their own profile."""
    name: Optional[str] = None
    title: Optional[str] = None
    bio: Optional[str] = None
    photo_url: Optional[str] = None
    phone: Optional[str] = None
    phone_display: Optional[str] = None
    email: Optional[str] = None
    calendar_url: Optional[str] = None
    location: Optional[str] = None
    carrier_count: Optional[int] = None
    carriers_json: Optional[str] = None


class TestimonialPublic(BaseModel):
    """Public testimonial — visible on consumer site."""
    id: int
    client_name: str
    text: str
    rating: int = 5
    date: Optional[str] = None


class TestimonialCreate(BaseModel):
    """Create a new testimonial."""
    client_name: str = Field(..., max_length=128)
    text: str
    rating: int = Field(default=5, ge=1, le=5)
    date: Optional[date_type] = None


class TestimonialUpdate(BaseModel):
    """Update an existing testimonial."""
    client_name: Optional[str] = Field(None, max_length=128)
    text: Optional[str] = None
    rating: Optional[int] = Field(None, ge=1, le=5)
    date: Optional[date_type] = None
    is_published: Optional[bool] = None
    sort_order: Optional[int] = None
