import os
import sys
import pytest

# Ensure we can import from core/api
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from api.services.retrieval import PostgresFullTextRetriever

@pytest.fixture
def retriever():
    return PostgresFullTextRetriever()

def test_retrieve_faculty_basic(retriever):
    """Test retrieving faculty returns a list of dictionaries with correct keys."""
    results = retriever.retrieve_faculty("machine learning", limit=5)
    assert isinstance(results, list)
    if results:
        assert "name" in results[0]
        assert "specialization" in results[0]
        assert "relevance_score" in results[0]

def test_retrieve_staff_basic(retriever):
    """Test retrieving staff returns a list of dictionaries with correct keys."""
    results = retriever.retrieve_staff("finance", limit=5)
    assert isinstance(results, list)
    if results:
        assert "name" in results[0]
        assert "designation" in results[0]
        assert "relevance_score" in results[0]

def test_retrieve_empty_query(retriever):
    """Test that empty queries return empty lists."""
    assert retriever.retrieve_faculty("") == []
    assert retriever.retrieve_faculty("   ") == []
    assert retriever.retrieve_staff("") == []
    assert retriever.retrieve_staff("   ") == []

def test_retrieve_respects_limit(retriever):
    """Test that the retrieval limits are respected."""
    # Assuming there are at least 3 faculties in DB
    results = retriever.retrieve_faculty("a", limit=2)
    assert len(results) <= 2
