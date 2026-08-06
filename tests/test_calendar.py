import pytest
from datetime import date
from api.services import calendar_service

def test_get_next_holiday(mocker):
    # Mock db_connection and cursor
    mock_conn = mocker.MagicMock()
    mock_cur = mocker.MagicMock()
    
    mock_conn.__enter__.return_value = mock_conn
    mock_conn.cursor.return_value.__enter__.return_value = mock_cur
    
    mocker.patch('api.services.calendar_service.db_connection', return_value=mock_conn)
    
    mock_cur.fetchone.return_value = {
        'holiday_date': date(2026, 8, 15),
        'holiday_name': 'Independence Day',
        'day_of_week': 'Saturday',
        'raw_date_text': '15 August'
    }
    
    result = calendar_service.get_next_holiday()
    assert result is not None
    assert result['holiday_name'] == 'Independence Day'

def test_get_upcoming_holidays(mocker):
    mock_conn = mocker.MagicMock()
    mock_cur = mocker.MagicMock()
    
    mock_conn.__enter__.return_value = mock_conn
    mock_conn.cursor.return_value.__enter__.return_value = mock_cur
    
    mocker.patch('api.services.calendar_service.db_connection', return_value=mock_conn)
    
    mock_cur.fetchall.return_value = [
        {
            'holiday_date': date(2026, 8, 15),
            'holiday_name': 'Independence Day',
            'day_of_week': 'Saturday',
            'raw_date_text': '15 August'
        },
        {
            'holiday_date': date(2026, 10, 2),
            'holiday_name': 'Gandhi Jayanti',
            'day_of_week': 'Friday',
            'raw_date_text': '2 October'
        }
    ]
    
    results = calendar_service.get_upcoming_holidays(limit=2)
    assert len(results) == 2
    assert results[0]['holiday_name'] == 'Independence Day'

def test_get_midsem_dates(mocker):
    mock_conn = mocker.MagicMock()
    mock_cur = mocker.MagicMock()
    
    mock_conn.__enter__.return_value = mock_conn
    mock_conn.cursor.return_value.__enter__.return_value = mock_cur
    
    mocker.patch('api.services.calendar_service.db_connection', return_value=mock_conn)
    
    mock_cur.fetchall.return_value = [
        {
            'event_name': 'Mid Semester Examinations',
            'start_date': date(2026, 9, 20),
            'end_date': date(2026, 9, 25),
            'raw_date_text': '20 - 25 September',
            'semester_type': 'Autumn 2026'
        }
    ]
    
    results = calendar_service.get_midsem_dates()
    assert len(results) == 1
    assert "Mid" in results[0]['event_name']

def test_search_calendar(mocker):
    mock_conn = mocker.MagicMock()
    mock_cur = mocker.MagicMock()
    
    mock_conn.__enter__.return_value = mock_conn
    mock_conn.cursor.return_value.__enter__.return_value = mock_cur
    
    mocker.patch('api.services.calendar_service.db_connection', return_value=mock_conn)
    
    # search_calendar makes 2 executes/fetchall calls
    mock_cur.fetchall.side_effect = [
        [
            {
                'event_name': 'Diwali Break',
                'start_date': date(2026, 11, 1),
                'end_date': date(2026, 11, 5),
                'raw_date_text': '1 - 5 November',
                'semester_type': 'Autumn 2026'
            }
        ], # First call for academic
        [
            {
                'holiday_date': date(2026, 11, 4),
                'holiday_name': 'Diwali',
                'day_of_week': 'Wednesday',
                'raw_date_text': '4 November'
            }
        ]  # Second call for holidays
    ]
    
    results = calendar_service.search_calendar("diwali")
    assert len(results['academic_events']) == 1
    assert len(results['holidays']) == 1
    assert results['holidays'][0]['holiday_name'] == 'Diwali'


# ── Day-order substitution ────────────────────────────────────────────────────
# The academic calendar reassigns individual dates ("07-08-2026 to be treated as
# Tuesday"). On those days the campus runs the substituted day's timetable, so a
# schedule lookup keyed off the real weekday returns the wrong classes.

@pytest.mark.parametrize("event_name,expected", [
    ("To be treated as Tuesday", "Tuesday"),
    ("To be Treated as Friday", "Friday"),          # capitalisation varies in the data
    ("to be treated as    wednesday", "Wednesday"), # whitespace varies too
    ("Orientation of Fresh BTech Students", None),
    ("Instruction begins", None),
    ("", None),
])
def test_parse_day_substitution(event_name, expected):
    assert calendar_service._parse_day_substitution([event_name]) == expected


def test_parse_day_substitution_picks_it_out_of_a_crowded_day():
    """Substitutions share a date with orientation events, holidays, etc."""
    names = [
        "Orientation of Fresh BTech Students",
        "Orientation of Fresh BS-MS Students",
        "To be treated as Tuesday",
    ]
    assert calendar_service._parse_day_substitution(names) == "Tuesday"


def test_effective_day_substitutes(mocker):
    mocker.patch.object(calendar_service, "get_day_substitution", return_value="Tuesday")
    # 2026-08-07 is a Friday.
    assert calendar_service.effective_day(date(2026, 8, 7)) == ("Tuesday", "Friday")


def test_effective_day_passes_a_normal_day_through(mocker):
    mocker.patch.object(calendar_service, "get_day_substitution", return_value=None)
    assert calendar_service.effective_day(date(2026, 8, 6)) == ("Thursday", None)


def test_effective_day_ignores_a_substitution_to_the_same_day(mocker):
    """A calendar entry restating the real weekday is not a substitution."""
    mocker.patch.object(calendar_service, "get_day_substitution", return_value="Friday")
    assert calendar_service.effective_day(date(2026, 8, 7)) == ("Friday", None)


def test_get_day_substitution_degrades_instead_of_raising(mocker):
    """A calendar outage must not break every schedule answer."""
    mocker.patch.object(
        calendar_service, "db_connection", side_effect=RuntimeError("db down")
    )
    assert calendar_service.get_day_substitution("2026-08-07") is None
