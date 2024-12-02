#!/usr/bin/env python3

import sys
from pathlib import Path
from reference_builder import ReferenceBuilder

def process_paragraphs(file_path: str):
    """Process each paragraph in the file through the reference builder."""
    with open(file_path) as f:
        content = f.read()
    
    paragraphs = [p.strip() for p in content.split('\n\n') if p.strip()]
    builder = ReferenceBuilder()
    
    output_file = Path(file_path).with_suffix('.citations')
    with open(output_file, 'a') as out:
        for para in paragraphs:
            if not para:
                continue
            
            # Get suggestions and process
            suggested = builder.get_suggested_papers(para)
            validated = builder.validate_on_arxiv(suggested)
            if validated:
                final_papers = builder.expand_by_key_authors(validated, para)
                if final_papers:
                    bibtex_entries = builder.generate_bibtex(final_papers)
                    cited_text = builder.suggest_citations(para, final_papers, bibtex_entries)
                    
                    # Write paragraph with citations
                    out.write(cited_text + "\n\n")
                    
                    # Write BibTeX entries
                    out.write('\n'.join(entry for _, entry in bibtex_entries))
                    out.write("\n\n")
                    out.write("-" * 80 + "\n\n")

def main():
    if len(sys.argv) != 2:
        print("Usage: python process_paragraphs.py path/to/paragraphs/file")
        sys.exit(1)
    
    file_path = sys.argv[1]
    if not Path(file_path).exists():
        print(f"Error: File {file_path} not found")
        sys.exit(1)
    
    process_paragraphs(file_path)

if __name__ == "__main__":
    main()