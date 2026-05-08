from src.memory.stores.neo4j_store import Neo4jStore


class FakeNode(dict):
    def __init__(self, labels, **props):
        super().__init__(props)
        self.labels = set(labels)


class FakeSession:
    def __init__(self, records):
        self.records = records

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def run(self, _query, **_params):
        return self.records


class FakeDriver:
    def __init__(self, records):
        self.records = records

    def session(self):
        return FakeSession(self.records)


def make_store(records):
    store = Neo4jStore.__new__(Neo4jStore)
    store.driver = FakeDriver(records)
    return store


def test_explorer_overview_curates_roots_and_hides_isolated_artifacts():
    records = [
        {
            "root": FakeNode(["Belief"], id="belief_1", name="Need more sleep"),
            "neighbor": FakeNode(["Person"], id="entity_1", name="Kevin"),
            "rel_type": "ABOUT",
            "source_id": "belief_1",
            "target_id": "entity_1",
        },
        {
            "root": FakeNode(["Task"], id="task_1", name="Fix explorer"),
            "neighbor": FakeNode(["Project"], id="project_1", name="AIManager"),
            "rel_type": "WORKS_ON",
            "source_id": "task_1",
            "target_id": "project_1",
        },
        {
            "root": FakeNode(["Project"], id="project_isolated", name="Chat-only project"),
            "neighbor": None,
            "rel_type": None,
            "source_id": None,
            "target_id": None,
        },
        {
            "root": FakeNode(["Project"], id="topic_deadbeef", name="Explorer Provenance"),
            "neighbor": None,
            "rel_type": None,
            "source_id": None,
            "target_id": None,
        },
    ]
    store = make_store(records)

    overview = store.get_explorer_graph_overview(limit=100)

    node_ids = {node["id"] for node in overview["nodes"]}
    edge_types = {edge["type"] for edge in overview["edges"]}

    assert node_ids == {"belief_1", "entity_1", "task_1", "project_1"}
    assert edge_types == {"ABOUT", "WORKS_ON"}
    assert "project_isolated" not in node_ids
    assert "topic_deadbeef" not in node_ids


def test_list_active_tasks_queries_tasks_directly():
    records = [
        {
            "id": "task_1",
            "name": "Fix explorer",
            "status": "TODO",
            "priority": "high",
            "due_date": "2026-05-10",
        },
        {
            "id": "task_2",
            "name": "Clean graph",
            "status": "IN_PROGRESS",
            "priority": "medium",
            "due_date": None,
        },
    ]
    store = make_store(records)

    tasks = store.list_active_tasks()

    assert tasks == [
        {
            "id": "task_1",
            "name": "Fix explorer",
            "status": "TODO",
            "priority": "high",
            "due_date": "2026-05-10",
            "label": "Task",
        },
        {
            "id": "task_2",
            "name": "Clean graph",
            "status": "IN_PROGRESS",
            "priority": "medium",
            "due_date": None,
            "label": "Task",
        },
    ]
