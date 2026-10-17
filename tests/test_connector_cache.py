import json

from email_processing import connector as connector_module
from email_processing.connector import EmailConnector


class NoopSpinner:
    def __init__(self, message=""):
        self.message = message

    def start(self):
        pass

    def stop(self):
        pass


class FakeIMAPConnection:
    def __init__(self, uidvalidity="1", uids=(b"42",)):
        self.uidvalidity = uidvalidity
        self.uids = uids
        self.folder = None

    def select(self, folder):
        self.folder = folder.strip('"')
        return "OK", [b"0"]

    def response(self, code):
        assert code == "UIDVALIDITY"
        return "UIDVALIDITY", [self.uidvalidity.encode()]

    def uid(self, command, *args):
        assert command == "search"
        return "OK", [b" ".join(self.uids)]

    def search(self, charset, criteria):
        return "OK", [b" ".join(self.uids)]


def _search(connector, folder):
    return connector.search_emails(folder, {"subject": 'SUBJECT "shipment"'})


def test_processed_uids_are_isolated_by_folder_and_persisted(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(connector_module, "ProgressSpinner", NoopSpinner)
    connector = EmailConnector("buyer@example.test", "unused", "gmail")
    connector.connection = FakeIMAPConnection(uidvalidity="7")

    assert _search(connector, "Folders/Shopping/Apple") == (True, [b"42"])
    connector.mark_uid_processed(b"42")

    # The same numeric UID in another mailbox is a different message.
    assert _search(connector, "All Mail") == (True, [b"42"])

    connector.save_progress()
    reloaded = EmailConnector("buyer@example.test", "unused", "gmail")
    reloaded.connection = FakeIMAPConnection(uidvalidity="7")
    assert _search(reloaded, "Folders/Shopping/Apple") == (True, [])
    assert _search(reloaded, "All Mail") == (True, [b"42"])


def test_uidvalidity_change_starts_a_fresh_mailbox_cache(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(connector_module, "ProgressSpinner", NoopSpinner)
    connector = EmailConnector("buyer@example.test", "unused", "gmail")
    connector.connection = FakeIMAPConnection(uidvalidity="7")
    assert _search(connector, "Folders/Shopping/Apple") == (True, [b"42"])
    connector.mark_uid_processed(b"42")
    connector.save_progress()

    reloaded = EmailConnector("buyer@example.test", "unused", "gmail")
    reloaded.connection = FakeIMAPConnection(uidvalidity="8")
    assert _search(reloaded, "Folders/Shopping/Apple") == (True, [b"42"])


def test_legacy_flat_cache_is_not_applied_to_every_folder(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(connector_module, "ProgressSpinner", NoopSpinner)
    cache_file = tmp_path / "cache" / "processed_uids_buyer_example_test.json"
    cache_file.parent.mkdir()
    cache_file.write_text(json.dumps(["42", "99"]))

    connector = EmailConnector("buyer@example.test", "unused", "gmail")
    connector.connection = FakeIMAPConnection(uidvalidity="7")

    assert _search(connector, "Folders/Shopping/Apple") == (True, [b"42"])


def test_cache_bypass_does_not_save_sequence_numbers_as_uids(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(connector_module, "ProgressSpinner", NoopSpinner)
    connector = EmailConnector("buyer@example.test", "unused", "gmail")
    connector.connection = FakeIMAPConnection(uidvalidity="7")

    found, message_numbers = connector.search_emails(
        "Folders/Shopping/Apple",
        {"subject": 'SUBJECT "shipment"'},
        use_uid_filter=False,
    )
    assert found is True
    assert message_numbers == [b"42"]

    connector.mark_uid_processed(message_numbers[0])

    assert connector.processed_uids == set()
