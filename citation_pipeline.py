#!/usr/bin/env python3

import json
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import List, Dict, Optional, Set
import arxiv
from openai import OpenAI
from rich.console import Console
from rich.panel import Panel

console = Console()

@dataclass
class CitationTarget:
    """Represents a concept or claim that needs citation"""
    text: str  # The specific text that needs citation
    explanation: str  # Why this needs citation
    suggested_papers: List[Dict]  # Papers that could cite this

@dataclass
class Paper:
    """Represents a paper that could be used as a citation"""
    title: str
    authors: List[str]
    year: Optional[int] = None
    arxiv_id: Optional[str] = None
    arxiv_url: Optional[str] = None
    pdf_url: Optional[str] = None
    abstract: Optional[str] = None
    relevance: Optional[str] = None
    source: str = "direct"  # direct/author_search

class CitationPipeline:
    """
    A pipeline for finding and suggesting academic citations.
    Uses a step-by-step approach:
    1. Identify what needs citation
    2. Find papers for those citations
    3. Expand search through author networks
    4. Generate formatted citations
    """
    
    def __init__(self):
        self.client = OpenAI()
        self.results_dir = Path("results")
        self.results_dir.mkdir(exist_ok=True)

    def load_paragraph(self, paragraph_num: int) -> str:
        """
        Load and preview a specific paragraph, asking for user confirmation.
        Returns the paragraph text if confirmed, exits if not.
        """
        try:
            with open('minds_from_markets.json', 'r') as f:
                data = json.load(f)
                text = data[str(paragraph_num)]
                
                # Show preview
                preview = ' '.join(text.split()[:7]) + "..."
                console.print(f"\n[bold blue]Preview of paragraph {paragraph_num}:[/]")
                console.print(f"[italic]{preview}[/]")
                
                if input("\nProceed with this paragraph? (y/n): ").lower().strip() != 'y':
                    console.print("[yellow]Operation cancelled by user[/]")
                    sys.exit(0)
                    
                return text
        except (FileNotFoundError, KeyError) as e:
            console.print(f"[bold red]Error loading paragraph: {e}[/]")
            sys.exit(1)

    def identify_citation_needs(self, text: str) -> List[CitationTarget]:
        """
        Analyze text to identify specific claims, statements, or concepts
        that would benefit from academic citations.
        """
        console.print("\n[bold green]Identifying citation needs...[/]")
        
        response = self.client.chat.completions.create(
            model="gpt-4o",
            messages=[
                {"role": "system", "content": """Identify specific claims or statements that should be supported by academic citations.
For each, explain why it needs citation and what kind of source would be appropriate.

Format as:
CLAIM: <text requiring citation>
REASON: <why this needs citation>
PAPERS: <description of ideal supporting papers>"""},
                {"role": "user", "content": text}
            ]
        )

        # Parse response into CitationTarget objects
        targets = []
        current_target = {}
        
        for line in response.choices[0].message.content.strip().split('\n'):
            if line.startswith('CLAIM:'):
                if current_target.get('text'):
                    targets.append(CitationTarget(
                        text=current_target['text'],
                        explanation=current_target.get('reason', ''),
                        suggested_papers=[]
                    ))
                current_target = {'text': line[6:].strip()}
            elif line.startswith('REASON:'):
                current_target['reason'] = line[7:].strip()
            elif line.startswith('PAPERS:'):
                current_target['papers'] = line[7:].strip()

        # Add the last target
        if current_target.get('text'):
            targets.append(CitationTarget(
                text=current_target['text'],
                explanation=current_target.get('reason', ''),
                suggested_papers=[]
            ))

        return targets

    def find_papers_for_targets(self, targets: List[CitationTarget]) -> List[Paper]:
        """
        For each citation target, find specific papers that could serve as citations.
        Uses GPT to suggest papers and then validates them against arXiv.
        """
        console.print("\n[bold green]Finding papers for citation targets...[/]")
        
        papers = []
        for target in targets:
            console.print(f"\n[blue]Finding papers for: [italic]{target.text[:100]}...[/]")
            
            # Ask GPT for paper suggestions specific to this target
            response = self.client.chat.completions.create(
                model="gpt-4o",
                messages=[
                    {"role": "system", "content": """Suggest specific academic papers that would support this claim.
Focus on papers that are:
1. Directly relevant to the specific claim
2. Foundational works if the claim is about established concepts
3. Recent developments for current state claims

Format each suggestion as:
Title: <paper title>
Year: <year if known>
Arxiv URL: <arxiv url>
Authors: <main authors>
Relevance: <brief explanation of why this paper supports the specific claim>"""},
                    {"role": "user", "content": f"""Claim: {target.text}
Why it needs citation: {target.explanation}
Ideal papers would be: {target.suggested_papers}"""}
                ]
            )
            
            # Parse response into Paper objects
            current_paper = {}
            for line in response.choices[0].message.content.strip().split('\n'):
                line = line.strip()
                if not line:
                    if current_paper.get('title'):
                        papers.append(Paper(**current_paper))
                        current_paper = {}
                    continue
                
                if line.startswith('Title:'):
                    if current_paper.get('title'):
                        papers.append(Paper(**current_paper))
                    current_paper = {'title': line[6:].strip()}
                elif line.startswith('Year:'):
                    try:
                        current_paper['year'] = int(line[5:].strip())
                    except ValueError:
                        pass
                elif line.startswith('Authors:'):
                    current_paper['authors'] = [a.strip() for a in line[8:].split(',')]
                elif line.startswith('Arxiv URL:'):
                    current_paper['arxiv_url'] = line[10:].strip()
                elif line.startswith('Relevance:'):
                    current_paper['relevance'] = line[10:].strip()
            
            # Add last paper if exists
            if current_paper.get('title'):
                papers.append(Paper(**current_paper))
        
        return papers

    def validate_papers(self, papers: List[Paper]) -> List[Paper]:
        """
        Validate suggested papers against arXiv and enrich with metadata.
        Returns only papers that can be verified.
        """
        console.print("\n[bold green]Validating papers on arXiv...[/]")
        
        validated = []
        for paper in papers:
            console.print(f"\n[blue]Validating: [italic]{paper.title}[/]")
            
            # First try by URL if available
            if paper.arxiv_url:
                try:
                    arxiv_id = paper.arxiv_url.split('/')[-1]
                    if 'arxiv.org' in paper.arxiv_url and arxiv_id:
                        search = arxiv.Search(id_list=[arxiv_id])
                        results = list(arxiv.Client().results(search))
                        
                        if results and self._titles_match(paper.title, results[0].title):
                            result = results[0]
                            paper.arxiv_id = result.entry_id
                            paper.pdf_url = result.pdf_url
                            paper.abstract = result.summary
                            paper.authors = [a.name for a in result.authors]
                            paper.year = result.published.year if result.published else paper.year
                            validated.append(paper)
                            console.print("[green]Successfully validated by arXiv URL!")
                            continue
                except Exception as e:
                    console.print(f"[yellow]URL validation failed: {str(e)}")
            
            # If URL validation failed or no URL, try title search
            found_paper = self._search_arxiv_by_title(paper)
            if found_paper:
                validated.append(found_paper)
        
        return validated

    def _titles_match(self, title1: str, title2: str) -> bool:
        """Compare two titles, ignoring case and punctuation."""
        import re
        def normalize(title: str) -> str:
            return re.sub(r'[^\w\s]', '', title.lower())
        return normalize(title1) == normalize(title2)

    def _search_arxiv_by_title(self, paper: Paper) -> Optional[Paper]:
        """Search arXiv for a paper by title and return enriched Paper if found."""
        try:
            search_title = paper.title.replace(':', ' ').replace('-', ' ')
            search = arxiv.Search(
                query=f'ti:"{search_title}"',
                max_results=10,
                sort_by=arxiv.SortCriterion.Relevance
            )
            
            results = list(arxiv.Client().results(search))
            
            # Try exact match first
            for result in results:
                if self._titles_match(paper.title, result.title):
                    paper.arxiv_id = result.entry_id
                    paper.pdf_url = result.pdf_url
                    paper.abstract = result.summary
                    paper.authors = [a.name for a in result.authors]
                    paper.year = result.published.year if result.published else paper.year
                    paper.arxiv_url = f"https://arxiv.org/abs/{result.entry_id.split('/')[-1]}"
                    console.print("[green]Found exact title match!")
                    return paper
            
            # If no exact match, show options to user
            if results:
                console.print("[yellow]No exact match found. Potential matches:")
                for i, result in enumerate(results, 1):
                    console.print(f"\n[cyan]{i}.[/] {result.title}")
                    console.print(f"   Authors: {', '.join(a.name for a in result.authors)}")
                    console.print(f"   Year: {result.published.year if result.published else 'N/A'}")
                
                choice = input("\nEnter number of matching paper (or 0 to skip): ").strip()
                if choice.isdigit() and 0 < int(choice) <= len(results):
                    result = results[int(choice) - 1]
                    paper.arxiv_id = result.entry_id
                    paper.pdf_url = result.pdf_url
                    paper.abstract = result.summary
                    paper.authors = [a.name for a in result.authors]
                    paper.year = result.published.year if result.published else paper.year
                    paper.arxiv_url = f"https://arxiv.org/abs/{result.entry_id.split('/')[-1]}"
                    return paper
            
            return None
            
        except Exception as e:
            console.print(f"[red]Search error: {str(e)}")
            return None

    def expand_by_authors(self, validated_papers: List[Paper], original_text: str) -> List[Paper]:
        """
        Find additional relevant papers by key authors from validated papers.
        Returns combined list of original and newly found papers.
        """
        console.print("\n[bold green]Expanding search through author networks...[/]")
        
        # Get unique authors from validated papers
        all_authors = set()
        for paper in validated_papers:
            all_authors.update(paper.authors)
        
        # Ask GPT to identify key authors to focus on
        response = self.client.chat.completions.create(
            model="gpt-4o",
            messages=[
                {"role": "system", "content": """From the list of authors, identify who are most likely to have written other relevant papers.
Consider:
1. First authors (primary contributors)
2. Last authors (senior researchers)
3. Authors appearing multiple times
4. Authors known for work in this area

Return just the names, one per line."""},
                {"role": "user", "content": f"Authors from validated papers:\n{', '.join(all_authors)}"}
            ]
        )
        
        key_authors = [a.strip() for a in response.choices[0].message.content.strip().split('\n')]
        
        # Search for papers by key authors
        author_papers = []
        for author in key_authors:
            console.print(f"\n[blue]Searching papers by: [italic]{author}[/]")
            search = arxiv.Search(
                query=f'au:"{author}"',
                max_results=20,
                sort_by=arxiv.SortCriterion.Relevance
            )
            
            try:
                results = list(arxiv.Client().results(search))
                for result in results:
                    paper = Paper(
                        title=result.title,
                        authors=[a.name for a in result.authors],
                        year=result.published.year if result.published else None,
                        arxiv_id=result.entry_id,
                        arxiv_url=f"https://arxiv.org/abs/{result.entry_id.split('/')[-1]}",
                        pdf_url=result.pdf_url,
                        abstract=result.summary,
                        source="author_search"
                    )
                    author_papers.append(paper)
            except Exception as e:
                console.print(f"[red]Author search error: {str(e)}")
        
        # Filter expanded papers for relevance
        if author_papers:
            console.print("\n[blue]Filtering expanded papers for relevance...[/]")
            response = self.client.chat.completions.create(
                model="gpt-4o",
                messages=[
                    {"role": "system", "content": """Review these papers and identify which ones are relevant to the original text.
For each relevant paper, explain why it should be included.

Format as:
PAPER: <title>
REASON: <explanation of relevance>

Only include truly relevant papers."""},
                    {"role": "user", "content": f"""Original Text:
{original_text}

Papers to Consider:
{chr(10).join([f'Title: {p.title}\nAbstract: {p.abstract}\nAuthors: {", ".join(p.authors)}\nYear: {p.year}' for p in author_papers])}"""}
                ]
            )
            
            # Parse response and filter papers
            relevant_papers = []
            current_paper = {}
            for line in response.choices[0].message.content.strip().split('\n'):
                if line.startswith('PAPER:'):
                    if current_paper.get('title'):
                        paper = next((p for p in author_papers if self._titles_match(p.title, current_paper['title'])), None)
                        if paper:
                            paper.relevance = current_paper.get('reason')
                            relevant_papers.append(paper)
                    current_paper = {'title': line[6:].strip()}
                elif line.startswith('REASON:'):
                    current_paper['reason'] = line[7:].strip()
            
            # Add last paper if exists
            if current_paper.get('title'):
                paper = next((p for p in author_papers if self._titles_match(p.title, current_paper['title'])), None)
                if paper:
                    paper.relevance = current_paper.get('reason')
                    relevant_papers.append(paper)
            
            # Combine original and new papers
            all_papers = validated_papers + relevant_papers
            
            # Remove duplicates while preserving order
            seen = set()
            unique_papers = []
            for paper in all_papers:
                if paper.arxiv_id not in seen:
                    seen.add(paper.arxiv_id)
                    unique_papers.append(paper)
            
            return unique_papers
        
        return validated_papers

    def generate_bibtex(self, papers: List[Paper]) -> List[tuple[str, str]]:
        """
        Generate BibTeX entries for the papers.
        Returns list of (citation_key, entry) tuples.
        """
        console.print("\n[bold green]Generating BibTeX entries...[/]")
        entries = []
        
        for paper in papers:
            # Create citation key: FirstAuthorLastNameYear
            first_author = paper.authors[0].split()[-1] if paper.authors else 'Unknown'
            year = paper.year or ''
            citation_key = f"{first_author}{year}"
            
            # Clean the title
            title = paper.title.replace('\n', ' ').replace('{', '\\{').replace('}', '\\}')
            
            # Format authors
            authors = ' and '.join(paper.authors)
            
            # Get arXiv identifier
            arxiv_id = paper.arxiv_id.split('/')[-1] if paper.arxiv_id else ''
            
            entry = f"""@article{{{citation_key},
  title={{{title}}},
  author={{{authors}}},
  year={{{year}}},
  eprint={{{arxiv_id}}},
  archivePrefix={{arXiv}},
  primaryClass={{cs.CR}},
  url={{{paper.arxiv_url or ''}}}
}}"""
            entries.append((citation_key, entry))
            
        return entries

    def suggest_citation_placement(self, text: str, papers: List[Paper], bibtex_entries: List[tuple[str, str]]) -> str:
        """
        Suggest where to add citations in the text.
        Returns the text with citations added in LaTeX format.
        """
        console.print("\n[bold green]Suggesting citation placements...[/]")
        
        # Create paper details for GPT
        paper_details = []
        for paper, (key, _) in zip(papers, bibtex_entries):
            details = {
                'key': key,
                'title': paper.title,
                'abstract': paper.abstract,
                'relevance': paper.relevance,
                'year': paper.year
            }
            paper_details.append(details)
        
        # Ask GPT to place citations
        response = self.client.chat.completions.create(
            model="gpt-4o",
            messages=[
                {"role": "system", "content": """Add LaTeX citations to the text where appropriate.
Use \\cite{key} format for citations.
Add citations at the end of relevant sentences.
Multiple papers can be cited together using \\cite{key1,key2}.
Only cite papers where they directly support the text.
Preserve all original text formatting."""},
                {"role": "user", "content": f"""Text to add citations to:
{text}

Available Papers:
{chr(10).join([
    f"Citation Key: {p['key']}\n"
    f"Title: {p['title']}\n"
    f"Year: {p['year']}\n"
    f"Abstract: {p['abstract']}\n"
    f"Relevance: {p['relevance']}\n"
    for p in paper_details
])}"""}
            ]
        )
        
        return response.choices[0].message.content.strip()

    def save_results(self, paragraph_num: int, results: dict):
        """Save all results to a JSON file."""
        output_file = self.results_dir / f"paragraph_{paragraph_num}_results.json"
        with open(output_file, 'w') as f:
            json.dump(results, f, indent=2)
        console.print(f"\n[green]Results saved to {output_file}[/]")

