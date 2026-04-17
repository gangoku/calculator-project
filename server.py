from __future__ import annotations

import os
from contextlib import asynccontextmanager
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Dict, List, Literal, Optional

import uvicorn
from fastapi import FastAPI
from pydantic import BaseModel, Field

try:
    from pypdf import PdfReader
except ImportError as exc:  # pragma: no cover
    raise RuntimeError(
        "pypdf is required. Install it with: pip install pypdf"
    ) from exc

try:
    from mcp.server.fastmcp import FastMCP
    from mcp.server.transport_security import TransportSecuritySettings
except ImportError as exc:  # pragma: no cover
    raise RuntimeError(
        "MCP SDK is required. Install the MCP Python SDK first."
    ) from exc


# -----------------------------------------------------------------------------
# Configuration
# -----------------------------------------------------------------------------

ComplianceType = Literal[
    "personal_information_protection",
    "monopoly_regulation_and_fair_trade",
    "unfair_competition_and_trade_secret_protection",
    "improper_solicitation_and_receiving_money",
    "information_network_and_information_protection",
]


@dataclass(frozen=True)
class Settings:
    compliance_dir: Path = Path(os.getenv("COMPLIANCE_DIR", "./compliance")).resolve()
    max_return_chars: int = int(os.getenv("MAX_RETURN_CHARS", "30000"))
    max_preview_chars: int = int(os.getenv("MAX_PREVIEW_CHARS", "3000"))
    host: str = os.getenv("MCP_HOST", "127.0.0.1")
    port: int = int(os.getenv("MCP_PORT", "8000"))


SETTINGS = Settings()


# Map each compliance type to a PDF file name in /compliance.
# You can rename the right-hand values to match your actual filenames.
COMPLIANCE_FILE_MAP: Dict[ComplianceType, str] = {
    "personal_information_protection": "개인정보 보호법 시행령(대통령령)(제35780호)(20251002).pdf",
    "monopoly_regulation_and_fair_trade": "독점규제 및 공정거래에 관한 법률 시행령(대통령령)(제36220호)(20260324).pdf",
    "unfair_competition_and_trade_secret_protection": "부정경쟁방지 및 영업비밀보호에 관한 법률 시행령(대통령령)(제36220호)(20260324).pdf",
    "improper_solicitation_and_receiving_money": "부정청탁 및 금품등 수수의 금지에 관한 법률 시행령(대통령령)(제35974호)(20251230).pdf",
    "information_network_and_information_protection": "정보통신망 이용촉진 및 정보보호 등에 관한 법률 시행령(대통령령)(제36220호)(20260324).pdf",
}


# -----------------------------------------------------------------------------
# Schemas
# -----------------------------------------------------------------------------

class ComplianceDocumentMetadata(BaseModel):
    compliance_type: ComplianceType
    file_name: str
    file_path: str
    exists: bool


class ComplianceDocumentResponse(BaseModel):
    compliance_type: ComplianceType
    file_name: str
    file_path: str
    page_count: int
    extracted_text: str
    truncated: bool
    preview: str


class SearchComplianceRequest(BaseModel):
    query: str = Field(..., min_length=1, description="Keyword or sentence to search")
    compliance_types: Optional[List[ComplianceType]] = Field(
        default=None,
        description="Optional subset of compliance document categories to search",
    )
    max_results: int = Field(default=5, ge=1, le=20)
    snippet_chars: int = Field(default=500, ge=100, le=2000)


class SearchComplianceResult(BaseModel):
    compliance_type: ComplianceType
    file_name: str
    file_path: str
    score: int
    snippet: str


class SearchComplianceResponse(BaseModel):
    query: str
    results: List[SearchComplianceResult]


# -----------------------------------------------------------------------------
# Utility functions
# -----------------------------------------------------------------------------


def normalize_text(text: str) -> str:
    lines = [line.strip() for line in text.splitlines()]
    lines = [line for line in lines if line]
    return "\n".join(lines)


@lru_cache(maxsize=32)
def read_pdf_text(file_path: str) -> tuple[str, int]:
    path = Path(file_path)
    if not path.exists():
        raise FileNotFoundError(f"PDF file not found: {path}")

    reader = PdfReader(str(path))
    page_texts: List[str] = []

    for page in reader.pages:
        text = page.extract_text() or ""
        page_texts.append(text)

    full_text = normalize_text("\n\n".join(page_texts))
    return full_text, len(reader.pages)



def get_document_path(compliance_type: ComplianceType) -> Path:
    filename = COMPLIANCE_FILE_MAP[compliance_type]
    return SETTINGS.compliance_dir / filename



def make_preview(text: str, max_chars: int) -> str:
    if len(text) <= max_chars:
        return text
    return text[:max_chars].rstrip() + "..."



def truncate_text(text: str, max_chars: int) -> tuple[str, bool]:
    if len(text) <= max_chars:
        return text, False
    return text[:max_chars].rstrip() + "...", True



