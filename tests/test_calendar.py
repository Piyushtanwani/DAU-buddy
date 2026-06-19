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
