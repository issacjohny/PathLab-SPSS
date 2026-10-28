"""Developer attribution shared by the package, reports and diagrams."""

AUTHOR = "Dr. B. Issac Johny"
TITLE = "Professor"
AFFILIATION = "Gnanam School of Business, Thanjavur"
CREDIT = "Developed by " + AUTHOR
CREDIT_BLOCK = "\n".join((CREDIT, TITLE, AFFILIATION))


def developer_metadata():
    return {"name": AUTHOR, "title": TITLE, "affiliation": AFFILIATION,
            "credit": CREDIT}
