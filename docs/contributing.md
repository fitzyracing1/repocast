# Contributing

```bash
pip install -e .
python -m unittest discover -s tests -v
```

Keep the runtime on the standard library only. Any change to composing or the gate must keep `tests/test_examples.py` passing, including the expected x-algorithm posts.
