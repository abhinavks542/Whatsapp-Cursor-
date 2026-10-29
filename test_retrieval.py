import ingestion.retrieval as retrieval


def test_candidate_pairs_with_tied_scores_preserve_input_order(monkeypatch):
    pairs = [
        {"conversation_id": "family", "their_message": "hello there", "my_reply": "first"},
        {"conversation_id": "family", "their_message": "hello again", "my_reply": "second"},
    ]
    monkeypatch.setattr(retrieval, "_load_pairs", lambda: pairs)

    result = retrieval._candidate_pairs("family", "hello")

    assert result == pairs
