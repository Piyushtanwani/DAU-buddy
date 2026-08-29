import sqlite3
import pytest
import asyncio
from unittest.mock import MagicMock
from datetime import date

# Import the modules we are testing
from api.services import timetable_service
from api.services import venue_service
from dau_mcp import timetable_mcp_server

# -----------------------------------------------------------------------------------
# Test 1: Venue Boundary / Overlap Logic (using in-memory SQLite to test SQL logic)
# -----------------------------------------------------------------------------------

@pytest.fixture
def sqlite_db(mocker):
    """Sets up an in-memory SQLite database to test the overlap SQL logic."""
    conn = sqlite3.connect(":memory:")
    # Create a dummy timetables table
    conn.execute('''
        CREATE TABLE timetables (
            room TEXT,
            day_of_week TEXT,
            start_time TEXT,
            end_time TEXT,
            session_type TEXT,
            course_code TEXT,
            course_name TEXT,
            faculty_name TEXT,
            program TEXT
        )
    ''')
    # Create venues table for metadata
    conn.execute('''
        CREATE TABLE venues (
            venue_id TEXT,
            capacity INTEGER,
            venue_type TEXT,
            booking_poc TEXT
        )
    ''')
    conn.commit()

    # Mock psycopg2 db_connection to return our sqlite connection
    mock_conn = MagicMock()
    mock_cur = conn.cursor()
    
    # We need to monkey-patch execute to strip ::TIME which is Postgres specific
    class MockCursor:
        def __init__(self, cur):
            self._cur = cur
        def execute(self, query, params=()):
            sqlite_query = query.replace("::TIME", "")
            # SQLite uses ? instead of %s
            sqlite_query = sqlite_query.replace("%s", "?")
            # ILIKE is just LIKE in SQLite
            sqlite_query = sqlite_query.replace("ILIKE", "LIKE")
            return self._cur.execute(sqlite_query, params)
        def fetchall(self):
            return self._cur.fetchall()
        def __enter__(self):
            return self
        def __exit__(self, *args):
            pass

    mock_cur = MockCursor(conn.cursor())
    
    mock_conn.__enter__.return_value = mock_conn
    mock_conn.cursor.return_value = mock_cur
    
    mocker.patch('api.services.timetable_service.db_connection', return_value=mock_conn)
    mocker.patch('api.services.venue_service.db_connection', return_value=mock_conn)
    
    return conn

@pytest.mark.parametrize("req_start, req_end, occ_start, occ_end, expected_available", [
    # Test 1 - Overlap
    ("14:00", "16:00", "15:00", "16:00", False),
    # Test 2 - Exact preceding boundary
    ("14:00", "16:00", "12:00", "14:00", True),
    # Test 3 - Exact following boundary
    ("14:00", "16:00", "16:00", "18:00", True),
    # Test 4 - Completely inside
    ("14:00", "18:00", "15:00", "16:00", False),
    # Test 5 - Completely surrounds
    ("15:00", "16:00", "14:00", "18:00", False),
])
def test_venue_overlap_logic(sqlite_db, mocker, req_start, req_end, occ_start, occ_end, expected_available):
    """
    Tests the 5 interval-boundary cases requested for venue availability overlap.
    """
    # Insert the occupied session
    sqlite_db.execute(
        "INSERT INTO timetables (room, day_of_week, start_time, end_time) VALUES (?, ?, ?, ?)",
        ("CEP-102", "Monday", occ_start, occ_end)
    )
    # Insert the venue metadata
    sqlite_db.execute(
        "INSERT INTO venues (venue_id, capacity, venue_type, booking_poc) VALUES (?, ?, ?, ?)",
        ("CEP-102", 100, "room", "poc@example.com")
    )
    sqlite_db.commit()

    import api.services.venue_service as vs
    mocker.patch.object(vs, 'get_venues_by_ids', return_value={'CEP-102': {
        'venue_id': 'CEP-102', 'capacity': 100, 'venue_type': 'room', 'booking_poc': 'poc@example.com'
    }})

    # Query for free venues
    results = timetable_service.find_free_venues("Monday", req_start, req_end)
    
    # Extract venue IDs from results
    available_venues = [r['venue_id'] for r in results]
    
    if expected_available:
        assert "CEP-102" in available_venues, f"Expected CEP-102 to be available for req {req_start}-{req_end} with occ {occ_start}-{occ_end}"
    else:
        assert "CEP-102" not in available_venues, f"Expected CEP-102 to be UNAVAILABLE for req {req_start}-{req_end} with occ {occ_start}-{occ_end}"


# -----------------------------------------------------------------------------------
# Test 2: MCP Tool Unknown Venue Flow
# -----------------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_check_venue_availability_unknown_venue(mocker):
    """
    Tests that querying an unknown venue returns a clear 'not found' message
    instead of falsely reporting it as available.
    """
    # Mock timetable to return None (no sessions found)
    mocker.patch.object(timetable_service, 'get_venue_availability', return_value=None)
    
    # Mock venue metadata to return None (venue doesn't exist)
    mocker.patch.object(venue_service, 'get_venue', return_value=None)
    
    result = await timetable_mcp_server.check_venue_availability("CEP-999", day="Monday", time="10:00")
    
    assert "Venue 'CEP-999' not found in our records" in result

@pytest.mark.asyncio
async def test_check_venue_availability_known_free_venue(mocker):
    """
    Tests that querying a known, free venue returns its metadata (capacity/POC).
    """
    mocker.patch.object(timetable_service, 'get_venue_availability', return_value=None)
    mocker.patch.object(venue_service, 'get_venue', return_value={
        'venue_id': 'CEP-102',
        'capacity': 182,
        'venue_type': 'room',
        'booking_poc': 'poc@example.com'
    })
    
    result = await timetable_mcp_server.check_venue_availability("CEP-102", day="Monday", time="10:00")
    
    assert "is free at" in result
    assert "Cap: 182" in result
    assert "POC: poc@example.com" in result


# -----------------------------------------------------------------------------------
# Test 3: MCP Tool Default Duration Logic
# -----------------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_find_available_venues_default_duration(mocker):
    """
    Tests that if only start_time is provided, end_time is derived using the 60-minute default.
    """
    mocker.patch.object(timetable_mcp_server.config, 'DEFAULT_VENUE_DURATION_MINUTES', 60)
    mock_find = mocker.patch.object(timetable_service, 'find_free_venues', return_value=[])
    
    await timetable_mcp_server.find_available_venues(
        min_capacity=10, 
        day="Monday", 
        start_time="14:00"
    )
    
    # It should pass "15:00" as the end_time to the service
    mock_find.assert_called_once_with("Monday", "14:00", "15:00")

@pytest.mark.asyncio
async def test_find_available_venues_explicit_duration(mocker):
    """
    Tests that if end_time is explicitly provided, the default is ignored.
    """
    mock_find = mocker.patch.object(timetable_service, 'find_free_venues', return_value=[])
    
    await timetable_mcp_server.find_available_venues(
        min_capacity=10, 
        day="Monday", 
        start_time="14:00",
        end_time="18:00"
    )
    
    # It should pass "18:00" as the end_time to the service
    mock_find.assert_called_once_with("Monday", "14:00", "18:00")
