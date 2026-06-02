"""
Test Faculty Service
====================
Unit tests for the faculty service database query helpers.

Run with:
    python -m pytest tests/ -v
"""
import pytest
from unittest.mock import patch, MagicMock

# These tests mock the database so they run without a live PostgreSQL connection.


class TestFacultyService:

    @patch("api.services.faculty_service.db_connection")
    def test_list_all_faculty_db_returns_formatted_output(self, mock_db):
        """list_all_faculty_db should return a markdown directory."""
        mock_cursor = MagicMock()
        mock_cursor.fetchall.return_value = [
            ("Prof. Test", "test@daiict.ac.in", "Regular"),
        ]
        mock_conn = MagicMock()
        mock_conn.__enter__ = MagicMock(return_value=mock_conn)
        mock_conn.__exit__ = MagicMock(return_value=False)
        mock_conn.cursor.return_value.__enter__ = MagicMock(return_value=mock_cursor)
        mock_conn.cursor.return_value.__exit__ = MagicMock(return_value=False)
        mock_db.return_value = mock_conn

        from api.services.faculty_service import list_all_faculty_db
        result = list_all_faculty_db()
        assert "Prof. Test" in result
        assert "DA-IICT Faculty Directory" in result

    @patch("api.services.faculty_service.db_connection")
    def test_list_all_faculty_db_empty_returns_message(self, mock_db):
        """list_all_faculty_db should handle empty DB gracefully."""
        mock_cursor = MagicMock()
        mock_cursor.fetchall.return_value = []
        mock_conn = MagicMock()
        mock_conn.__enter__ = MagicMock(return_value=mock_conn)
        mock_conn.__exit__ = MagicMock(return_value=False)
        mock_conn.cursor.return_value.__enter__ = MagicMock(return_value=mock_cursor)
        mock_conn.cursor.return_value.__exit__ = MagicMock(return_value=False)
        mock_db.return_value = mock_conn

        from api.services.faculty_service import list_all_faculty_db
        result = list_all_faculty_db()
        assert "No faculty" in result.lower() or "sync" in result.lower()
