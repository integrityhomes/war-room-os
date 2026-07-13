"""XLeads export intake, safety review, and optional Ninja CRM sync.

This module stays separate from the lead-ranking engine so malformed exports or
CRM credentials cannot break Seller Lead Command.
"""
from __future__ import annotations

from dataclasses import dataclass
from io import BytesIO
import json
import re
from typing import Any, Iterable
from zipfile import BadZipFile, ZipFile