def build_snippet(text: str, query: str, snippet_chars: int) -> str:
    lowered_text = text.lower()
    lowered_query = query.lower()
    idx = lowered_text.find(lowered_query)

    if idx == -1:
        return make_preview(text, snippet_chars)

    start = max(0, idx - snippet_chars // 2)
    end = min(len(text), idx + len(query) + snippet_chars // 2)
    snippet = text[start:end].strip()

    if start > 0:
        snippet = "..." + snippet
    if end < len(text):
        snippet = snippet + "..."
    return snippet


# -----------------------------------------------------------------------------
# Repository / service layer
# -----------------------------------------------------------------------------

class ComplianceRepository:
    def list_documents(self) -> List[ComplianceDocumentMetadata]:
        items: List[ComplianceDocumentMetadata] = []
        for compliance_type, file_name in COMPLIANCE_FILE_MAP.items():
            path = get_document_path(compliance_type)
            items.append(
                ComplianceDocumentMetadata(
                    compliance_type=compliance_type,
                    file_name=file_name,
                    file_path=str(path),
                    exists=path.exists(),
                )
            )
        return items

    def get_document(self, compliance_type: ComplianceType) -> ComplianceDocumentResponse:
        path = get_document_path(compliance_type)
        full_text, page_count = read_pdf_text(str(path))
        extracted_text, truncated = truncate_text(full_text, SETTINGS.max_return_chars)

        return ComplianceDocumentResponse(
            compliance_type=compliance_type,
            file_name=path.name,
            file_path=str(path),
            page_count=page_count,
            extracted_text=extracted_text,
            truncated=truncated,
            preview=make_preview(full_text, SETTINGS.max_preview_chars),
        )

    def search_documents(
        self,
        query: str,
        compliance_types: Optional[List[ComplianceType]] = None,
        max_results: int = 5,
        snippet_chars: int = 500,
    ) -> SearchComplianceResponse:
        target_types = compliance_types or list(COMPLIANCE_FILE_MAP.keys())
        results: List[SearchComplianceResult] = []
        lowered_query = query.lower()

        for compliance_type in target_types:
            path = get_document_path(compliance_type)
            if not path.exists():
                continue

            full_text, _ = read_pdf_text(str(path))
            score = full_text.lower().count(lowered_query)
            if score <= 0:
                continue

            results.append(
                SearchComplianceResult(
                    compliance_type=compliance_type,
                    file_name=path.name,
                    file_path=str(path),
                    score=score,
                    snippet=build_snippet(full_text, query, snippet_chars),
                )
            )

        results.sort(key=lambda x: x.score, reverse=True)
        return SearchComplianceResponse(query=query, results=results[:max_results])


repository = ComplianceRepository()


# -----------------------------------------------------------------------------
# MCP server
# -----------------------------------------------------------------------------
DOMAIN = "calculator-project-ucyb.onrender.com"
LOCAL_ALLOWED_HOSTS = [
    "localhost",
    "localhost:*",
    "127.0.0.1",
    "127.0.0.1:*",
]
LOCAL_ALLOWED_ORIGINS = [
    "http://localhost:8000",
    "http://127.0.0.1:8000",
]

mcp = FastMCP(
    "compliance-pdf-mcp",
    host=SETTINGS.host,
    port=SETTINGS.port,
    streamable_http_path="/",
    transport_security=TransportSecuritySettings(
        enable_dns_rebinding_protection=True,
        allowed_hosts=[
            *LOCAL_ALLOWED_HOSTS,
            DOMAIN,
            f"{DOMAIN}:*",
        ],
        allowed_origins=[
            *LOCAL_ALLOWED_ORIGINS,
            f"https://{DOMAIN}",
        ],
    ),
    json_response=True,
    stateless_http=True,
)


@mcp.tool()
def list_compliance_documents() -> List[dict]:
    """
    List the 5 compliance PDF documents configured in the /compliance folder.
    Use this when ChatGPT needs to know which compliance documents are available.
    """
    return [item.model_dump() for item in repository.list_documents()]


@mcp.tool()
def get_compliance_document(compliance_type: ComplianceType) -> dict:
    """
    Read one compliance PDF document from the /compliance folder and return its extracted text.

    Args:
        compliance_type: One of the 5 predefined compliance categories.

    Returns:
        Metadata, page count, preview, and extracted text from the PDF.
        If the document is too long, extracted_text may be truncated.
    """
    document = repository.get_document(compliance_type)
    return document.model_dump()


@mcp.tool()
def search_compliance_documents(
    query: str,
    compliance_types: Optional[List[ComplianceType]] = None,
    max_results: int = 5,
    snippet_chars: int = 500,
) -> dict:
    """
    Search across one or more compliance PDF documents and return ranked matches.

    This is useful when ChatGPT has inferred which regulation topics might be relevant
    and wants to quickly locate matching document text before requesting a full document.

    Args:
        query: Keyword, phrase, or short sentence to search.
        compliance_types: Optional subset of compliance categories to search.
        max_results: Maximum number of matched documents to return.
        snippet_chars: Approximate snippet length for each result.
    """
    request = SearchComplianceRequest(
        query=query,
        compliance_types=compliance_types,
        max_results=max_results,
        snippet_chars=snippet_chars,
    )
    response = repository.search_documents(
        query=request.query,
        compliance_types=request.compliance_types,
        max_results=request.max_results,
        snippet_chars=request.snippet_chars,
    )
    return response.model_dump()


streamable_http_app = mcp.streamable_http_app()


@asynccontextmanager
async def lifespan(app: FastAPI):
    async with mcp.session_manager.run():
        yield


app = FastAPI(lifespan=lifespan)


@app.get("/health")
def health() -> dict[str, bool]:
    return {"ok": True}


app.mount("/mcp", streamable_http_app)


if __name__ == "__main__":
    uvicorn.run(app, host=SETTINGS.host, port=SETTINGS.port)
