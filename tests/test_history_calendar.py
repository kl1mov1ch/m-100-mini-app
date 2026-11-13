from test_workspaces import client as client


def test_history_groups_reports_and_marks_days_outside_selected_range(client):
    all_data = client.get("/api/analytics?project_id=default").json()
    assert all_data["work_dates"]
    date = all_data["work_dates"][0]
    filtered = client.get(f"/api/analytics?project_id=default&start={date}&end={date}").json()
    assert filtered["work_dates"] == all_data["work_dates"]
    assert all(row["date"] == date for row in filtered["rows"])
    keys = [(row["project_id"], row["date"]) for row in all_data["rows"]]
    assert len(keys) == len(set(keys))
    project = client.get("/api/session").json()["projects"][0]
    assert "today_sync_status" in project
