import pytest
from dau_mcp.timetable_mcp_server import _check_working_hours, find_free_venues, find_available_venues, check_venue_availability
from unittest.mock import patch

def test_working_hours_boundaries():
    # 07:59 -> rejected
    err, _, _ = _check_working_hours(day="Monday", time_str="07:59")
    assert err is not None
    assert "outside college working hours" in err

    # 08:00 -> accepted
    err, start, _ = _check_working_hours(day="Monday", time_str="08:00")
    assert err is None
    assert start == "08:00"

    # 17:59 -> accepted
    err, start, _ = _check_working_hours(day="Monday", time_str="17:59")
    assert err is None
    assert start == "17:59"

    # 18:00 -> rejected
    err, _, _ = _check_working_hours(day="Monday", time_str="18:00")
    assert err is not None
    assert "outside college working hours" in err

def test_working_hours_weekends():
    # Saturday
    err, _, _ = _check_working_hours(day="Saturday", time_str="10:00")
    assert err is not None
    assert "Saturday and Sunday are off" in err

    # Sunday
    err, _, _ = _check_working_hours(day="Sunday", time_str="10:00")
    assert err is not None
    assert "Saturday and Sunday are off" in err

    # Saturday without time
    err, _, _ = _check_working_hours(day="Saturday")
    assert err is None

    # Sunday without time
    err, _, _ = _check_working_hours(day="Sunday")
    assert err is None

def test_working_hours_intervals_and_clamp():
    # Venue request 17:00-18:00 -> accepted on boundary
    err, start, end = _check_working_hours(day="Monday", time_str="17:00", end_time_str="18:00")
    assert err is None
    assert start == "17:00"
    assert end == "18:00"

    # Venue request 17:30-18:30 -> rejected
    err, _, _ = _check_working_hours(day="Monday", time_str="17:30", end_time_str="18:30")
    assert err is not None
    assert "outside college working hours" in err

    # Venue request 15:00-14:00 -> rejected (end before start)
    err, _, _ = _check_working_hours(day="Monday", time_str="15:00", end_time_str="14:00")
    assert err is not None
    assert "must be later than start time" in err

    # Derived end time clamping
    # 17:15 start with derived end time -> clamps end to 18:00
    err, start, end = _check_working_hours(day="Monday", time_str="17:15", end_time_str="18:15", is_derived_end_time=True)
    assert err is None
    assert start == "17:15"
    assert end == "18:00"

def test_working_hours_formats():
    # 12-hour parsing 
    err, start, _ = _check_working_hours(day="Monday", time_str="2:00 PM")
    assert err is None
    assert start == "14:00"
    
    err, start, _ = _check_working_hours(day="Monday", time_str="5:30 PM")
    assert err is None
    assert start == "17:30"
    
    err, start, _ = _check_working_hours(day="Monday", time_str="8:00 AM")
    assert err is None
    assert start == "08:00"
    
    err, _, _ = _check_working_hours(day="Monday", time_str="6:00 PM")
    assert err is not None
    assert "outside college working hours" in err
    
    # 24-hour parsing
    err, start, _ = _check_working_hours(day="Monday", time_str="14:00")
    assert err is None
    assert start == "14:00"

    # Explicit end time with 12-hour
    err, start, end = _check_working_hours(day="Monday", time_str="5:00 PM", end_time_str="6:00 PM")
    assert err is None
    assert start == "17:00"
    assert end == "18:00"

    err, start, end = _check_working_hours(day="Monday", time_str="5:30 PM", end_time_str="6:30 PM")
    assert err is not None
    assert "outside college working hours" in err

def test_working_hours_day_all():
    # Explicitly verify day="All" does not get rejected
    err, _, _ = _check_working_hours(day="All")
    assert err is None
    
    err, _, _ = _check_working_hours(day="All", time_str="10:00")
    assert err is None

