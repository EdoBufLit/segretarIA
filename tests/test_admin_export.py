
import csv
import json
from datetime import datetime, timedelta
from io import StringIO
from unittest.mock import MagicMock
from admin_service import AdminService
from models import CallLog, User, Agent

def test_export_logs_csv_generator_db_only():
    # Setup Mock DB
    mock_db = MagicMock()

    # Setup Date Range
    from_date = datetime.utcnow() - timedelta(days=1)
    to_date = datetime.utcnow() + timedelta(days=1)

    # Setup Mock Data
    agent_id = "test_agent"
    timestamp = datetime.utcnow()

    raw_data = {
        "timestamp": timestamp.isoformat(),
        "agent_id": agent_id,
        "data": {
            "caller_number": "+123456789",
            "status": "success",
            "duration_secs": 120,
            "transcript_text": "Cliente: Ciao\nAgent: Buongiorno",
            "analysis": {
                "summary": "Chiamata di prova",
                "urgency": "bassa",
                "category": "info"
            }
        }
    }

    log_entry = CallLog(
        agent_id=agent_id,
        timestamp=timestamp,
        status="success",
        text="Chiamata di prova",
        raw_data=raw_data
    )

    # Mock Query
    mock_query = MagicMock()
    mock_db.query.return_value = mock_query
    mock_query.filter.return_value = mock_query
    mock_query.order_by.return_value = mock_query

    # Simulate batching: first call returns list with 1 item, second call returns empty list
    mock_query.offset.return_value.limit.return_value.all.side_effect = [[log_entry], []]

    # Init Service
    service = AdminService(mock_db)

    # Execute Generator
    generator = service.export_logs_csv_generator(from_date, to_date, client_filter=agent_id)

    # Consume Generator
    csv_content = "".join(list(generator))

    # Parse CSV
    f = StringIO(csv_content)
    reader = csv.DictReader(f)
    rows = list(reader)

    assert len(rows) == 1
    row = rows[0]

    # Verify Columns
    assert "Timestamp" in row
    assert "Caller" in row
    assert "Transcript" in row
    assert "AI_Analysis" in row
    assert "Status" in row

    # Verify Values
    assert row["AgentID"] == agent_id
    assert row["Caller"] == "+123456789"
    assert "Ciao" in row["Transcript"]
    assert "Prova" in row["AI_Analysis"] or "summary" in row["AI_Analysis"]
    assert row["Status"] == "success"
