import typing
import strawberry

@strawberry.type
class Book:
    title: str
    author: str

def get_books():
    return [
        Book(
            title="Hello World",
            author="Peng Wang",
        ),
        Book(
            title="Hello World2",
            author="Peng Wang2",
        ),
    ]

@strawberry.type
class Query:
    books: typing.List[Book] = strawberry.field(resolver=get_books)

schema = strawberry.Schema(query=Query)
