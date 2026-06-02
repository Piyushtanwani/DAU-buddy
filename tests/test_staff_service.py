"""
Test Staff Service
==================
Unit tests for the staff service database query helpers.

Run with:
    python -m pytest tests/ -v
"""
import pytest
from unittest.mock import patch, MagicMock


class TestStaffService:

    @patch("api.services.staff_service.db_connection")
    def test_list_all_staff_db_returns_formatted_output(self, mock_db):
        """list_all_staff_db should return a markdown directory."""
        mock_cursor = MagicMock()
        mock_cursor.fetchall.return_value = [
            ("Test Staff", "staff@daiict.ac.in", "Registrar Executive"),
        ]
        mock_conn = MagicMock()
        mock_conn.__enter__ = MagicMock(return_value=mock_conn)
        mock_conn.__exit__ = MagicMock(return_value=False)
        mock_conn.cursor.return_value.__enter__ = MagicMock(return_value=mock_cursor)
        mock_conn.cursor.return_value.__exit__ = MagicMock(return_value=False)
        mock_db.return_value = mock_conn

        from api.services.staff_service import list_all_staff_db
        result = list_all_staff_db()
        assert "Test Staff" in result
        assert "DA-IICT Staff Directory" in result

    @patch("api.services.staff_service.db_connection")
    def test_list_all_staff_db_empty_returns_message(self, mock_db):
        """list_all_staff_db should handle empty DB gracefully."""
        mock_cursor = MagicMock()
        mock_cursor.fetchall.return_value = []
        mock_conn = MagicMock()
        mock_conn.__enter__ = MagicMock(return_value=mock_conn)
        mock_conn.__exit__ = MagicMock(return_value=False)
        mock_conn.cursor.return_value.__enter__ = MagicMock(return_value=mock_cursor)
        mock_conn.cursor.return_value.__exit__ = MagicMock(return_value=False)
        mock_db.return_value = mock_conn

        from api.services.staff_service import list_all_staff_db
        result = list_all_staff_db()
        assert "no staff" in result.lower() or "sync" in result.lower()
