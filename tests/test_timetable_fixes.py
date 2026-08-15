import pytest
import datetime
from pydantic import ValidationError
from core.utils.program import normalize_program_name, resolve_program
from dau_mcp.timetable_mcp_server import find_programs_common_free_time, ProgramQuery, get_program_timetable
from api.services import timetable_service
import asyncio

def test_normalization_parity():
    # B.Tech == B Tech != B Tech ICT-CS
    p1 = normalize_program_name("B.Tech ICT")
    p2 = normalize_program_name("B Tech ICT")
    p3 = normalize_program_name("BTech ICT")
    p4 = normalize_program_name("B Tech ICT-CS")
    
    assert p1 == p2 == p3
    assert p1 != p4

def test_exact_programme_distinction():
    p1 = normalize_program_name("B Tech (ICT)")
    p2 = normalize_program_name("B Tech (ICT and CS)")
    assert p1 != p2

def test_unknown_programme_resolution():
    res = resolve_program("Fake Program Name")
    assert res == []

def test_ambiguous_programme_resolution(monkeypatch):
    # Mock db response to have multiple matches
    def mock_db_connection():
        class MockConn:
            def __enter__(self): return self
            def __exit__(self, *args): pass
            def cursor(self):
                class MockCur:
                    def __enter__(self): return self
                    def __exit__(self, *args): pass
                    def execute(self, *args): pass
                    def fetchall(self):
                        return [("B Tech (ICT)",), ("B Tech ICT",)]
                return MockCur()
        return MockConn()
        
    monkeypatch.setattr("core.utils.program.db_connection", mock_db_connection)
    res = resolve_program("B Tech (ICT)")
    assert len(res) == 2
    assert "B Tech (ICT)" in res
    assert "B Tech ICT" in res

@pytest.mark.asyncio
async def test_find_programs_common_free_time_validation():
    # Empty programs list
    res = await find_programs_common_free_time(programs=[], day="Monday")
    assert "Please provide at least one valid programme name" in res
    
    # Missing program name
    try:
        ProgramQuery(semester="7")
        assert False, "Should raise ValidationError"
    except ValidationError:
        pass

@pytest.mark.asyncio
async def test_find_programs_common_free_time_unknown_program(monkeypatch):
    # Mock resolve_program to return []
    monkeypatch.setattr("dau_mcp.timetable_mcp_server.resolve_program", lambda x: [])
    query = ProgramQuery(program_name="MSc XYZ")
    res = await find_programs_common_free_time([query], day="Monday")
    assert "I couldn't find the programme 'MSc XYZ'" in res

@pytest.mark.asyncio
async def test_find_programs_common_free_time_ambiguous_program(monkeypatch):
    # Mock resolve_program to return multiple
    monkeypatch.setattr("dau_mcp.timetable_mcp_server.resolve_program", lambda x: ["Prog 1", "Prog 2"])
    query = ProgramQuery(program_name="Prog")
    res = await find_programs_common_free_time([query], day="Monday")
    assert "is ambiguous. It could match: Prog 1, Prog 2." in res

