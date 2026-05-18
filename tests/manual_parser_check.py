import importlib.util
import sys
from pathlib import Path

script_dir = Path(__file__).resolve().parent
package_root = script_dir.parent
parsing_dir = package_root / "src" / "parsing"

for module_name, filename in [
    ("src.parsing.text_cleaner", "text_cleaner.py"),
]:
    module_path = parsing_dir / filename
    spec = importlib.util.spec_from_file_location(module_name, module_path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    spec.loader.exec_module(module)

# If pdfplumber isn't available in this environment, provide a no-op fallback
pdf_module = importlib.util.module_from_spec(importlib.util.spec_from_loader("src.parsing.pdf_table_extractor", loader=None))
pdf_module.extract_skills_from_pdf_tables = lambda *args, **kwargs: []
sys.modules["src.parsing.pdf_table_extractor"] = pdf_module

enhanced_path = parsing_dir / "enhanced_parser.py"
spec = importlib.util.spec_from_file_location("src.parsing.enhanced_parser", enhanced_path)
enhanced_parser = importlib.util.module_from_spec(spec)
sys.modules["src.parsing.enhanced_parser"] = enhanced_parser
spec.loader.exec_module(enhanced_parser)

samples = [
    {
        "name": "education_professional",
        "content": "• Professional",
        "parser": enhanced_parser.parse_education_section,
    },
    {
        "name": "experience_having_10_years",
        "content": (
            "• having 10+ years of\n"
            "• experiences in the IT and Security domain with strong Academic\n"
            "• background , Professional"
        ),
        "parser": enhanced_parser.parse_experience_section,
    },
]

for sample in samples:
    result = sample["parser"](sample["content"])
    print(f"=== {sample['name']} ===")
    print(f"input:\n{sample['content']}\n")
    print("output:")
    for item in result:
        print(f"  - {item}")
    print()
