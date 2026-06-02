"""API schemas — Pydantic models for request/response shapes (no table=True).

These define the public API contract and are kept separate from the SQLModel
table classes in aiinfra/db/models.py so the wire surface and the database
schema can evolve independently.
"""
