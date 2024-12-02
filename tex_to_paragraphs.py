#!/usr/bin/env python3

import re
import sys
from pathlib import Path

def extract_paragraphs(latex_file: str) -> list[str]:
    """Extract paragraphs from LaTeX file, ignoring commands and environments."""
    with open(latex_file) as f:
        content = f.read()
    
    # Remove comments
    content = re.sub(r'%.*$', '', content, flags=re.MULTILINE)
    
    # Remove LaTeX commands and environments
    content = re.sub(r'\\[a-zA-Z]+(\[[^\]]*\])?({[^}]*})?', '', content)
    content = re.sub(r'\\[a-zA-Z]+', '', content)
    content = re.sub(r'\\[^a-zA-Z]', '', content)
    
    # Remove begin/end environments
    content = re.sub(r'\\begin{.*?}.*?\\end{.*?}', '', content, flags=re.DOTALL)
    
    # Split into paragraphs (double newlines)
    paragraphs = re.split(r'\n\s*\n', content)
    
    # Clean up paragraphs
    paragraphs = [
        ' '.join(p.split()) 
        for p in paragraphs 
        if p.strip() and len(p.split()) > 20  # Only keep paragraphs with >20 words
    ]
    
    return paragraphs

def main():
    if len(sys.argv) != 2:
        print("Usage: python latex_paragraph_extractor.py path/to/latex/file")
        sys.exit(1)
    
    latex_file = sys.argv[1]
    if not Path(latex_file).exists():
        print(f"Error: File {latex_file} not found")
        sys.exit(1)
    
    # Extract paragraphs
    paragraphs = extract_paragraphs(latex_file)
    
    # Create output file
    output_file = Path(latex_file).with_suffix('.paragraphs')
    
    # Write paragraphs to file with separators and numbers
    with open(output_file, 'w') as f:
        for i, para in enumerate(paragraphs, 1):
            f.write(f"{para}\n\n")
    
    print(f"Extracted {len(paragraphs)} paragraphs to {output_file}")
    print("You can now edit the file to remove unwanted paragraphs")
    print("Then use process_paragraphs.py to generate citations for the remaining ones")

if __name__ == "__main__":
    main()