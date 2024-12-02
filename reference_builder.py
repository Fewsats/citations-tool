#!/usr/bin/env python3

import sys
import json
from pathlib import Path
from typing import List, Dict, Optional
from dataclasses import dataclass
import arxiv
from openai import OpenAI
from rich.console import Console
from rich.panel import Panel

console = Console()

@dataclass
class SuggestedPaper:
    """A paper suggested by GPT for citation."""
    title: str
    authors: Optional[List[str]] = None
    year: Optional[int] = None
    arxiv_url: Optional[str] = None
    pdf_url: Optional[str] = None
    abstract: Optional[str] = None
    
class ReferenceBuilder:
    def __init__(self):
        self.client = OpenAI()
        self.results_dir = Path("search_results")
        self.results_dir.mkdir(exist_ok=True)
    
    def get_suggested_papers(self, text: str) -> List[SuggestedPaper]:
        """Phase 1: Ask GPT to suggest papers that would be good citations."""
        console.print("[bold green]Phase 1: Getting paper suggestions...[/]")
        
        response = self.client.chat.completions.create(
            model="gpt-4o",
            messages=[
                {"role": "system", "content": """Suggest real and already published academic papers that would be good citations for this text.
Focus on papers that:
1. Directly support or relate to the key claims and concepts
2. Are foundational works in the field
3. Represent recent developments or state-of-the-art

Format each suggestion as:
Title: <paper title>
Year: <year if known>
Arxiv URL: <arxiv url>
Authors: <main authors>
Relevance: <brief explanation of why this paper is relevant>
"""},
                {"role": "user", "content": text}
            ]
        )
        
        # Parse GPT's response into structured paper suggestions
        suggestions = []
        current_paper = {}
        
        print(response.choices[0].message.content.strip().split('\n'))
        for line in response.choices[0].message.content.strip().split('\n'):
            line = line.strip()
            if not line:
                if current_paper.get('title'):
                    suggestions.append(SuggestedPaper(
                        title=current_paper.get('title', ''),
                        authors=current_paper.get('authors', []),
                        year=current_paper.get('year'),
                        arxiv_url=current_paper.get('arxiv_url')
                    ))
                current_paper = {}
                continue
                
            if line.startswith('Title:'):
                if current_paper.get('title'):
                    suggestions.append(SuggestedPaper(
                        title=current_paper.get('title', ''),
                        authors=current_paper.get('authors', []),
                        year=current_paper.get('year'),
                        arxiv_url=current_paper.get('arxiv_url')
                    ))
                current_paper = {'title': line[6:].strip()}
            elif line.startswith('Year:'):
                try:
                    current_paper['year'] = int(line[5:].strip())
                except ValueError:
                    pass
            elif line.startswith('Authors:'):
                current_paper['authors'] = [a.strip() for a in line[8:].split(',')]
            elif line.startswith('Relevance:'):
                current_paper['relevance'] = line[10:].strip()
            elif line.startswith('Arxiv URL:'):
                current_paper['arxiv_url'] = line[11:].strip()
        
        # Add the last paper if exists
        if current_paper.get('title'):
            suggestions.append(SuggestedPaper(
                title=current_paper.get('title', ''),
                authors=current_paper.get('authors', []),
                year=current_paper.get('year'),
                arxiv_url=current_paper.get('arxiv_url')
            ))
        
        # Display initial suggestions
        console.print(f"\n[bold blue]Found {len(suggestions)} suggested papers:[/]")
        for i, paper in enumerate(suggestions, 1):
            console.print(Panel(
                f"[bold blue]Suggestion {i}:[/]\n" +
                f"[bold]Title:[/] {paper.title}\n" +
                f"[bold]Authors:[/] {', '.join(paper.authors) if paper.authors else 'Unknown'}\n" +
                f"[bold]Year:[/] {paper.year if paper.year else 'Unknown'}\n" +
                f"[bold]Arxiv URL:[/] {paper.arxiv_url if paper.arxiv_url else 'Unknown'}"
            ))
        
        self.save_phase_results("phase1_suggestions", {"papers": [vars(p) for p in suggestions]})
        return suggestions
    
    def validate_on_arxiv(self, suggestions: List[SuggestedPaper]) -> List[SuggestedPaper]:
        """Phase 2: Check which suggested papers exist on arXiv and get their details."""
        console.print("\n[bold green]Phase 2: Validating papers on arXiv...[/]")
        
        validated_papers = []
        for paper in suggestions:
            # Search by title
            console.print(f"\n[blue]Searching for: [italic]{paper.title}[/]")
            search = arxiv.Search(
                query=f'ti:"{paper.title}"',
                max_results=1
            )
            
            try:
                results = list(arxiv.Client().results(search))
                if results:
                    result = results[0]
                    paper.arxiv_id = result.entry_id
                    paper.pdf_url = result.pdf_url
                    paper.abstract = result.summary
                    paper.authors = [a.name for a in result.authors]
                    paper.year = result.published.year if result.published else paper.year
                    validated_papers.append(paper)
                    console.print("[green]Found on arXiv!")
                else:
                    console.print("[yellow]Not found on arXiv")
            except Exception as e:
                console.print(f"[red]Search error: {str(e)}[/]")
        
        console.print(f"\n[bold blue]Validated {len(validated_papers)} papers on arXiv[/]")
        self.save_phase_results("phase2_validated", {"papers": [vars(p) for p in validated_papers]})
        return validated_papers
    
    def expand_by_key_authors(self, validated_papers: List[SuggestedPaper], original_text: str) -> List[Dict]:
        """Phase 3: Find additional papers from key authors and combine with validated papers."""
        console.print("\n[bold green]Phase 3: Expanding by key authors...[/]")
        
        # Convert validated papers to dict format
        initial_papers = [{
            'title': p.title,
            'authors': p.authors,
            'url': p.arxiv_id,
            'pdf_url': p.pdf_url,
            'year': p.year,
            'abstract': p.abstract,
            'source': 'initial'
        } for p in validated_papers]
        
        # For each validated paper, identify its main authors
        for paper in validated_papers:
            console.print(f"\n[blue]Analyzing authors for: [italic]{paper.title}[/]")
            
            response = self.client.chat.completions.create(
                model="gpt-4o",
                messages=[
                    {"role": "system", "content": """Identify the main authors of this paper who are most likely to have written other important papers in this area.
Consider:
1. First author (usually the primary contributor)
2. Last author (often the senior researcher/supervisor)
3. Any particularly notable researchers

Return just the names, one per line."""},
                    {"role": "user", "content": f"Paper: {paper.title}\nAuthors: {', '.join(paper.authors) if paper.authors else 'Unknown'}"}
                ]
            )
            
            key_authors = [a.strip() for a in response.choices[0].message.content.strip().split('\n')]
            console.print(f"Main authors: {', '.join(key_authors)}")
            
            # Search for papers by these authors
            author_papers = []
            for author in key_authors:
                console.print(f"[blue]Searching papers by: [italic]{author}[/]")
                search = arxiv.Search(
                    query=f'au:"{author}"',
                    max_results=20,
                    sort_by=arxiv.SortCriterion.Relevance
                )
                
                try:
                    papers = list(arxiv.Client().results(search))
                    if papers:
                        author_papers.extend([{
                            'title': p.title,
                            'authors': [a.name for a in p.authors],
                            'url': p.entry_id,
                            'pdf_url': p.pdf_url,
                            'year': p.published.year if p.published else None,
                            'abstract': p.summary,
                            'from_author': author,
                            'source': 'author_search',
                            'original_paper': paper.title
                        } for p in papers])
                except Exception as e:
                    console.print(f"[red]Author search error: {str(e)}[/]")
        
        # Combine initial and author papers, removing duplicates
        all_papers = initial_papers + author_papers
        unique_papers = {p['url']: p for p in all_papers}.values()
        
        # Filter all papers for relevance
        if len(unique_papers) > 0:
            console.print("\n[blue]Filtering all papers for relevance...[/]")
            response = self.client.chat.completions.create(
                model="gpt-4o",
                messages=[
                    {"role": "system", "content": """Select the most relevant papers for the research context.
Consider:
1. Direct relevance to the technical concepts and methodologies
2. Balance between foundational papers and recent developments
3. Significance of contributions to the field
4. Complementary perspectives and approaches

Return paper URLs in order of relevance, one per line."""},
                    {"role": "user", "content": f"""Original Text:
{original_text}

Papers to Consider:
{chr(10).join([f'Title: {p["title"]}\nAbstract: {p["abstract"]}\nAuthors: {", ".join(p["authors"])}\nYear: {p.get("year", "N/A")}\nURL: {p["url"]}\n' for p in unique_papers])}"""}
                ]
            )
            
            selected_urls = [url.strip() for url in response.choices[0].message.content.strip().split('\n')]
            final_papers = [p for p in unique_papers if p['url'] in selected_urls]
        else:
            final_papers = []
        
        self.save_phase_results("phase3_final_papers", {
            "initial_papers": initial_papers,
            "additional_papers": [p for p in final_papers if p['source'] == 'author_search'],
            "all_papers": final_papers
        })
        return final_papers
    
    def save_phase_results(self, phase: str, data: dict):
        """Save intermediate results to a JSON file."""
        output_file = self.results_dir / f"{phase}.json"
        with open(output_file, 'w') as f:
            json.dump(data, f, indent=2)
    
    def generate_bibtex(self, papers: List[Dict]) -> List[tuple[str, str]]:
        """Generate BibTeX entries for the papers. Returns list of (citation_key, entry) tuples."""
        entries = []
        for paper in papers:
            # Create citation key: FirstAuthorLastNameYear
            first_author = paper['authors'][0].split()[-1] if paper['authors'] else 'Unknown'
            year = paper.get('year', '')
            citation_key = f"{first_author}{year}"
            
            # Clean the title (remove special characters, keep only alphanumeric and basic punctuation)
            title = paper['title'].replace('\n', ' ').replace('{', '\\{').replace('}', '\\}')
            
            # Format authors
            authors = ' and '.join(paper['authors'])
            
            # Get arXiv identifier from URL
            arxiv_id = paper['url'].split('/')[-1]
            
            entry = f"""@article{{{citation_key},
  title={{{title}}},
  author={{{authors}}},
  year={{{year}}},
  eprint={{{arxiv_id}}},
  archivePrefix={{arXiv}},
  primaryClass={{cs.CR}},
  url={{{paper['url']}}}
}}"""
            entries.append((citation_key, entry))
        
        return entries

    def suggest_citations(self, text: str, papers: List[Dict], bibtex_entries: List[tuple[str, str]]) -> str:
        """Suggest where to add citations in the text."""
        console.print("\n[bold green]Suggesting citations...[/]")
        
        # Create a mapping of papers to their citation keys
        citation_keys = {p['title']: key for p, (key, _) in zip(papers, bibtex_entries)}
        
        # Ask GPT to suggest citation placements
        response = self.client.chat.completions.create(
            model="gpt-4o",
            messages=[
                {"role": "system", "content": """Add LaTeX citations to the text where appropriate.
Use \\cite{key} format for citations.
Available citation keys are provided in the papers list.
Add citations at the end of relevant sentences.
Multiple papers can be cited together using \\cite{key1,key2}."""},
                {"role": "user", "content": f"""Text to add citations to:
{text}

Available Papers and their citation keys:
{chr(10).join([f"- {p['title']}: {citation_keys[p['title']]}" for p in papers])}"""}
            ]
        )
        
        return response.choices[0].message.content.strip()

