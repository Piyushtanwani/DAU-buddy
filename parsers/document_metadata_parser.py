import re
import logging

logger = logging.getLogger(__name__)

class DocumentMetadataParser:
    def __init__(self, collection_id: str):
        self.collection = collection_id

    def normalize_program(self, raw_program: str) -> str:
        if not raw_program:
            return ""
        
        # Remove "Program", extra spaces, standardize punctuation
        prog = raw_program.replace("Program", "").replace("_", " ").strip()
        
        # Normalize degrees
        prog = re.sub(r'M\s*Sc', 'MSc', prog, flags=re.IGNORECASE)
        prog = re.sub(r'B\s*Tech', 'BTech', prog, flags=re.IGNORECASE)
        prog = re.sub(r'M\s*Tech', 'MTech', prog, flags=re.IGNORECASE)
        prog = re.sub(r'Ph\s*D', 'PhD', prog, flags=re.IGNORECASE)
        prog = re.sub(r'M\s*Des', 'MDes', prog, flags=re.IGNORECASE)
        
        # Remove parens and extra spaces
        prog = prog.replace("(", " ").replace(")", " ")
        prog = re.sub(r'\s+', ' ', prog).strip()
        
        return prog

    def parse(self, filename: str) -> dict:
        """
        Extracts metadata from the filename.
        Returns a dictionary with:
        collection, degree, program, effective_year, title, filename, version
        """
        metadata = {
            'collection': self.collection,
            'filename': filename,
            'title': filename.replace('.pdf', ''),
            'degree': None,
            'program': None,
            'effective_year': None,
            'version': None
        }

        # Academic Requirements_MTech(CS&ML)_Program_wef 2021-22.pdf
        # Try to find the 'wef' (with effect from) part
        wef_match = re.search(r'wef\s*(?:Aut|Spr)?\s*(\d{4}-\d{2})', filename, re.IGNORECASE)
        if wef_match:
            metadata['effective_year'] = wef_match.group(1)
            metadata['version'] = metadata['effective_year']

        # Try to extract the program/degree
        if "Academic Requirement" in filename:
            # Drop the prefix and the wef part
            name_part = re.sub(r'^Academic Requirements?_?', '', filename, flags=re.IGNORECASE)
            name_part = re.sub(r'_?wef.*\.pdf$', '', name_part, flags=re.IGNORECASE)
            
            normalized = self.normalize_program(name_part)
            metadata['program'] = normalized
            
            # Simple heuristic for degree
            if 'BTech' in normalized:
                metadata['degree'] = 'BTech'
            elif 'MTech' in normalized:
                metadata['degree'] = 'MTech'
            elif 'MSc' in normalized:
                metadata['degree'] = 'MSc'
            elif 'PhD' in normalized:
                metadata['degree'] = 'PhD'
            elif 'MDes' in normalized:
                metadata['degree'] = 'MDes'
                
            metadata['title'] = f"Academic Requirements - {normalized}"

        return metadata
