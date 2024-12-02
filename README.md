# Reference Builder

A tool that uses GPT-4 and arXiv to automatically find and add relevant citations to your LaTeX papers.

## Features

- Extracts main ideas from text using OpenAI's GPT models
- Searches arXiv for relevant papers
- Filters papers based on relevance to original ideas
- Fetches additional papers from top authors using Arxiv
- Ranks papers by relevance

## Setup

1. Install dependencies:
```bash
pip install -r requirements.txt
```

2. Create a `.env` file with your OpenAI API key:
```
OPENAI_API_KEY=your_api_key_here
```

## Usage

### 1. Extract Clean Paragraphs

First, convert your LaTeX paper into clean, processable paragraphs:

```bash
python tex_to_paragraphs.py path/to/your/paper.tex
```

This creates `paper.paragraphs` containing clean text with:
- LaTeX commands removed
- Content split into paragraphs
- Short paragraphs (<20 words) filtered out

### 2. Get Citations (Two Options)

#### Option A: Process Individual Paragraphs (Recommended)

Copy each paragraph from `paper.paragraphs` and feed it to the reference builder:

```bash
python reference_builder.py < input_paragraph.txt
```

For each paragraph, this will:
1. Get paper suggestions from GPT-4
2. Validate them on arXiv
3. Find related papers by key authors
4. Generate:
   - BibTeX entries in `results/references.bib`
   - Suggested citation placements
   - Detailed paper information

#### Option B: Batch Process (Might be broken)

Process all paragraphs at once (note: this might be unstable):

```bash
python process_paragraphs.py path/to/paper.paragraphs
```

### Output Files

The `results/` directory will contain:
- `references.bib`: BibTeX entries
- `phase1_suggestions.json`: Initial suggestions
- `phase2_validated.json`: Validated papers
- `phase3_final_papers.json`: Final selections with author expansions

### Workflow Tips

1. Process one section at a time through `reference_builder.py`
2. Review and merge the generated BibTeX entries
3. Copy the suggested citation placements back into your LaTeX file
4. Verify all citations are relevant to your context

## Note

The tool uses GPT-4 for suggestions. Always review the output for accuracy and relevance in your specific context.
