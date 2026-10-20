"""graphrag-server package."""

try:
    from graphrag_server.local_embedding import LocalTfidfEmbeddingModel
    from graphrag.language_model.factory import ModelFactory

    ModelFactory.register_embedding("local_tfidf", lambda **kwargs: LocalTfidfEmbeddingModel(**kwargs))
except Exception:
    pass
