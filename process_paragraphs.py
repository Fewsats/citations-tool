import json

def process_paragraphs(input_file, output_file):
    # Read paragraphs and filter out empty lines
    with open(input_file, 'r', encoding='utf-8') as f:
        paragraphs = [p.strip() for p in f.read().split('\n\n') if p.strip()]
    
    # Create dictionary with numbered keys
    paragraph_dict = {str(i+1): p for i, p in enumerate(paragraphs)}
    
    # Write to JSON file with UTF-8 encoding
    with open(output_file, 'w', encoding='utf-8') as f:
        json.dump(paragraph_dict, f, indent=2, ensure_ascii=False)

if __name__ == "__main__":
    process_paragraphs('minds_from_markets.paragraphs', 'minds_from_markets.json') 