rfg-status:
    python3 rfg.py status --format json

rfg-doctor:
    python3 rfg.py doctor --format json

rfg-next:
    python3 rfg.py next --format json

test:
    PYTHONPATH=. python3 -m unittest discover -s tests -q
