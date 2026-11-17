from datavault.cli import main


def test_cli_demo(capsys):
    assert main(["demo"]) == 0
    out = capsys.readouterr().out
    assert "Data Vault 2.0" in out
    assert "audit log" in out


def test_cli_load_demo(capsys):
    assert main(["load-demo"]) == 0
    assert "hubs=" in capsys.readouterr().out


def test_cli_pit(capsys):
    assert main(["pit", "--entity", "customer", "--business-key", "CUST-1001",
                 "--as-of", "2026-03-31T00:00:00Z"]) == 0
    assert "Riverton" in capsys.readouterr().out


def test_cli_pit_before_history_returns_1():
    assert main(["pit", "--entity", "customer", "--business-key", "CUST-1001",
                 "--as-of", "2026-01-01T00:00:00Z"]) == 1


def test_cli_marts(capsys):
    assert main(["marts", "--as-of", "2026-03-31T00:00:00Z"]) == 0
    assert "fact_total_amount=" in capsys.readouterr().out


def test_cli_audit(capsys):
    assert main(["audit"]) == 0
    assert "chain_valid=True" in capsys.readouterr().out
