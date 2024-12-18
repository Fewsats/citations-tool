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
    arxiv_id: Optional[str] = None
    
class ReferenceBuilder:
    def __init__(self):
        self.client = OpenAI()
        self.results_dir = Path("results")
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
        
        return suggestions
    
    def validate_by_arxiv_url(self, suggestions: List[SuggestedPaper]) -> List[SuggestedPaper]:
        """Phase 2: Check which suggested papers exist on arXiv and get their details."""
        console.print("\n[bold green]Phase 2: Validating papers on arXiv...[/]")
        
        validated_papers = []
        for paper in suggestions:
            console.print(f"\n[blue]Validating: [italic]{paper.title}[/]")
            
            # First try by URL if available
            validated = False
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
                            validated_papers.append(paper)
                            validated = True
                            console.print("[green]Successfully validated by arXiv URL!")
                except Exception as e:
                    console.print(f"[yellow]URL validation failed: {str(e)}")
            
            # If URL validation failed, try finding by title
            if not validated:
                console.print(f"[blue]Attempting to find paper by title... {paper.title}")
                found_paper = self.find_by_title(paper)
                if found_paper:
                    validated_papers.append(found_paper)
        
        console.print(f"\n[bold blue]Validated {len(validated_papers)} papers on arXiv[/]")
        return validated_papers
    
    def _titles_match(self, title1: str, title2: str) -> bool:
        """Compare two titles, ignoring case and punctuation."""
        import re
        def normalize(title: str) -> str:
            return re.sub(r'[^\w\s]', '', title.lower())
        
        return normalize(title1) == normalize(title2)
    
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
                    {"role": "system", "content": """Review the papers and identify which ones are most relevant for citation.
For each relevant paper, explain why it should be cited in relation to the research context.

Format your response as:
PAPER: <arxiv_url>
REASON: <detailed explanation of relevance>

Only include papers that are truly relevant."""},
                    {"role": "user", "content": f"""Original Text:
{original_text}

Papers to Consider:
{chr(10).join([f'Title: {p["title"]}\nAbstract: {p["abstract"]}\nAuthors: {", ".join(p["authors"])}\nYear: {p.get("year", "N/A")}\nURL: {p["url"]}\n' for p in unique_papers])}"""}
                ]
            )
            
            # Parse structured response
            selected_papers = []
            current_paper = {}
            print(response.choices[0].message.content.strip().split('\n'))    
            for line in response.choices[0].message.content.strip().split('\n'):
                line = line.strip()
                if line.startswith('PAPER:'):
                    if current_paper.get('url'):
                        selected_papers.append(current_paper)
                    current_paper = {'url': line[6:].strip()}
                elif line.startswith('REASON:'):
                    current_paper['reason'] = line[7:].strip()
            
            # Add the last paper if exists
            if current_paper.get('url'):
                selected_papers.append(current_paper)
            
            # Get final papers with their metadata
            final_papers = []
            for selection in selected_papers:
                paper = next((p for p in unique_papers if p['url'] == selection['url']), None)
                if paper:
                    paper['selection_reason'] = selection['reason']
                    final_papers.append(paper)
                    console.print(Panel(
                        f"[bold cyan]Selected Paper[/]\n\n"
                        f"[bold white]Title:[/] {paper['title']}\n\n"
                        f"[bold white]Authors:[/] {', '.join(paper['authors'])}\n"
                        f"[bold white]Year:[/] {paper.get('year', 'N/A')}\n\n"
                        f"[bold yellow]Relevance:[/]\n{selection['reason']}",
                        border_style="cyan",
                        padding=(1, 2),
                        title="[bold cyan]Citation Suggestion[/]",
                        expand=True
                    ))
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
        
        # Create a mapping of papers to their citation keys and details
        paper_details = []
        for paper, (key, _) in zip(papers, bibtex_entries):
            details = {
                'key': key,
                'title': paper['title'],
                'abstract': paper['abstract'],
                'reason': paper.get('selection_reason', 'No reason provided'),
                'year': paper.get('year', 'N/A')
            }
            paper_details.append(details)
        
        # Ask GPT to suggest citation placements
        response = self.client.chat.completions.create(
            model="gpt-4o",
            messages=[
                {"role": "system", "content": """Add LaTeX citations to the text where appropriate.
Use \\cite{key} format for citations.
Consider each paper's abstract and relevance when deciding where to place citations.
Add citations at the end of relevant sentences.
Multiple papers can be cited together using \\cite{key1,key2} when they support the same point.
Be precise in citation placement - only cite papers where they directly support the text."""},
                {"role": "user", "content": f"""Text to add citations to:
{text}

Available Papers:
{chr(10).join([
    f"Citation Key: {p['key']}\n"
    f"Title: {p['title']}\n"
    f"Year: {p['year']}\n"
    f"Abstract: {p['abstract']}\n"
    f"Relevance: {p['reason']}\n"
    for p in paper_details
])}"""}
            ]
        )
        
        return response.choices[0].message.content.strip()

    def load_phase_results(self, phase: str) -> dict:
        """Load results from a previous phase's JSON file."""
        input_file = self.results_dir / f"{phase}.json"
        if not input_file.exists():
            raise FileNotFoundError(f"No saved results found for {phase}")
        
        with open(input_file, 'r') as f:
            data = json.load(f)
        
        # Convert dict back to SuggestedPaper objects if loading phase1 or phase2
        if phase in ["phase1_suggestions", "phase2_validated"]:
            data["papers"] = [SuggestedPaper(**p) for p in data["papers"]]
        
        return data

    def find_by_title(self, paper: SuggestedPaper) -> Optional[SuggestedPaper]:
        """Search for a paper by title on arXiv and validate the match."""
        try:
            # Clean and format the title for search
            search_title = paper.title.replace(':', ' ').replace('-', ' ')
            search = arxiv.Search(
                query=f'ti:"{search_title}"',
                max_results=5,
                sort_by=arxiv.SortCriterion.Relevance
            )
            
            results = list(arxiv.Client().results(search))
            
            for result in results:
                if self._titles_match(paper.title, result.title):
                    paper.arxiv_id = result.entry_id
                    paper.pdf_url = result.pdf_url
                    paper.abstract = result.summary
                    paper.authors = [a.name for a in result.authors]
                    paper.year = result.published.year if result.published else paper.year
                    paper.arxiv_url = f"https://arxiv.org/abs/{result.entry_id.split('/')[-1]}"
                    console.print("[green]Found matching paper by title!")
                    return paper
                
            console.print("[yellow]No matching paper found by title")
            return None
            
        except Exception as e:
            console.print(f"[red]Title search error: {str(e)}[/]")
            return None

