"""Review comments kept inside the markdown as tagged HTML comments.

See README.md for the grammar and the workflow.
"""

from importlib.metadata import PackageNotFoundError, version

try:
    __version__ = version("mkdocs-review-comments")  # pyproject.toml is the single source
except PackageNotFoundError:  # running from a checkout that is not installed
    __version__ = "0.0.0"