def main():
    builder = ReferenceBuilder()
    
    # Get input text
    console.print("\n[bold]Enter your text (press Ctrl+D when finished):[/]")
    try:
        text = sys.stdin.read().strip()
    except EOFError:
        console.print("\n[bold red]Input error. Exiting.[/]")
        sys.exit(1)
    
    # Phase 1: Get paper suggestions from GPT
    suggested_papers = builder.get_suggested_papers(text)
    
    # Phase 2: Validate papers on arXiv
    validated_papers = builder.validate_on_arxiv(suggested_papers)
    if not validated_papers:
        console.print("\n[bold red]No suggested papers found on arXiv.[/]")
        sys.exit(0)
    
    # Phase 3: Expand by key authors and combine with initial papers
    final_papers = builder.expand_by_key_authors(validated_papers, text)
    
    if not final_papers:
        console.print("\n[bold red]No papers selected.[/]")
        sys.exit(0)
    
    # Generate BibTeX
    bibtex_entries = builder.generate_bibtex(final_papers)
    
    # Save BibTeX to file
    bibtex_content = '\n\n'.join(entry for _, entry in bibtex_entries)
    bibtex_file = builder.results_dir / "references.bib"
    with open(bibtex_file, 'w') as f:
        f.write(bibtex_content)
    console.print(f"\n[bold green]BibTeX entries saved to {bibtex_file}[/]")
    
    # Get citation suggestions
    cited_text = builder.suggest_citations(text, final_papers, bibtex_entries)
    
    # Display results with rich formatting for paper details
    console.print("\n[bold blue]Selected Papers:[/]")
    for i, ((citation_key, _), paper) in enumerate(zip(bibtex_entries, final_papers), 1):
        source = "Initial Suggestion" if paper['source'] == 'initial' else f"Found via {paper['from_author']}"
        if paper['source'] == 'author_search':
            source += f" (from {paper['original_paper']})"
            
        console.print(Panel(
            f"[bold blue]Paper {i}:[/]\n" +
            f"[bold]Citation Key:[/] {citation_key}\n" +
            f"[bold]Title:[/] {paper['title']}\n" +
            f"[bold]Authors:[/] {', '.join(paper['authors'])}\n" +
            f"[bold]Year:[/] {paper.get('year', 'N/A')}\n" +
            f"[bold]Source:[/] {source}\n" +
            f"[bold]PDF:[/] {paper['pdf_url']}"
        ))
    
    # Print plain text BibTeX entries
    print("\n=== BibTeX Entries ===")
    print(bibtex_content)
    
    # Print plain text cited version
    print("\n=== Text with Citations ===")
    print(cited_text)

if __name__ == "__main__":
    main()
