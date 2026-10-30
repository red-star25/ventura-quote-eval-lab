"""Score quoting decisions against a catalog and business rules.

Fixture mode scores hand-written decisions. Live mode can call a model, then
scores the parsed decision with the same checker. Hybrid mode asks the model
only for customer facts, then applies the catalog rules. The model never
receives the labeled answer.
"""

__version__ = "0.2.4"
