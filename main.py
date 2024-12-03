from fastapi import FastAPI, HTTPException, Depends
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import BaseModel, validator
from reference_builder import ReferenceBuilder
import os
from dotenv import load_dotenv
from typing import List
import uvicorn


load_dotenv()
app = FastAPI()
port = int(os.getenv("PORT", 8000))
API_TOKEN = os.getenv("API_TOKEN", "default-token")
security = HTTPBearer()

builder = ReferenceBuilder()

class ParagraphRequest(BaseModel):
    text: str

    @validator('text')
    def validate_paragraph(cls, v):
        if '\n' in v:
            raise ValueError('Text must be a single paragraph (no line breaks)')
        if len(v) > 3000:
            raise ValueError('Text must not exceed 1500 characters')
        if len(v.strip()) == 0:
            raise ValueError('Text cannot be empty')
        return v.strip()

class CitationResponse(BaseModel):
    cited_text: str
    bibtex_entries: List[str]

async def verify_token(credentials: HTTPAuthorizationCredentials = Depends(security)):
    if credentials.credentials != API_TOKEN:
        raise HTTPException(
            status_code=401,
            detail="Invalid authentication token"
        )
    return credentials.credentials
    return credentials.credentials

@app.get("/")
def read_root():
    return {
        "description": "Academic Citation API",
        "endpoints": {
            "/citations": "POST - Get citations for a text paragraph"
        }
    }

@app.get("/citations")
def read_root():
    return {
        "description": "POST - Get citations for a text paragraph"
    }


@app.post("/citations/", response_model=CitationResponse)
async def get_citations(
    request: ParagraphRequest,
    token: str = Depends(verify_token)
):
    try:
        suggested_papers = builder.get_suggested_papers(request.text)
        validated_papers = builder.validate_by_arxiv_url(suggested_papers)
        final_papers = builder.expand_by_key_authors(validated_papers, request.text)
        bibtex_entries = builder.generate_bibtex(final_papers)
        cited_text = builder.suggest_citations(request.text, final_papers, bibtex_entries)
        
        return CitationResponse(
            cited_text=cited_text,
            bibtex_entries=[entry for _, entry in bibtex_entries]
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
    
if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=port)