def main():
    builder = ReferenceBuilder()
    
    # Get input text
    console.print("\n[bold]Enter your text (press Ctrl+D when finished):[/]")
    try:
        text = sys.stdin.read().strip()
    except EOFError:
        console.print("\n[bold red]Input error. Exiting.[/]")
        sys.exit(1)
    

    # # Run Phase 1
    suggested_papers = builder.get_suggested_papers(text)
    builder.save_phase_results("phase1_suggestions", {"papers": [vars(p) for p in suggested_papers]})
    
    # Try to load phase 1 results
    # data = builder.load_phase_results("phase1_suggestions")
    # suggested_papers = data["papers"]
    # console.print("[bold green]Loaded saved results from phase 1[/]")
    
    # # Phase 2: Validate papers on arXiv
    validated_papers = builder.validate_by_arxiv_url(suggested_papers)
    if not validated_papers:
        console.print("\n[bold red]No suggested papers found on arXiv.[/]")
        sys.exit(0)
    builder.save_phase_results("phase2_validated", {"papers": [vars(p) for p in validated_papers]})

    # Try to load phase 2 results
    # data = builder.load_phase_results("phase2_validated")
    # validated_papers = [SuggestedPaper(**p) if isinstance(p, dict) else p for p in data["papers"]]
    # console.print("[bold green]Loaded saved results from phase 2[/]")

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
