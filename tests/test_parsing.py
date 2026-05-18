'''from src.parsing import parse_resume

for pdf in ["text_only.pdf", "with_tables.pdf"]:
    print(f"=== {pdf} ===")
    print(parse_resume(f"test_pdfs/{pdf}")[:500])'''  # First 500 chars
import sys
import os
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import pytest
from pathlib import Path
from src.parsing import parse_resume

# Test files
PDF_SIMPLE = Path("tests/test_data/pdfs/simple.pdf")
PDF_TABLES = Path("tests/test_data/pdfs/tables.pdf")
DOCX_SIMPLE = Path("tests/test_data/docs/simple.docx")
DOCX_TABLES = Path("tests/test_data/docs/tables.docx")

def test_pdf_parsing():
    """Test basic PDF parsing - now returns DICT not text"""
    data = parse_resume(str(PDF_SIMPLE))
    assert data, "Failed to extract resume"
    assert isinstance(data, dict), "Should return dictionary"
    # Check if we extracted any structured data
    assert any([data.get("skills"), data.get("education"), data.get("experience")])

def test_pdf_tables():
    """Test PDF with tables - check if any content is extracted"""
    data = parse_resume(str(PDF_TABLES))
    assert data, "Failed to extract table content"
    # Check if any meaningful data was extracted
    assert any([data.get("skills"), data.get("education"), data.get("experience")])

def test_docx_parsing():
    """Test basic DOCX parsing - returns structured dict"""
    data = parse_resume(str(DOCX_SIMPLE))
    assert data, "Failed to extract DOCX"
    assert isinstance(data, dict), "Should return dictionary"
    assert any([data.get("skills"), data.get("education"), data.get("experience")])

def test_docx_tables():
    """Test DOCX with skill tables - check if any skills are detected"""
    data = parse_resume(str(DOCX_TABLES))
    assert data, "Failed to extract DOCX with tables"
    # Check if we got any skills or content
    assert any([data.get("skills"), data.get("education"), data.get("experience")])

def test_education_experience_grouping():
    from src.parsing.enhanced_parser import parse_education_section, parse_experience_section

    edu = parse_education_section("• Bachelor Of Science\n• (Stanford)")
    assert len(edu) == 1
    assert "Bachelor Of Science" in edu[0]
    assert "Stanford" in edu[0]

    exp = parse_experience_section(
        "• . Two years of working experience\n"
        "• in Data Analysis team of LIGO Scientific Collaboration [$3M Special Breakthrough Prize winner of\n"
        "• 2016]. Over ten years of successful research experience in both theoretical and computational"
    )
    assert len(exp) == 1
    assert "Two years of working experience" in exp[0]
    assert "LIGO Scientific Collaboration" in exp[0]


def test_bullet_only_experience_merges_into_one_item():
    from src.parsing.enhanced_parser import parse_experience_section

    exp = parse_experience_section(
        "• ¢ Developing predictive models to improve decision\n"
        "• making processes.\n"
        "• ¢ Gaining hands"
    )
    assert len(exp) == 1
    assert "Developing predictive models to improve decision" in exp[0]
    assert "making processes." in exp[0]
    assert "Gaining hands" in exp[0]
    assert "¢" not in exp[0]


def test_emoji_headings_and_experience_bullets():
    from src.parsing.enhanced_parser import enhanced_extract_sections

    sample = (
        "🎓 Education:\n\n—\n\n💼 Experience:\n\n"
        "• Decent knowledge MVC Architecture FrameWorks: Cccoa Touch\n\n"
        "• Experience in using SOAP, REST\n\n"
        "• based Web Services"
    )
    data = enhanced_extract_sections(sample)
    assert data["education"] == []
    assert len(data["experience"]) == 1
    assert "Decent knowledge MVC Architecture FrameWorks" in data["experience"][0]
    assert "Experience in using SOAP, REST" in data["experience"][0]
    assert "based Web Services" in data["experience"][0]


def test_error_handling():
    """Test invalid files"""
    with pytest.raises(ValueError):
        parse_resume("invalid_file.txt")


if __name__ == "__main__":
    # Run all tests manually
    print("🚀 Running Resume Parser Tests...")
    print("=" * 50)
    
    tests = [
        test_pdf_parsing,
        test_pdf_tables, 
        test_docx_parsing,
        test_docx_tables,
        test_error_handling
    ]
    
    passed = 0
    failed = 0
    
    for test_func in tests:
        try:
            test_func()
            print(f"✅ {test_func.__name__} - PASSED")
            passed += 1
        except Exception as e:
            print(f"❌ {test_func.__name__} - FAILED: {e}")
            failed += 1
    
    print("=" * 50)
    print(f"Results: {passed} passed, {failed} failed")
    
    if failed > 0:
        exit(1)  # Exit with error code if any tests failed