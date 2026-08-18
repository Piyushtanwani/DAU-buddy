import pytest
from dau_mcp.timetable_mcp_server import _check_working_hours

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
    assert err is not None
    assert "Saturday and Sunday are off" in err

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
    assert "cannot be earlier than start time" in err

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
    
    # 24-hour parsing
    err, start, _ = _check_working_hours(day="Monday", time_str="14:00")
    assert err is None
    assert start == "14:00"

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