def test_working_hours_venue_query():
    # Venue queries out of hours should include contact info
    err, _, _ = _check_working_hours(day="Saturday", time_str="10:00", is_venue_query=True)
    assert err is not None
    assert "All classrooms are free outside regular hours" in err
    assert "prabhunath_sharma@dau.ac.in" in err

    err, _, _ = _check_working_hours(day="Monday", time_str="20:00", is_venue_query=True)
    assert err is not None
    assert "All classrooms are free outside regular hours" in err
    assert "prabhunath_sharma@dau.ac.in" in err

@pytest.mark.asyncio
async def test_find_free_venues_12hour():
    with patch("dau_mcp.timetable_mcp_server.timetable_service.find_free_venues") as mock_find:
        mock_find.return_value = [{"venue_id": "TEST-1", "capacity": 50}]
        
        # Monday 2:00 PM -> ✅ searches 14:00-15:00
        res = await find_free_venues(day="Monday", time="2:00 PM")
        assert "Free from 14:00 to 15:00" in res
        mock_find.assert_called_with("Monday", "14:00", "15:00")
        
        # Monday 5:30 PM -> ✅ searches 17:30-18:00 (clamped)
        res = await find_free_venues(day="Monday", time="5:30 PM")
        assert "Free from 17:30 to 18:00" in res
        
        # Monday 8:00 AM -> ✅ searches 08:00-09:00
        res = await find_free_venues(day="Monday", time="8:00 AM")
        assert "Free from 08:00 to 09:00" in res
        
        # Monday 6:00 PM -> ❌ rejected
        res = await find_free_venues(day="Monday", time="6:00 PM")
        assert "All classrooms are free outside regular hours" in res

@pytest.mark.asyncio
async def test_find_available_venues_12hour():
    with patch("dau_mcp.timetable_mcp_server.timetable_service.find_free_venues") as mock_find:
        mock_find.return_value = [{"venue_id": "TEST-1", "capacity": 50}]
        
        # Monday 2:00 PM -> ✅ searches 14:00-15:00
        res = await find_available_venues(min_capacity=10, day="Monday", start_time="2:00 PM")
        assert "Available venues (>= 10 capacity) from 14:00 to 15:00" in res
        mock_find.assert_called_with("Monday", "14:00", "15:00")
        
        # Monday 5:30 PM -> ✅ searches 17:30-18:00 (clamped)
        res = await find_available_venues(min_capacity=10, day="Monday", start_time="5:30 PM")
        assert "Available venues (>= 10 capacity) from 17:30 to 18:00" in res

@pytest.mark.asyncio
async def test_find_available_venues_explicit_end_time_error():
    res = await find_available_venues(min_capacity=50, day="Monday", start_time="10:00", end_time="19:00")
    assert "7:00 PM is outside college working hours" in res

@pytest.mark.asyncio
async def test_venue_day_only_queries():
    # Case A: Day only -> "Please specify a time..."
    res = await find_free_venues(day="Monday")
    assert "Please specify a time" in res
    
    res = await check_venue_availability(venue="CEP-102", day="Monday")
    assert "Please specify a time" in res
    
    res = await find_available_venues(min_capacity=50, day="Monday")
    assert "Please specify a time" in res

    # Case B: Right now (mock _campus_time to 19:30 out of hours)
    with patch("dau_mcp.timetable_mcp_server._campus_time") as mock_time:
        mock_time.return_value = "19:30:00"
        
        # It should reject with out of hours message
        res = await find_free_venues()
        assert "All classrooms are free outside regular hours" in res
        
        res = await check_venue_availability(venue="CEP-102")
        assert "All classrooms are free outside regular hours" in res
        
        res = await find_available_venues(min_capacity=50)
        assert "All classrooms are free outside regular hours" in res

    # Case C: Day + Time (mock find_free_venues inside timetable_service)
    with patch("dau_mcp.timetable_mcp_server.timetable_service.find_free_venues") as mock_svc:
        mock_svc.return_value = [{"venue_id": "CEP-102", "capacity": 50}]
        res = await find_free_venues(day="Monday", time="14:00")
        assert "Free from 14:00 to 15:00 on Monday" in res