def main():
    """Main execution flow of the citation pipeline."""
    pipeline = CitationPipeline()
    
    # Parse command line arguments
    if len(sys.argv) != 2:
        console.print("[bold red]Usage: python citation_pipeline.py <paragraph_number>[/]")
        sys.exit(1)
    
    try:
        paragraph_num = int(sys.argv[1])
    except ValueError:
        console.print("[bold red]Paragraph number must be an integer[/]")
        sys.exit(1)
    
    # Load and confirm paragraph
    text = pipeline.load_paragraph(paragraph_num)
    
    # Step 1: Identify what needs citation
    citation_targets = pipeline.identify_citation_needs(text)
    if not citation_targets:
        console.print("[yellow]No citation targets identified in this paragraph.[/]")
        sys.exit(0)
    
    # Step 2: Find papers for citations
    suggested_papers = pipeline.find_papers_for_targets(citation_targets)
    if not suggested_papers:
        console.print("[yellow]No papers found for citation targets.[/]")
        sys.exit(0)
    
    # Step 3: Validate papers on arXiv
    validated_papers = pipeline.validate_papers(suggested_papers)
    if not validated_papers:
        console.print("[yellow]No papers could be validated on arXiv.[/]")
        sys.exit(0)
    
    # Step 4: Expand through author networks
    final_papers = pipeline.expand_by_authors(validated_papers, text)
    
    # Step 5: Generate citations
    bibtex_entries = pipeline.generate_bibtex(final_papers)
    
    # Step 6: Suggest citation placement
    cited_text = pipeline.suggest_citation_placement(text, final_papers, bibtex_entries)
    
    # Save results
    results = {
        "paragraph_number": paragraph_num,
        "original_text": text,
        "citation_targets": [vars(t) for t in citation_targets],
        "final_papers": [vars(p) for p in final_papers],
        "bibtex_entries": [entry for _, entry in bibtex_entries],
        "cited_text": cited_text
    }
    pipeline.save_results(paragraph_num, results)
    
    # Display results
    console.print("\n[bold blue]Final Results:[/]")
    
    # Show citation targets
    console.print("\n[bold cyan]Citation Targets:[/]")
    for i, target in enumerate(citation_targets, 1):
        console.print(Panel(
            f"[bold]Target {i}:[/]\n{target.text}\n\n"
            f"[bold]Reason:[/]\n{target.explanation}",
            border_style="cyan"
        ))
    
    # Show selected papers
    console.print("\n[bold cyan]Selected Papers:[/]")
    for i, ((citation_key, _), paper) in enumerate(zip(bibtex_entries, final_papers), 1):
        console.print(Panel(
            f"[bold]Paper {i}:[/]\n"
            f"Citation Key: {citation_key}\n"
            f"Title: {paper.title}\n"
            f"Authors: {', '.join(paper.authors)}\n"
            f"Year: {paper.year}\n"
            f"Relevance: {paper.relevance}\n"
            f"PDF: {paper.pdf_url}",
            border_style="cyan"
        ))
    
    # Show BibTeX
    console.print("\n[bold cyan]BibTeX Entries:[/]")
    print('\n\n'.join(entry for _, entry in bibtex_entries))
    
    # Show cited text
    console.print("\n[bold cyan]Text with Citations:[/]")
    print(cited_text)

if __name__ == "__main__":
    main()